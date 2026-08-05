"""Bootstrap an admin user for internal/trusted deploys.

Usage:
  pdf2md-admin --email admin@example.com --password '...'
  WEB_BOOTSTRAP_ADMIN_EMAIL=... WEB_BOOTSTRAP_ADMIN_PASSWORD=... pdf2md-admin
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select

from smart_pdf2md.web.credits import grant_signup_credits
from smart_pdf2md.web.db import get_session_factory, reset_engine
from smart_pdf2md.web.models import User
from smart_pdf2md.web.security import hash_password
from smart_pdf2md.web.settings import get_settings


def seed_admin(email: str, password: str) -> tuple[User, bool]:
    """Create or promote an admin. Returns (user, created)."""
    email_n = email.strip().lower()
    if not email_n or len(password) < 8:
        raise SystemExit("email required and password must be at least 8 characters")

    settings = get_settings()
    factory = get_session_factory()
    with factory() as session:
        user = session.scalar(select(User).where(User.email == email_n))
        if user is None:
            user = User(
                email=email_n,
                password_hash=hash_password(password),
                role="admin",
                credits=0,
            )
            session.add(user)
            session.flush()
            grant_signup_credits(session, user, settings.web_default_credits)
            session.commit()
            session.refresh(user)
            return user, True

        user.role = "admin"
        user.password_hash = hash_password(password)
        session.commit()
        session.refresh(user)
        return user, False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed or promote a smart-pdf2md admin user")
    parser.add_argument("--email", default=os.environ.get("WEB_BOOTSTRAP_ADMIN_EMAIL", ""))
    parser.add_argument(
        "--password",
        default=os.environ.get("WEB_BOOTSTRAP_ADMIN_PASSWORD", ""),
    )
    args = parser.parse_args(argv)
    if not args.email or not args.password:
        parser.error(
            "provide --email/--password or WEB_BOOTSTRAP_ADMIN_EMAIL / "
            "WEB_BOOTSTRAP_ADMIN_PASSWORD"
        )

    get_settings.cache_clear()
    reset_engine()
    user, created = seed_admin(args.email, args.password)
    action = "created" if created else "updated"
    print(f"admin {action}: {user.email} (id={user.id}, credits={user.credits})")


if __name__ == "__main__":
    main(sys.argv[1:])
