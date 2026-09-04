import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.db.engine import get_session
from backend.db.repositories import RawEventRepository

router = APIRouter()


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
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    raw = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not valid_signature(raw, x_razorpay_signature, secret):
        raise HTTPException(400, "invalid Razorpay webhook signature")
    event_id = x_razorpay_event_id
    if not event_id:
        raise HTTPException(400, "missing x-razorpay-event-id")

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "invalid JSON webhook payload") from exc
    if not isinstance(payload, (dict, list)):
        raise HTTPException(400, "webhook payload must be a JSON object or array")

    event_type = payload.get("event") if isinstance(payload, dict) else None
    inserted = RawEventRepository(session).insert_if_new(
        provider_event_id=event_id,
        event_type=event_type if isinstance(event_type, str) else None,
        payload=payload,
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    if not inserted:
        return {"status": "duplicate"}
    return {"status": "accepted"}
