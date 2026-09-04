"""Render compliant local-only message records; this module never sends."""

from pathlib import Path
from typing import Any

import yaml


def render_payment_reminder(amount_paise: int, payment_link: str) -> dict[str, str]:
    values: dict[str, Any] = yaml.safe_load(Path("config/templates.yaml").read_text()) or {}
    template = values.get("payment_reminder", {})
    amount = f"₹{amount_paise / 100:.2f}"
    body = str(template.get("body", "Your payment is pending. Reply STOP to opt out."))
    subject = str(template.get("subject", "Complete your payment"))
    rendered = body.format(amount=amount, payment_link=payment_link)
    if "opt out" not in rendered.lower() and "stop" not in rendered.lower():
        rendered = f"{rendered} Reply STOP to opt out."
    return {"subject": subject, "body": rendered}


__all__ = ["render_payment_reminder"]
