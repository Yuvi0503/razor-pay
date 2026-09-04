# Revenue Recovery Architecture

The application is a simulator-first FastAPI service with PostgreSQL as the durable
source of truth. Docker Compose runs exactly two services: `api` and `db`.

## Current boundaries

- `backend/api` exposes `/health`, dashboard API placeholders, and the Razorpay webhook.
- `backend/db` owns SQLAlchemy metadata, sessions, models, repositories, and migrations.
- `backend/domain` contains enums, state transitions, taxonomy, recoverability, and domain models.
- `backend/policy` contains the pure deterministic policy gate loaded from `config/policy.yaml`.
- `backend/actions` contains the action allowlist and budget metadata.
- `backend/gateway` defines the gateway boundary; unverified Razorpay operations fail closed.
- `sim` and `eval` contain simulation-only outcome logic and evaluation code. Production backend
  code must not import the hidden simulator outcome model.
- `frontend` is the dashboard shell and currently uses sample data.

## Webhook boundary

`POST /webhooks/razorpay` reads the raw request bytes, verifies the HMAC signature, requires the
provider event ID, and inserts the event into `raw_events` with a unique provider-event constraint.
Duplicate deliveries return HTTP 200 with a duplicate status. Event normalization and downstream
orchestration are intentionally separate follow-up work.

## Persistence and safety

Internal IDs are ULIDs stored as text. Money is integer paise. Timestamps are UTC-aware. PostgreSQL
native enums, uniqueness constraints, append-only triggers, and the one-open-case-per-order index
enforce domain invariants in the database. `policy_config_hash` records the exact policy file hash
used for each policy evaluation.

## Operational rules

The Compose API waits for a healthy PostgreSQL service and runs `alembic upgrade head` before startup.
Secrets are supplied through environment variables and redacted from application log records.
The approved contact channel is rendered email only; SMS is disabled. High-value approvals are
manual UI decisions and are not exposed through an executable approval API. Anthropic is optional;
deterministic policy behavior is the default and does not require an API key.
