"""Keep bearer credentials out of logs.

Uvicorn's access log records full request paths, and the image route carries a short-lived bearer token in its
query string. This filter rewrites any log record that contains a credential-shaped value before a handler writes
it. It applies to every handler it is installed on, so it also covers application diagnostics.
"""

import logging
import re

REDACTED = "[redacted]"
_PARAM = re.compile(r"(?i)((?:access_)?token|password|api[_-]?key|signature|secret)=[^&\s\"']+")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")


def redact(text: str) -> str:
    text = _PARAM.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return _JWT.sub(REDACTED, text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            # Keep the argument tuple: uvicorn's access formatter unpacks it. Redact only the string values.
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            return True
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_LOGGERS = ("", "uvicorn", "uvicorn.access", "uvicorn.error")


def install_log_redaction() -> None:
    """Attach the filter to every handler of the loggers the app and uvicorn use. Safe to call repeatedly."""
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactionFilter) for f in handler.filters):
                handler.addFilter(RedactionFilter())
