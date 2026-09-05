# RecoverGuard

## Safety-first revenue recovery for Razorpay Test Mode

RecoverGuard is a simulator-first operations console for recovering failed payments without unsafe retries. It separates mandate-backed failures from one-off failures, evaluates interventions through deterministic policy rules, records an auditable case timeline, and measures incremental recovery against an organic-recovery control.

The Python distribution/import name remains `revenue-recovery` for compatibility with the existing codebase.

## What the end-to-end demo shows

1. A Razorpay Test Mode webhook is delivered to the API and verified against the exact raw request body.
2. The worker processes the accepted event out of band and persists a normalized recovery case in PostgreSQL.
3. The dashboard reads the persisted case and shows risk, classification, policy output, actions, and the audit timeline.
4. A duplicate provider event is acknowledged without creating a second record.
5. Evaluation metrics are generated and displayed as stored evidence; the frontend does not recompute them.

The real gateway boundary is intentionally narrow. Recovery actions, outcomes, messages, and regulatory rules are simulated or feature-gated unless their official requirements are recorded in `docs/razorpay-verified.md`.

## Prerequisites

- Docker Desktop with Compose
- Git
- Node.js 20 or newer and npm
- Python 3.11 or newer for local evaluation/tests
- Optional: a Razorpay Test Mode account and a public HTTPS tunnel such as zrok for a real webhook delivery

On Windows, run the commands below in PowerShell. On macOS/Linux, use the equivalent shell syntax.

## Quick start: API, worker, database, and dashboard

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
Invoke-RestMethod http://localhost:8000/health
Set-Location frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The API is at `http://localhost:8000`; PostgreSQL is exposed on port `5432`.

Compose starts the `db`, `api`, and out-of-band `worker` services. The API and worker run Alembic migrations before startup. Keep `docker compose logs -f api worker` open while demonstrating webhook delivery.

To stop the stack:

```powershell
docker compose down
```

To remove the local database volume as well, use `docker compose down -v` only when you no longer need the demo data.

## Generate evaluation evidence

The Evaluation tab is populated from a stored report. Generate it before recording the dashboard:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m eval.run --arms all --split test --seed 42
```

Run the automated tests with:

```powershell
.venv\Scripts\python -m pytest -q
```

## Create a reliable demo recovery case

The shortest repeatable path is the signed `payment.failed` fixture in `DEMO.md`. It uses the local `RAZORPAY_WEBHOOK_SECRET`, posts to `/webhooks/razorpay`, and lets the worker create the case asynchronously. After posting it, wait a few seconds and refresh the dashboard. The expected result is one open `B_ONEOFF` case with `₹1.00` at risk.

For a real Test Mode delivery, configure Razorpay Test Mode to send `payment.failed`, `payment.captured`, and `order.paid` to the current tunnel URL ending in `/webhooks/razorpay`. Never expose `.env`, API secrets, webhook secrets, or tunnel tokens in the recording.

## Recording plan

Use [docs/DEMO_VIDEO_PLAN.md](docs/DEMO_VIDEO_PLAN.md) as the shot list and narration script. It is designed for a 5–8 minute end-to-end recording with a clean reset path and explicit simulator/Test Mode disclosure.

## Host-run API database note

For a host-run API, set `DATABASE_URL` in `.env` to:

```bash
postgresql+psycopg://recovery:recovery@localhost:5432/recovery
```

Then run `alembic upgrade head` before starting Uvicorn. Docker Compose is the recommended demo path.

## What is modelled

- Outcomes, organic recovery, outages, and messages are simulated/rendered.
- Webhook raw-body signature verification and payment-link API fields have been verified from official documentation.
- Live mandate charge/retry, regulatory caps, consent obligations, order sweeper fields, and idempotency header behavior remain feature-gated pending verification.
