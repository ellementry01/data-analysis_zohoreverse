"""Logs without secrets or customer personal data (Phase 8).

Every handler of the root and uvicorn loggers gets a formatter that scrubs the finished line, tracebacks included:
API keys and tokens, passwords in connection URLs and `password=` pairs, SQL parameter values in database errors,
e-mail addresses (kept recognisable for audit: first letter and domain), Indian mobile numbers, and the query string of
every logged URL (search boxes and filters can carry customer names).
"""
from __future__ import annotations

import logging
import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-[redacted]"),
    (re.compile(r"\b(Bearer|Token)\s+[A-Za-z0-9._\-]{16,}", re.I), r"\1 [redacted]"),
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://[^:/@\s]+):[^@\s]+@", re.I), r"\1:[redacted]@"),
    (re.compile(r"\b(password|passwd|pwd|secret|api[_-]?key|token)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)", re.I),
     r"\1\2[redacted]"),
    # SQLAlchemy errors end with "[parameters: {...}]": the values can be customer data
    (re.compile(r"\[parameters: .*?\](?=\s*(?:\n|\(Background|$))", re.S), "[parameters: redacted]"),
    (re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]{2,}|local)\b"), r"\1***@\2"),
    (re.compile(r"(?<![\d.])(?:\+?91[\s\-]?)?[6-9]\d{9}(?![\d.])"), "[phone]"),
]
# a logged URL or request line: keep the path, drop the query string
_QUERY = re.compile(r"((?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /[^\s?\"]*)\?[^\s\"]*")


def scrub(text: str) -> str:
    if not text:
        return text
    text = _QUERY.sub(r"\1?[query]", text)
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


class ScrubbingFormatter(logging.Formatter):
    def __init__(self, inner: logging.Formatter | None = None):
        super().__init__()
        self.inner = inner or logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return scrub(self.inner.format(record))


def install(level: int = logging.INFO) -> None:
    """Set up logging for the app or the worker and wrap every handler's formatter (idempotent)."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            if not isinstance(h.formatter, ScrubbingFormatter):
                h.setFormatter(ScrubbingFormatter(h.formatter))
