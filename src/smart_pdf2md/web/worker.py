from __future__ import annotations

import logging
import os
from pathlib import Path

from redis import Redis
from rq import Queue, Worker
from sqlalchemy.orm import Session

from smart_pdf2md.converter import convert_full
from smart_pdf2md.events import FanOutListener, LockedListener
from smart_pdf2md.quality import ReportCollector, build_report, write_report
from smart_pdf2md.web.credits import InsufficientCreditsError, settle_job
from smart_pdf2md.web.db import get_session_factory, reset_engine
from smart_pdf2md.web.listener import RedisEventListener
from smart_pdf2md.web.models import Document, Job
from smart_pdf2md.web.settings import get_settings

logger = logging.getLogger(__name__)

_redis_override = None


def set_redis_override(redis) -> None:
    """Test hook: use fakeredis instead of REDIS_URL."""
    global _redis_override
    _redis_override = redis


def _get_redis(redis_conn=None):
    if redis_conn is not None:
        return redis_conn
    if _redis_override is not None:
        return _redis_override
    return Redis.from_url(get_settings().redis_url)


def get_queue(redis_conn=None, *, is_async: bool = True) -> Queue:
    conn = _get_redis(redis_conn)
    return Queue("smartmd", connection=conn, is_async=is_async)


def run_conversion_job(job_id: str) -> None:
    settings = get_settings()
    factory = get_session_factory()
    session: Session = factory()
    redis = _get_redis()
    try:
        job = session.get(Job, job_id)
        if job is None:
            return
        doc = session.get(Document, job.document_id)
        if doc is None:
            job.status = "failed"
            job.error_message = "document missing"
            session.commit()
            return
        job.status = "running"
        session.commit()

        opts = dict(job.options_json or {})
        # Per job, since two jobs on one document can convert different pages.
        out_path = (
            Path(settings.web_data_dir)
            / job.owner_id
            / doc.id
            / "jobs"
            / job.id
            / "output.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        redis_listener = RedisEventListener(
            job_id=job.id,
            session=session,
            redis=redis,
            user_id=job.owner_id,
            credits_held=job.credits_held,
            guard_credits=True,
        )
        report_collector = ReportCollector()
        listener = LockedListener(
            FanOutListener(redis_listener, report_collector)
        )
        concurrency = int(
            opts.get("concurrency")
            or os.environ.get("WEB_OCR_CONCURRENCY")
            or settings.web_ocr_concurrency
            or 4
        )
        try:
            result = convert_full(
                doc.stored_path,
                output=out_path,
                show_progress=False,
                ocr_backend=job.backend,
                vlm_model=job.vlm_model,
                dpi=int(opts.get("dpi", 200)),
                vlm_jpeg_quality=int(opts.get("vlm_jpeg_quality", 85)),
                vlm_max_tokens=int(opts.get("vlm_max_tokens", 8192)),
                force_ocr=bool(opts.get("force_ocr", False)),
                use_cache=bool(opts.get("use_cache", True)),
                pages=opts.get("pages") or None,
                concurrency=max(1, concurrency),
                listener=listener,
            )
            quality_path = out_path.parent / "quality.json"
            write_report(quality_path, build_report(result, report_collector))
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "succeeded"
                job.output_path = str(out_path)
                job.ocr_input_tokens = result.ocr_input_tokens
                job.ocr_output_tokens = result.ocr_output_tokens
                job.ocr_cost_usd = result.ocr_cost_usd
                settle_job(session, job.id)
                session.commit()
        except InsufficientCreditsError as exc:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "insufficient_credits"
                job.error_message = str(exc)
                settle_job(session, job.id)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            cancelled = bool(redis.get(f"job:{job_id}:cancel"))
            if not cancelled:
                logger.exception("job %s failed", job_id)
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "cancelled" if cancelled else "failed"
                job.error_message = "Cancelled" if cancelled else str(exc)
                settle_job(session, job.id)
                session.commit()
        finally:
            listener.close()
    finally:
        session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    reset_engine()
    redis = Redis.from_url(settings.redis_url)
    worker = Worker(["smartmd"], connection=redis)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
