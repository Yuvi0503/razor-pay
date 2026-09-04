"""Logging protections for application and provider credentials."""

import logging
import os

SECRET_ENV_VARS = (
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
)
REDACTED = "[REDACTED]"


def _configured_secrets() -> list[str]:
    return [value for name in SECRET_ENV_VARS if (value := os.getenv(name, ""))]


class SecretRedactionFilter(logging.Filter):
    """Replace configured secret values before a log record is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in _configured_secrets():
            message = message.replace(secret, REDACTED)
        record.msg = message
        record.args = ()
        if record.exc_text:
            for secret in _configured_secrets():
                record.exc_text = record.exc_text.replace(secret, REDACTED)
        return True


def install_secret_redaction_filter() -> None:
    """Install redaction on the root logger and currently configured handlers."""

    redactor = SecretRedactionFilter()
    root = logging.getLogger()
    if not any(isinstance(item, SecretRedactionFilter) for item in root.filters):
        root.addFilter(redactor)
    for handler in root.handlers:
        if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
            handler.addFilter(redactor)

