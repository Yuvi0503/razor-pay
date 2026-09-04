"""Run verified raw-event processing outside the webhook request process."""

from backend.db.engine import get_session
from backend.gateway.razorpay_adapter import RazorpayAdapter
from backend.policy.config_loader import load

from .processor import process_pending


def main() -> None:
    session = next(get_session())
    try:
        processed = process_pending(session, RazorpayAdapter(), load(), execute_actions=True)
        print(f"processed {processed} pending webhook event(s)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
