from datetime import datetime


class NotVerifiedGatewayOperation(RuntimeError):
    pass


class RazorpayAdapter:
    """Test-mode adapter shell. Unverified operations deliberately fail closed."""

    def charge_mandate(self, *_: object, **__: object) -> None:
        raise NotVerifiedGatewayOperation(
            "A1/A2/A3/A7 are not verified; mandate charging is disabled"
        )

    def list_stale_orders(self, *_: object, **__: object) -> list[dict]:
        raise NotVerifiedGatewayOperation("A4 is not verified; order sweeping is disabled")

    def create_payment_link(
        self, case_id: str, amount_paise: int, expires_at: datetime, idempotency_key: str
    ) -> dict:
        raise NotVerifiedGatewayOperation(
            "Wire this verified endpoint only after test credentials are supplied"
        )
