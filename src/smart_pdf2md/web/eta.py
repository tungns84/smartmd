"""Time-remaining estimates for conversion jobs.

Everything is derived from persisted ``job_events`` rows, so a reloaded page is
accurate before SSE replays anything and no extra columns are needed.

Throughput mode: ``pages_done / elapsed_since_first_PageStarted`` — correct for
both sequential and parallel OCR. Falls back to the historical prior until at
least two pages have completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from smart_pdf2md.web.models import Job, JobEvent
from smart_pdf2md.web.settings import get_settings

# Weight recent pages heavily: VLM latency drifts with page complexity.
EMA_ALPHA = 0.3
HISTORY_JOBS = 5
MIN_SECONDS_PER_PAGE = 1.0
MAX_SECONDS_PER_PAGE = 600.0


@dataclass(frozen=True)
class JobEta:
    pages_total: int
    pages_done: int
    cached_pages: int
    elapsed_s: float
    current_page: Optional[int]
    current_page_elapsed_s: Optional[float]
    seconds_per_page: float
    eta_seconds: Optional[int]
    basis: str

    @property
    def progress_pct(self) -> int:
        """Cached pages count as done; they resolved instantly."""
        total = self.pages_total + self.cached_pages
        if total <= 0:
            return 0
        done = self.pages_done + self.cached_pages
        return max(0, min(100, round(done / total * 100)))


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown"
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def default_seconds_per_page(backend: str) -> float:
    settings = get_settings()
    if backend == "paddleocr":
        return float(settings.web_eta_paddle_seconds_per_page)
    return float(settings.web_eta_default_seconds_per_page)


def _clamp(value: float) -> float:
    return max(MIN_SECONDS_PER_PAGE, min(MAX_SECONDS_PER_PAGE, value))


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def page_durations(events: Sequence[JobEvent]) -> list[float]:
    """Seconds per completed page, paired by page number across start/done."""
    started: dict[int, datetime] = {}
    durations: list[float] = []
    for event in events:
        page = (event.payload or {}).get("page")
        if page is None:
            continue
        when = _as_utc(event.created_at)
        if event.event_type == "PageStarted":
            started[int(page)] = when
        elif event.event_type == "PageDone":
            begin = started.pop(int(page), None)
            if begin is not None:
                durations.append(max(0.0, (when - begin).total_seconds()))
    return durations


def ema(durations: Sequence[float], seed: float, alpha: float = EMA_ALPHA) -> float:
    value = seed
    for duration in durations:
        value = alpha * duration + (1 - alpha) * value
    return _clamp(value)


def seconds_per_page_prior(
    db: Session,
    *,
    user_id: str,
    backend: str,
    model: Optional[str],
) -> tuple[float, str]:
    """Median seconds/page from the user's recent jobs, else a static default."""
    for match_model in (True, False):
        query = select(Job).where(
            Job.owner_id == user_id,
            Job.status == "succeeded",
            Job.backend == backend,
        )
        if match_model and model:
            query = query.where(Job.vlm_model == model)
        jobs = db.scalars(
            query.order_by(Job.created_at.desc()).limit(HISTORY_JOBS)
        ).all()

        samples: list[float] = []
        for job in jobs:
            events = db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job.id)
                .order_by(JobEvent.seq)
            ).all()
            samples.extend(page_durations(events))
        if samples:
            label = f"your last {len(jobs)} job{'s' if len(jobs) != 1 else ''}"
            return _clamp(median(samples)), label
        if not model:
            break

    return default_seconds_per_page(backend), "default estimate"


def job_eta(db: Session, job: Job) -> JobEta:
    events = db.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.seq)
    ).all()

    pages_total = 0
    cached_pages = 0
    pages_done = 0
    current_page: Optional[int] = None
    current_started: Optional[datetime] = None
    first_at: Optional[datetime] = None
    last_at: Optional[datetime] = None
    completed_elapsed: Optional[float] = None
    first_page_started: Optional[datetime] = None
    in_flight: set[int] = set()

    for event in events:
        payload = event.payload or {}
        when = _as_utc(event.created_at)
        first_at = first_at or when
        last_at = when
        if event.event_type == "OcrStarted":
            pages_total = int(payload.get("total") or 0)
        elif event.event_type == "CacheSummary":
            cached_pages = int(payload.get("hits") or 0)
        elif event.event_type == "PageStarted":
            page = int(payload.get("page") or 0) or None
            if page is not None:
                in_flight.add(page)
                current_page = page
                current_started = when
            if first_page_started is None:
                first_page_started = when
        elif event.event_type == "PageDone":
            pages_done += 1
            page = int(payload.get("page") or 0) or None
            if page is not None:
                in_flight.discard(page)
            if not in_flight:
                current_page = None
                current_started = None
            else:
                current_page = next(iter(in_flight))
        elif event.event_type == "Completed":
            completed_elapsed = float(payload.get("elapsed_ms") or 0) / 1000.0

    prior, prior_basis = seconds_per_page_prior(
        db, user_id=job.owner_id, backend=job.backend, model=job.vlm_model
    )

    now = datetime.now(timezone.utc)
    if completed_elapsed is not None:
        elapsed = completed_elapsed
    elif first_at is not None:
        end = last_at if job.status in {"failed", "cancelled"} else now
        elapsed = max(0.0, ((end or now) - first_at).total_seconds())
    else:
        elapsed = 0.0

    current_elapsed = (
        max(0.0, (now - current_started).total_seconds())
        if current_started is not None
        else None
    )

    # Throughput from wall clock since the first PageStarted (parallel-safe).
    seconds_per_page = prior
    basis = prior_basis
    if pages_done >= 2 and first_page_started is not None:
        end = last_at if job.status in {"failed", "cancelled", "succeeded"} else now
        if completed_elapsed is not None and first_at is not None:
            # Prefer Completed elapsed relative to first page start when available.
            ocr_elapsed = max(
                0.001,
                completed_elapsed
                - max(0.0, (first_page_started - first_at).total_seconds()),
            )
        else:
            ocr_elapsed = max(0.001, ((end or now) - first_page_started).total_seconds())
        throughput = pages_done / ocr_elapsed
        if throughput > 0:
            seconds_per_page = _clamp(1.0 / throughput)
            basis = (
                f"throughput ({pages_done} pages / {ocr_elapsed:.0f}s)"
            )
    elif pages_done >= 1:
        durations = page_durations(events)
        if durations:
            seconds_per_page = ema(durations, prior)
            basis = f"{len(durations)} completed page{'s' if len(durations) != 1 else ''}"

    eta_seconds: Optional[int] = None
    if job.status == "running" and pages_total:
        remaining = max(0, pages_total - pages_done)
        if pages_done >= 2 and first_page_started is not None:
            ocr_elapsed = max(0.001, (now - first_page_started).total_seconds())
            throughput = pages_done / ocr_elapsed
            eta_seconds = max(0, int(round(remaining / throughput))) if throughput else None
        else:
            raw = remaining * seconds_per_page - (current_elapsed or 0.0)
            eta_seconds = max(0, int(round(raw)))

    return JobEta(
        pages_total=pages_total,
        pages_done=pages_done,
        cached_pages=cached_pages,
        elapsed_s=elapsed,
        current_page=current_page,
        current_page_elapsed_s=current_elapsed,
        seconds_per_page=seconds_per_page,
        eta_seconds=eta_seconds,
        basis=basis,
    )
