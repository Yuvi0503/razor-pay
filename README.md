# AI Revenue Recovery

Safety-first revenue-recovery decisioning for Razorpay test mode. The system differentiates mandate-backed retries from one-off failures, evaluates every intervention through deterministic policy rules, and measures incremental recovery against an organic-recovery control.

## Run the simulator evaluation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m eval.run --arms all --split test --seed 42
.venv/bin/python -m pytest -q
```

## Run the API and dashboard

```bash
docker compose up --build
cd frontend && npm install && npm run dev
```

Compose starts both the API/scheduler and the out-of-band webhook worker. The
worker persists normalized cases; the API scheduler reconciles and executes
durable recovery actions.

The app is simulator-first. Live Razorpay operations are blocked until their facts are recorded in `docs/razorpay-verified.md`; never infer an endpoint, error code, or regulatory retry rule.

The API uses PostgreSQL for durable state. Docker Compose creates the database and runs
the Alembic migration before starting the API. For a host-run API, set `DATABASE_URL` in
`.env` (for the Compose database, use
`postgresql+psycopg://recovery:recovery@localhost:5432/recovery`) and run:

```bash
alembic upgrade head
```

## What is modelled

- Outcomes, organic recovery, outages, and messages are simulated/rendered.
- Webhook raw-body signature verification and payment-link API fields have been verified from official documentation.
- Live mandate charge/retry, regulatory caps, consent obligations, order sweeper fields, and idempotency header behavior remain feature-gated pending verification.
