import logging

from backend.logging_filters import REDACTED, SecretRedactionFilter


def test_secret_redaction_filter_masks_configured_values(monkeypatch) -> None:
    webhook_secret = "webhook-secret-value"
    database_url = "postgresql+psycopg://user:password@db/recovery"
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("DATABASE_URL", database_url)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="webhook=%s database=%s",
        args=(webhook_secret, database_url),
        exc_info=None,
    )

    assert SecretRedactionFilter().filter(record)
    assert record.getMessage() == f"webhook={REDACTED} database={REDACTED}"
    assert webhook_secret not in record.getMessage()
    assert database_url not in record.getMessage()
