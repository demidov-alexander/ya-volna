"""Logging setup with secret redaction (spec section 5.4 / 24)."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

REDACTED = "***REDACTED***"

# Patterns that must never reach the log output even if a value is unknown to
# the redaction filter (for example a token embedded in a provider traceback).
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Everything after an Authorization key goes, not just the first word
    # ("Authorization: OAuth <token>" must not leak the token).
    re.compile(r"(?i)\b(authorization)\s*[:=]\s*[^\r\n,;}]+"),
    re.compile(r"(?i)\bOAuth\s+[A-Za-z0-9_\-\.]+"),
    re.compile(
        r"(?i)\b(token|access_token|cookie|session_id|sessionid)\b(\s*[:=]\s*)(\"?)([^\s\"',}]+)"
    ),
)


class RedactingFilter(logging.Filter):
    """Replaces known secret values and secret-looking patterns with a marker."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = {s for s in secrets if s and len(s) >= 8}

    def add_secret(self, secret: str | None) -> None:
        if secret and len(secret) >= 8:
            self._secrets.add(secret)

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(lambda m: _mask(m), text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        scrubbed = self.scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        if record.exc_text:
            record.exc_text = self.scrub(record.exc_text)
        return True


def _mask(match: re.Match[str]) -> str:
    groups = match.groups()
    if len(groups) == 4:
        key, sep, quote, _value = groups
        return f"{key}{sep}{quote}{REDACTED}"
    if len(groups) == 1:
        return f"{groups[0]}: {REDACTED}"
    return REDACTED


_filter = RedactingFilter()


def redaction_filter() -> RedactingFilter:
    return _filter


def setup_logging(level: str = "INFO", *, secrets: Iterable[str] = ()) -> None:
    for secret in secrets:
        _filter.add_secret(secret)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    handler.addFilter(_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # The provider library is chatty and may echo request details.
    logging.getLogger("yandex_music").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
