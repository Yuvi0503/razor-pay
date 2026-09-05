# RecoverGuard Demo Runbook

## Start

1. Copy `.env.example` to `.env` and set a local webhook secret. Add Razorpay Test Mode credentials only if you are configuring a real Test Mode delivery.
2. Start the database and API:

   ```bash
   docker compose up --build
   ```

3. Optional for the local fixture: no public tunnel is required. For a real delivery, use the reachable HTTPS tunnel URL ending in `/webhooks/razorpay` in the Razorpay Test Mode
   webhook configuration.

On Windows, use `Copy-Item .env.example .env`; the remaining Compose and npm commands work in PowerShell.

## What the current demo proves

- The health endpoint is available from the API.
- Razorpay webhook signatures are checked against the exact raw request body.
- Duplicate provider event IDs are acknowledged without duplicate persistence.
- Database schema creation is run by Alembic before the API starts.
- Policy behavior is deterministic and does not require Anthropic.
- Customer contact is email-only and rendered locally; no SMS is sent.
- High-value actions require manual dashboard approval.

## Required disclosure

Razorpay Test Mode API interactions are real only where the corresponding operation is verified and
implemented. Messages are rendered into the database and are not sent. Simulator outcomes are
modelled results, not production recovery claims. Regulatory retry-cap and pre-debit-notice rules
remain disabled until their official requirements are verified and recorded.

## Reliable scripted flow

Generate an evaluation report, open the dashboard, and then send a signed failure event from the
repository root. The script is cross-platform and uses the same `RAZORPAY_WEBHOOK_SECRET` as the API.

```bash
python scripts/send_demo_failure.py
```

When running inside the Compose API container instead of a host virtual environment:

```bash
docker compose exec -T api python scripts/send_demo_failure.py
```

Wait 5–10 seconds for the worker, then refresh the dashboard. The expected result is one open
`B_ONEOFF` case with `₹1.00` at risk. To demonstrate duplicate protection, reuse the same provider
event ID:

```bash
python scripts/send_demo_failure.py --event-id evt_demo_duplicate_001
python scripts/send_demo_failure.py --event-id evt_demo_duplicate_001
```

Use a separate mandate-shaped case only if you want to show the classification boundary and its
restricted retry policy. Keep all live actions in Test Mode.
