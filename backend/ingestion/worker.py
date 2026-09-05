"""Run verified raw-event processing outside the webhook request process."""

import argparse
import time

from backend.db.engine import get_session
from backend.gateway.razorpay_adapter import RazorpayAdapter
from backend.policy.config_loader import load

from .processor import process_pending


def run_once() -> int:
    session = next(get_session())
    try:
        # Scheduling is owned by the API lifecycle.  The worker only persists
        # normalized cases and actions, keeping request processing out-of-band.
        return process_pending(session, RazorpayAdapter(), load(), execute_actions=False)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be positive")
    while True:
        processed = run_once()
        if processed:
            print(f"processed {processed} pending webhook event(s)")
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
