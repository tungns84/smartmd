from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from smart_pdf2md.cache import OcrPageCache
from smart_pdf2md.config import Options
from smart_pdf2md.converter import plan_ocr_pages
from smart_pdf2md.web.credits import InsufficientCreditsError, hold_credits, settle_job
from smart_pdf2md.web.db import get_session_factory
from smart_pdf2md.web.deps import (
    DbSession,
    load_session,
    require_csrf,
    require_owner,
    require_user,
)
from smart_pdf2md.web.eta import JobEta, format_duration, job_eta
from smart_pdf2md.web.htmlutil import (
    as_bool,
    html_error,
    hx_redirect,
    shell_context,
    templates,
    wants_html,
)
from smart_pdf2md.web.job_options import (
    _coerce_int,
    format_page_selection,
    validate_job_options,
)
from smart_pdf2md.web.listener import event_timestamp_ms
from smart_pdf2md.web.models import Document, Job, JobEvent, User
from smart_pdf2md.web.settings import get_settings
from smart_pdf2md.web.worker import get_queue, run_conversion_job

router = APIRouter(tags=["jobs"])

TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "insufficient_credits"}
)

_sse_lock = threading.Lock()
_sse_streams_by_user: dict[str, int] = defaultdict(int)


def _acquire_sse_slot(user_id: str, max_streams: int) -> bool:
    with _sse_lock:
        if _sse_streams_by_user[user_id] >= max_streams:
            return False
        _sse_streams_by_user[user_id] += 1
        return True


def _release_sse_slot(user_id: str) -> None:
    with _sse_lock:
        current = _sse_streams_by_user.get(user_id, 0)
        if current <= 1:
            _sse_streams_by_user.pop(user_id, None)
        else:
            _sse_streams_by_user[user_id] = current - 1


def job_timeout_seconds(ocr_pages: int) -> int:
    """Wall-clock budget RQ gives the worker for one conversion."""
    settings = get_settings()
    return max(
        int(settings.web_job_timeout_seconds),
        max(1, ocr_pages) * int(settings.web_job_timeout_per_page_seconds),
    )


def _cancel_rq_job(redis, rq_job_id: str) -> None:
    """Best effort: drop a still-queued job so no worker picks it up later."""
    try:
        from rq.job import Job as RQJob

        RQJob.fetch(rq_job_id, connection=redis).cancel()
    except Exception:  # noqa: BLE001
        pass


def _get_redis(request: Request):
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        from redis import Redis

        redis = Redis.from_url(get_settings().redis_url)
        request.app.state.redis = redis
    return redis


async def _read_job_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    form = await request.form()
    # Last value wins for duplicate keys (checkbox + hidden use_cache).
    payload: dict[str, Any] = {}
    for key in form.keys():
        values = form.getlist(key)
        payload[key] = values[-1] if values else None
    payload["force_ocr"] = as_bool(payload.get("force_ocr"), False)
    if "use_cache" in payload:
        payload["use_cache"] = as_bool(payload.get("use_cache"), True)
    else:
        payload["use_cache"] = True
    if "dpi" in payload and payload["dpi"] not in (None, ""):
        payload["dpi"] = _coerce_int(payload["dpi"], 200, "dpi")
    return payload


def _job_json(job: Job, eta: Optional[JobEta] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": job.id,
        "status": job.status,
        "error_message": job.error_message,
        "output_path": job.output_path,
        "ocr_input_tokens": job.ocr_input_tokens,
        "ocr_output_tokens": job.ocr_output_tokens,
        "ocr_cost_usd": job.ocr_cost_usd,
        "credits_held": job.credits_held,
        "credits_charged": job.credits_charged,
        "credits_topup": job.credits_topup,
        "settled_at": job.settled_at.isoformat() if job.settled_at else None,
    }
    if eta is not None:
        body.update(
            {
                "pages_total": eta.pages_total,
                "pages_done": eta.pages_done,
                "cached_pages": eta.cached_pages,
                "progress_pct": eta.progress_pct,
                "elapsed_seconds": round(eta.elapsed_s, 1),
                "seconds_per_page": round(eta.seconds_per_page, 1),
                "eta_seconds": eta.eta_seconds,
                "eta_basis": eta.basis,
            }
        )
    return body


