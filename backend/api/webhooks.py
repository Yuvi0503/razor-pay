import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()
_events: dict[str, dict] = {}


def valid_signature(raw: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/razorpay", status_code=200)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> dict[str, str]:
    raw = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not valid_signature(raw, x_razorpay_signature, secret):
        raise HTTPException(400, "invalid Razorpay webhook signature")
    event_id = x_razorpay_event_id
    if not event_id:
        raise HTTPException(400, "missing x-razorpay-event-id")
    if event_id in _events:
        return {"status": "duplicate"}
    _events[event_id] = {"payload": json.loads(raw), "signature_valid": True}
    return {"status": "accepted"}
