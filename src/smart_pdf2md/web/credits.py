from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from smart_pdf2md.web.models import CreditTransaction, Job, User


class InsufficientCreditsError(Exception):
    def __init__(self, needed: int, available: int):
        self.needed = needed
        self.available = available
        super().__init__(f"Need {needed} FGold, have {available}")


def grant_signup_credits(session: Session, user: User, amount: int) -> None:
    user.credits = amount
    session.add(
        CreditTransaction(
            user_id=user.id,
            delta=amount,
            reason="signup_grant",
            balance_after=amount,
        )
    )


def hold_credits(session: Session, user_id: str, hold: int, job_id: str) -> int:
    """Atomically subtract hold if balance sufficient. Returns new balance."""
    if hold <= 0:
        user = session.get(User, user_id)
        assert user is not None
        return user.credits
    result = session.execute(
        text(
            "UPDATE users SET credits = credits - :hold "
            "WHERE id = :uid AND credits >= :hold "
            "RETURNING credits"
        ),
        {"hold": hold, "uid": user_id},
    )
    row = result.first()
    if row is None:
        user = session.get(User, user_id)
        available = user.credits if user else 0
        raise InsufficientCreditsError(hold, available)
    new_balance = int(row[0])
    session.add(
        CreditTransaction(
            user_id=user_id,
            delta=-hold,
            reason="job_hold",
            job_id=job_id,
            balance_after=new_balance,
        )
    )
    return new_balance


def topup_one_credit(session: Session, user_id: str, job_id: str) -> bool:
    result = session.execute(
        text(
            "UPDATE users SET credits = credits - 1 "
            "WHERE id = :uid AND credits >= 1 "
            "RETURNING credits"
        ),
        {"uid": user_id},
    )
    row = result.first()
    if row is None:
        return False
    session.add(
        CreditTransaction(
            user_id=user_id,
            delta=-1,
            reason="job_topup",
            job_id=job_id,
            balance_after=int(row[0]),
        )
    )
    job = session.get(Job, job_id)
    if job is not None:
        job.credits_topup += 1
    return True


def settle_job(session: Session, job_id: str) -> None:
    job = session.get(Job, job_id)
    if job is None or job.settled_at is not None:
        return
    refund = job.credits_held + job.credits_topup - job.credits_charged
    if refund > 0:
        result = session.execute(
            text(
                "UPDATE users SET credits = credits + :refund "
                "WHERE id = :uid RETURNING credits"
            ),
            {"refund": refund, "uid": job.owner_id},
        )
        row = result.first()
        balance = int(row[0]) if row else 0
        session.add(
            CreditTransaction(
                user_id=job.owner_id,
                delta=refund,
                reason="job_settle_refund",
                job_id=job.id,
                balance_after=balance,
            )
        )
    job.settled_at = datetime.now(timezone.utc)


def admin_set_credits(
    session: Session,
    user_id: str,
    new_balance: int,
    actor_user_id: str,
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("user not found")
    delta = int(new_balance) - int(user.credits)
    user.credits = int(new_balance)
    session.add(
        CreditTransaction(
            user_id=user_id,
            delta=delta,
            reason="admin_set",
            actor_user_id=actor_user_id,
            balance_after=user.credits,
        )
    )
    return user


def ledger_sum(session: Session, user_id: str) -> int:
    rows = session.scalars(
        select(CreditTransaction).where(CreditTransaction.user_id == user_id)
    ).all()
    return sum(t.delta for t in rows)
