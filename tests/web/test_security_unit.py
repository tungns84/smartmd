"""Cycle 8: pure security helpers."""

from __future__ import annotations

from smart_pdf2md.web.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)


def test_argon2_hash_verifies_and_rejects():
    h = hash_password("correct horse")
    assert verify_password(h, "correct horse")
    assert not verify_password(h, "wrong password")


def test_session_token_is_stored_hashed_not_plaintext():
    token = new_session_token()
    digest = hash_session_token(token)
    assert digest != token
    assert len(digest) == 64
    assert digest == hash_session_token(token)
