"""Send the signed, deterministic failure event used by the demo runbook."""

import argparse
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx


def _load_local_env() -> None:
    """Load only the demo secret when the script is run from the host."""
    if os.environ.get("RAZORPAY_WEBHOOK_SECRET"):
        return
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "RAZORPAY_WEBHOOK_SECRET":
            os.environ["RAZORPAY_WEBHOOK_SECRET"] = value.strip().strip('"').strip("'")
            return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/razorpay")
    parser.add_argument("--event-id", default=None)
    args = parser.parse_args()

    _load_local_env()
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise SystemExit("RAZORPAY_WEBHOOK_SECRET is not set")

    now = int(time.time())
    event_id = args.event_id or f"evt_demo_failure_{now}"
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "customer_id": "cust_demo_failure_01",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_demo_failure_{now}",
                    "amount": 100,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_demo_failure_001",
                    "method": "upi",
                    "error": {"code": "BAD_REQUEST_ERROR", "reason": "payment_failed"},
                }
            },
            "order": {
                "entity": {
                    "id": "order_demo_failure_001",
                    "amount": 100,
                    "currency": "INR",
                    "status": "attempted",
                    "created_at": now,
                }
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    response = httpx.post(
        args.url,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Event-Id": event_id,
            "X-Razorpay-Signature": signature,
        },
        timeout=10,
    )
    print(response.status_code, response.text)


if __name__ == "__main__":
    main()
