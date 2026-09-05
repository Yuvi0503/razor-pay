from datetime import UTC

from backend.ingestion.normalizer import normalize


def test_malformed_payment_payload_does_not_create_an_actionable_snapshot() -> None:
    event = normalize(
        "event-malformed",
        {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "payment-malformed",
                        "order_id": "order-malformed",
                        "amount": "99900",
                        "created_at": "2026-01-01T04:00:00Z",
                    }
                }
            },
        },
    )

    assert event.payment is None
    assert event.order is None
    assert event.customer_id == "unidentified:event-malformed"


def test_normalizer_converts_iso_timestamps_to_utc() -> None:
    event = normalize(
        "event-time",
        {
            "event": "payment.failed",
            "customer_id": "customer-time",
            "payload": {
                "order": {
                    "entity": {
                        "id": "order-time",
                        "amount": 99900,
                        "created_at": "2026-01-01T09:30:00+05:30",
                    }
                },
                "payment": {
                    "entity": {
                        "id": "payment-time",
                        "order_id": "order-time",
                        "amount": 99900,
                        "created_at": "2026-01-01T09:30:00+05:30",
                    }
                }
            },
        },
    )

    assert event.payment is not None
    assert event.payment.captured_at is None
    assert event.order is not None
    assert event.order.created_at.tzinfo is UTC
    assert event.order.created_at.hour == 4
