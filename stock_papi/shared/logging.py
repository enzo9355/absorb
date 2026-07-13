"""Secret-safe logging formatters used by the application runtime."""

import copy
import logging
import re


def redact_secrets(text: str, extra_secrets: list[str] | None = None) -> str:
    def _redact_key_value(match):
        quote = match.group(2) or ""
        if quote:
            return f"{match.group(1)}{quote}********{quote}"
        return f"{match.group(1)}********"

    redacted = str(text)
    redacted = re.sub(
        r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 ********",
        redacted,
    )
    redacted = re.sub(
        (
            r"(?i)([\"']?\b(?:access_token|refresh_token|id_token|api_token|"
            r"client_secret|api_key|api-key|apikey|password|passwd|secret|"
            r"token|pwd)\b[\"']?\s*(?::=|[:=])\s*)"
            r"(?:([\"'])(.*?)\2|([^\"'\s,;&}]+))"
        ),
        _redact_key_value,
        redacted,
    )
    for secret in extra_secrets or []:
        secret_text = str(secret)
        if len(secret_text) >= 8:
            redacted = re.sub(re.escape(secret_text), "********", redacted)
    return redacted


def safe_exception_text(exc: Exception, extra_secrets: list[str] | None = None) -> str:
    return redact_secrets(str(exc), extra_secrets=extra_secrets)


class RedactingFormatter(logging.Formatter):
    def __init__(
        self,
        fmt=None,
        datefmt=None,
        style="%",
        validate=True,
        *,
        defaults=None,
        secrets_provider=None,
        original_formatter=None,
    ):
        super().__init__(
            fmt=fmt,
            datefmt=datefmt,
            style=style,
            validate=validate,
            defaults=defaults,
        )
        self._secrets_provider = secrets_provider or (lambda: ())
        self._original_formatter = original_formatter

    def format(self, record):
        record_copy = copy.copy(record)
        formatted = (
            self._original_formatter.format(record_copy)
            if self._original_formatter
            else super().format(record_copy)
        )
        if record.levelno < logging.WARNING:
            return formatted
        return redact_secrets(formatted, self._get_extra_secrets())

    def _get_extra_secrets(self):
        try:
            return [secret for secret in (self._secrets_provider() or []) if secret]
        except Exception:
            return []


def _iter_existing_loggers():
    yield logging.getLogger()
    for logger_ref in logging.Logger.manager.loggerDict.values():
        if isinstance(logger_ref, logging.Logger):
            yield logger_ref


def _install_redacting_formatter(handler, secrets_provider=None):
    current = handler.formatter or logging.Formatter()
    if isinstance(current, RedactingFormatter):
        return
    handler.setFormatter(
        RedactingFormatter(
            secrets_provider=secrets_provider,
            original_formatter=current,
        )
    )


def install_redacting_formatters(secrets_provider=None):
    for log in _iter_existing_loggers():
        for handler in log.handlers:
            _install_redacting_formatter(handler, secrets_provider)
