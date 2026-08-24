from __future__ import annotations

import logging

from yavolna.logging import REDACTED, RedactingFilter, setup_logging


def record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, args, None)


def test_known_secret_is_replaced():
    log_filter = RedactingFilter({"y0_super-secret-token"})
    entry = record("using token y0_super-secret-token for request")
    log_filter.filter(entry)
    assert "y0_super-secret-token" not in entry.getMessage()
    assert REDACTED in entry.getMessage()


def test_secret_in_formatted_arguments_is_replaced():
    log_filter = RedactingFilter({"y0_super-secret-token"})
    entry = record("token=%s", "y0_super-secret-token")
    log_filter.filter(entry)
    assert "y0_super-secret-token" not in entry.getMessage()


def test_authorization_header_is_replaced_even_if_unknown():
    log_filter = RedactingFilter()
    entry = record("headers: Authorization: OAuth abcdef123456")
    log_filter.filter(entry)
    assert "abcdef123456" not in entry.getMessage()


def test_token_keyword_patterns_are_replaced():
    log_filter = RedactingFilter()
    for message in (
        'access_token: "abcdef1234567890"',
        "cookie=Session_id=abcdef1234567890",
        "token=abcdef1234567890",
    ):
        entry = record(message)
        log_filter.filter(entry)
        assert "abcdef1234567890" not in entry.getMessage(), message


def test_short_values_are_not_treated_as_secrets():
    log_filter = RedactingFilter({"abc"})
    entry = record("harmless abc text")
    log_filter.filter(entry)
    assert entry.getMessage() == "harmless abc text"


def test_added_secrets_apply_to_later_records():
    log_filter = RedactingFilter()
    log_filter.add_secret("y0_added-secret-value")
    entry = record("value y0_added-secret-value")
    log_filter.filter(entry)
    assert REDACTED in entry.getMessage()


def test_exception_text_is_scrubbed():
    log_filter = RedactingFilter({"y0_super-secret-token"})
    entry = record("failed")
    entry.exc_text = "Traceback ... OAuth y0_super-secret-token ..."
    log_filter.filter(entry)
    assert "y0_super-secret-token" not in entry.exc_text


def test_setup_logging_installs_the_filter_and_quiets_the_provider(capsys):
    setup_logging("INFO", secrets={"y0_installed-secret"})
    logging.getLogger("test.redaction").info("token is y0_installed-secret")
    captured = capsys.readouterr()
    assert "y0_installed-secret" not in captured.err
    assert logging.getLogger("yandex_music").level == logging.WARNING
