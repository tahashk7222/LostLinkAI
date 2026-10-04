"""Credentials must never reach a log line, including the uvicorn access log that records image URLs."""

import logging

from app.core.log_redaction import REDACTED, RedactionFilter, redact
from app.core.security import create_image_token


def _format(name, msg, args=()):
    record = logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, None)
    RedactionFilter().filter(record)
    return logging.Formatter("%(message)s").format(record)


def test_access_log_line_with_image_token_is_redacted():
    token = create_image_token(9)
    line = _format("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("client", "GET", f"/images/9?token={token}", "1.1", 200))
    assert token not in line and "token=" + REDACTED in line
    assert "/images/9" in line  # the path stays, so the log is still useful


def test_jwt_shaped_strings_and_passwords_are_redacted():
    token = create_image_token(1)
    assert token not in redact(f"Authorization: Bearer {token}")
    assert "hunter2" not in redact("login password=hunter2&email=a@b.c")
    assert "s3cr3t-value" not in redact("api_key=s3cr3t-value")


def test_ordinary_text_is_unchanged():
    text = "matching report 6: 1 candidates scored, 0 stored, 0 notifiable"
    assert redact(text) == text
    assert _format("lostlink.ai", text) == text