@router.post("/jobs", dependencies=[Depends(require_csrf)])
async def create_job(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    payload = await _read_job_payload(request)
    document_id = payload.get("document_id")
    if not document_id:
        raise HTTPException(status_code=422, detail="document_id required")
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(doc.owner_id, user)

    try:
        opts = validate_job_options(payload, page_count=doc.page_count)
    except HTTPException as exc:
        if wants_html(request):
            return html_error(str(exc.detail), exc.status_code)
        raise
    ocr_pages = plan_ocr_pages(
        pdf_type=doc.pdf_type or "scanned",
        page_count=doc.page_count,
        pages_needing_ocr=list(doc.pages_needing_ocr or []),
        page_native_chars=list(doc.page_native_chars or []),
        force_ocr=bool(opts["force_ocr"]),
        selected_pages=opts["pages"],
    )
    cached = 0
    # --force-ocr skips cache reads in convert_full, so do not discount hold.
    if opts["use_cache"] and not opts["force_ocr"]:
        cache_opts = Options(
            ocr_backend=opts["backend"],
            vlm_model=opts["vlm_model"] or "qwen3.6-plus",
            dpi=opts["dpi"],
            vlm_jpeg_quality=opts["vlm_jpeg_quality"],
            use_cache=True,
        )
        try:
            cache = await run_in_threadpool(
                OcrPageCache.for_pdf, doc.stored_path, cache_opts
            )
            cached = len(set(cache.cached_pages()) & set(ocr_pages))
        except Exception:  # noqa: BLE001
            cached = 0
    hold = max(0, len(ocr_pages) - cached)

    job = Job(
        owner_id=user.id,
        document_id=doc.id,
        status="queued",
        backend=opts["backend"],
        vlm_model=opts["vlm_model"],
        options_json=opts,
        credits_held=hold,
    )
    db.add(job)
    db.flush()
    try:
        hold_credits(db, user.id, hold, job.id)
    except InsufficientCreditsError as exc:
        db.rollback()
        if wants_html(request):
            return html_error(
                f"Cần {exc.needed} FGold, hiện có {exc.available}",
                422,
            )
        raise HTTPException(
            status_code=422,
            detail=f"Need {exc.needed} FGold, have {exc.available}",
        ) from exc
    db.commit()

    redis = _get_redis(request)
    is_async = getattr(request.app.state, "rq_is_async", True)
    if is_async:
        queue = get_queue(redis, is_async=True)
        rq_job = queue.enqueue(
            run_conversion_job,
            job.id,
            job_timeout=job_timeout_seconds(len(ocr_pages)),
        )
        job.rq_job_id = rq_job.id
        db.commit()
    else:
        # Sync path for tests (RQ + fakeredis is brittle); still uses same worker fn.
        db.commit()
        run_conversion_job(job.id)
        db.refresh(job)

    if wants_html(request):
        return hx_redirect(request, f"/jobs/{job.id}")

    return {"id": job.id, "status": job.status, "credits_held": hold}


@router.get("/jobs")
async def list_jobs(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    jobs = db.scalars(
        select(Job).where(Job.owner_id == user.id).order_by(Job.created_at.desc())
    ).all()
    if wants_html(request):
        documents = {
            doc.id: doc
            for doc in db.scalars(
                select(Document).where(Document.owner_id == user.id)
            ).all()
        }
        return templates.TemplateResponse(
            request,
            "jobs.html",
            shell_context(
                request,
                db,
                user,
                jobs=jobs,
                documents=documents,
                format_page_selection=format_page_selection,
            ),
        )
    return [_job_json(job) for job in jobs]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(job.owner_id, user)

    eta = job_eta(db, job)

    if wants_html(request):
        progress_pct = 100 if job.status in TERMINAL_STATUSES else eta.progress_pct
        message = {
            "queued": "Đang chờ worker trống…",
            "running": "Đang chuyển…",
            "succeeded": "Xong",
            "failed": job.error_message or "Lỗi",
            "cancelled": "Đã hủy",
            "insufficient_credits": job.error_message or "Hết FGold",
        }.get(job.status, job.status)
        doc = db.get(Document, job.document_id)
        quality = None
        if job.output_path:
            quality_path = Path(job.output_path).parent / "quality.json"
            if quality_path.is_file():
                try:
                    quality = json.loads(quality_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    quality = None
        return templates.TemplateResponse(
            request,
            "job_detail.html",
            shell_context(
                request,
                db,
                user,
                job=job,
                doc=doc,
                eta=eta,
                page_spec=format_page_selection((job.options_json or {}).get("pages")),
                progress_pct=progress_pct,
                message=message,
                timeout_budget=job_timeout_seconds(eta.pages_total),
                format_duration=format_duration,
                quality=quality,
            ),
        )

    return _job_json(job, eta)


@router.get("/jobs/{job_id}/download")
async def download_job_output(
    job_id: str,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    job = db.get(Job, job_id)
    if job is None or not job.output_path:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(job.owner_id, user)
    doc = db.get(Document, job.document_id)
    stem = Path(doc.original_filename).stem if doc else "output"
    return FileResponse(
        job.output_path,
        filename=f"{stem or 'output'}.md",
        media_type="text/markdown",
    )


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_csrf)])
async def cancel_job(
    job_id: str,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(job.owner_id, user)

    if job.status not in TERMINAL_STATUSES:
        redis = _get_redis(request)
        redis.set(f"job:{job_id}:cancel", "1")
        never_started = job.status == "queued"
        job.status = "cancelled"
        if never_started:
            # No worker will run, so nothing else would release the hold.
            settle_job(db, job.id)
        db.commit()
        if never_started and job.rq_job_id:
            _cancel_rq_job(redis, job.rq_job_id)

    if wants_html(request):
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return {"ok": True, "status": job.status}


@router.get("/jobs/{job_id}/events")
async def job_events_sse(
    job_id: str,
    request: Request,
    last_event_id: Optional[int] = None,
):
    """SSE stream with short-lived DB sessions (no pool hold for the stream lifetime)."""
    settings = get_settings()
    factory = get_session_factory()
    # Authz + ownership in a short-lived session that closes before streaming.
    with factory() as db:
        token = request.cookies.get(settings.cookie_name)
        user, _ = load_session(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="not found")
        require_owner(job.owner_id, user)
        user_id = user.id

    max_streams = int(settings.web_sse_max_streams_per_user)
    with _sse_lock:
        if _sse_streams_by_user.get(user_id, 0) >= max_streams:
            raise HTTPException(
                status_code=429,
                detail="Too many concurrent event streams",
            )

    redis = _get_redis(request)
    after = last_event_id or 0
    header_id = request.headers.get("last-event-id")
    if header_id and header_id.isdigit():
        after = max(after, int(header_id))
    max_duration = float(settings.web_sse_max_duration_seconds)
    channel = f"job:{job_id}"

    async def gen():
        nonlocal after
        # Acquire only once the stream body starts, so abandoned responses
        # cannot leak slots when the client never reads.
        if not _acquire_sse_slot(user_id, max_streams):
            return
        started = time.monotonic()
        pubsub = redis.pubsub()
        pubsub.subscribe(channel)
        try:
            with factory() as db:
                rows = db.scalars(
                    select(JobEvent)
                    .where(JobEvent.job_id == job_id, JobEvent.seq > after)
                    .order_by(JobEvent.seq)
                ).all()
                history = [
                    (
                        row.seq,
                        row.event_type,
                        row.payload,
                        event_timestamp_ms(row.created_at),
                    )
                    for row in rows
                ]
            for seq, etype, payload, ts in history:
                after = seq
                data = json.dumps(
                    {"seq": seq, "type": etype, "data": payload, "ts": ts}
                )
                yield f"id: {seq}\nevent: {etype}\ndata: {data}\n\n"
                if etype == "Completed":
                    return

            while True:
                if await request.is_disconnected():
                    break
                if time.monotonic() - started >= max_duration:
                    break
                message = await run_in_threadpool(
                    pubsub.get_message,
                    ignore_subscribe_messages=True,
                    timeout=0.5,
                )
                if message and message.get("type") == "message":
                    raw = message["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload = json.loads(raw)
                    seq = int(payload["seq"])
                    if seq <= after:
                        continue
                    after = seq
                    etype = payload["type"]
                    yield f"id: {seq}\nevent: {etype}\ndata: {json.dumps(payload)}\n\n"
                    if etype == "Completed":
                        break
                else:
                    with factory() as db:
                        status = db.scalar(
                            select(Job.status).where(Job.id == job_id)
                        )
                    if status in TERMINAL_STATUSES:
                        break
                await asyncio.sleep(0.05)
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            finally:
                _release_sse_slot(user_id)

    return StreamingResponse(gen(), media_type="text/event-stream")
