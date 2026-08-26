import hashlib
import hmac

from backend.api.webhooks import valid_signature


def test_raw_webhook_signature_rejects_tampered_payload() -> None:
    secret, raw = "test-secret", b'{"event":"payment.failed", "x": 1}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert valid_signature(raw, signature, secret)
    assert not valid_signature(raw + b" ", signature, secret)
