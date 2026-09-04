# Demo Runbook

## Start

1. Copy `.env.example` to `.env` and fill in local Test Mode credentials and the webhook secret.
2. Start the database and API:

   ```bash
   docker compose up --build
   ```

3. Use the reachable HTTPS tunnel URL ending in `/webhooks/razorpay` in the Razorpay Test Mode
   webhook configuration.

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

## Suggested next scripted flow

Use one failed one-off payment to show classification, payment-link/reminder planning, and the
class restriction against mandate retry. Use a separate mandate case to show scheduling and the
revalidation path that cancels a retry after a manual payment. Keep all live actions in Test Mode.
