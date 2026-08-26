# AI Revenue Recovery

Safety-first revenue-recovery decisioning for Razorpay test mode. The system differentiates mandate-backed retries from one-off failures, evaluates every intervention through deterministic policy rules, and measures incremental recovery against an organic-recovery control.

## Run the simulator evaluation

```bash
python -m pip install -e '.[dev]'
python -m eval.run --arms all --split test --seed 42
pytest
```

## Run the API and dashboard

```bash
docker compose up --build
cd frontend && npm install && npm run dev
```

The app is simulator-first. Live Razorpay operations are blocked until their facts are recorded in `docs/razorpay-verified.md`; never infer an endpoint, error code, or regulatory retry rule.

## What is modelled

- Outcomes, organic recovery, outages, and messages are simulated/rendered.
- Webhook raw-body signature verification and payment-link API fields have been verified from official documentation.
- Live mandate charge/retry, regulatory caps, consent obligations, order sweeper fields, and idempotency header behavior remain feature-gated pending verification.
