from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from smart_pdf2md.events import (
    Completed,
    ConversionEvent,
    PageDone,
    PageStarted,
)
from smart_pdf2md.web.credits import InsufficientCreditsError, settle_job, topup_one_credit
from smart_pdf2md.web.models import Job, JobEvent


def event_timestamp_ms(created_at: Optional[datetime]) -> int:
    """Epoch ms for an event, so clients can time pages across a page reload."""
    when = created_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return int(when.timestamp() * 1000)


class RedisEventListener:
    """Persist job_events + PUBLISH to Redis; optional credit guard."""

    def __init__(
        self,
        *,
        job_id: str,
        session: Session,
        redis,
        user_id: str,
        credits_held: int,
        guard_credits: bool = True,
    ) -> None:
        self.job_id = job_id
        self.session = session
        self.redis = redis
        self.user_id = user_id
        self.credits_held = credits_held
        self.guard_credits = guard_credits
        self._seq = 0
        self._pages_started = 0
        self._closed = False

    def _channel(self) -> str:
        return f"job:{self.job_id}"

    def _cancel_key(self) -> str:
        return f"job:{self.job_id}:cancel"

    def emit(self, event: ConversionEvent) -> None:
        if self.redis.get(self._cancel_key()):
            raise RuntimeError("job cancelled")

        if self.guard_credits and isinstance(event, PageStarted):
            self._pages_started += 1
            job = self.session.get(Job, self.job_id)
            topup = job.credits_topup if job else 0
            budget = self.credits_held + topup
            if self._pages_started > budget:
                if not topup_one_credit(self.session, self.user_id, self.job_id):
                    if job is not None:
                        job.status = "insufficient_credits"
                        job.error_message = "Không đủ FGold cho trang OCR tiếp theo"
                    self.session.commit()
                    raise InsufficientCreditsError(1, 0)
                self.session.commit()

        if self.guard_credits and isinstance(event, PageDone):
            job = self.session.get(Job, self.job_id)
            if job is not None:
                job.credits_charged += 1
                self.session.flush()

        self._seq += 1
        payload = asdict(event)
        row = JobEvent(
            job_id=self.job_id,
            seq=self._seq,
            event_type=type(event).__name__,
            payload=payload,
        )
        self.session.add(row)
        self.session.commit()
        self.redis.publish(
            self._channel(),
            json.dumps(
                {
                    "seq": self._seq,
                    "type": type(event).__name__,
                    "data": payload,
                    "ts": event_timestamp_ms(row.created_at),
                }
            ),
        )

        if isinstance(event, Completed):
            job = self.session.get(Job, self.job_id)
            if job is not None:
                job.status = "succeeded"
                job.ocr_input_tokens = event.ocr_input_tokens
                job.ocr_output_tokens = event.ocr_output_tokens
                job.ocr_cost_usd = event.ocr_cost_usd
                self.session.flush()
                settle_job(self.session, self.job_id)
                self.session.commit()

        if isinstance(event, PageDone) and self.redis.get(self._cancel_key()):
            raise RuntimeError("job cancelled")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
