"""Feature-gated class-C abandonment sweeper."""

import argparse
import os
from datetime import UTC, datetime, timedelta

from backend.db.engine import get_session
from backend.gateway.razorpay_adapter import RazorpayAdapter
from backend.orchestration.orchestrator import Orchestrator
from backend.policy.config_loader import load


def sweep_stale_orders(
    session, gateway, policy, merchant_id: str, before: datetime
) -> int:
    """Open one assisted case for each verified stale non-paid order."""
    orchestrator = Orchestrator(session, gateway, policy)
    count = 0
    for order in gateway.list_stale_orders(before):
        orchestrator.ingest_stale_order(
            merchant_id,
            order,
            provider_event_id=f"order-sweeper:{order.order_id}:{int(before.timestamp())}",
        )
        count += 1
    session.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=2)
    args = parser.parse_args()
    before = datetime.now(UTC) - timedelta(hours=args.hours)
    merchant_id = os.getenv("RAZORPAY_MERCHANT_ID", "merchant")
    session = next(get_session())
    try:
        count = sweep_stale_orders(session, RazorpayAdapter(), load(), merchant_id, before)
        print(f"opened {count} stale order case(s)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
