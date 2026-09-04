# Revenue Recovery — Execution Guide

This document explains what has been implemented so far, how the system works, and how to
describe it confidently in an interview. It is intentionally written as an execution and
reasoning guide, not just as a list of files.

## 1. What the system does

Revenue Recovery is a simulator-first payment-recovery service. It receives payment failure
events, turns them into recovery cases, classifies the failure, chooses a deterministic eligible
action, passes that action through a safety policy, schedules it, executes it through a gateway
boundary, verifies the result, and records the full audit trail.

The central design principle is:

> The system may propose an action automatically, but it may execute only after a fresh policy
> decision and a durable action record.

The active product mode is deterministic-only. The optional Anthropic advisor code remains in the
repository as an inactive, isolated extension, but no API key is required and no LLM call is part
of the active product flow. Real Razorpay operations that depend on unresolved legal/provider
answers fail closed instead of being guessed.

## 2. High-level execution flow

```text
Razorpay webhook
      |
      v
Read exact raw bytes -> verify HMAC -> deduplicate event ID -> store raw_events
      |
      v
Background processor -> normalize provider payload
      |
      v
Persist merchant/customer/order/subscription/payment attempt
      |
      v
Open or reuse one recovery case
      |
      v
OPEN -> CLASSIFIED -> DECIDED -> policy evaluation -> SCHEDULED
                                                   |
                                                   v
                         revalidate -> EXECUTING -> VERIFYING
                                                   |
                              RECOVERED / EXHAUSTED / STOPPED / EXPIRED
```

The simulator follows the same flow. The only difference is that its gateway returns a
deterministic modelled outcome instead of calling Razorpay.

### The complete flow, step by step

1. A Razorpay webhook reaches `POST /webhooks/razorpay`.
2. The API reads the exact raw request bytes and verifies the HMAC-SHA256 signature using the
   configured webhook secret.
3. The API requires `x-razorpay-event-id` and inserts the event into `raw_events`. The unique
   provider-event constraint makes repeated delivery safe.
4. The API returns HTTP 200 after durable insertion. It does not normalize the event, make a
   decision, send a message, or charge a customer inside the request.
5. `backend.ingestion.worker` loads unprocessed raw events and normalizes verified provider data
   into merchant, customer, order, subscription, and payment-attempt records.
6. The orchestrator opens one recovery case per order, or reuses the existing open case when the
   event is a duplicate or a related update.
7. The domain layer classifies the case, calculates recoverability, and generates only actions
   allowed for that case class. Unknown provider errors remain `UNKNOWN`.
8. The deterministic policy engine evaluates consent, budgets, cooldowns, outage status, payment
   state, case age, approval requirements, communication hours, and the global kill switch.
9. The result, fired rules, human-readable explanation, policy hash, and proposed action are
   persisted before scheduling.
10. The scheduler stores a job using the durable action ID. Before execution, the orchestrator
   revalidates freshness, payment state, consent, budgets, outage state, and the policy gate.
11. The simulator executes through `SimulatedGateway`, which uses deterministic modelled outcomes.
   The Razorpay adapter executes only verified Test Mode operations, currently the payment-link
   path.
12. The system verifies the result from payment evidence or a provider read-back. A successful
   payment-link creation alone does not recover a case.
13. The case is moved to `RECOVERED`, `EXHAUSTED`, `STOPPED`, or `EXPIRED`, and the full timeline
   records the outcome, audit event, and any compensation requirement.
14. The dashboard reads the persisted cases, timelines, approvals, policy data, and evaluation
   report through the API. It does not run business rules or recompute evaluation metrics.

## 3. Repository structure and ownership

| Area | Responsibility |
|---|---|
| `backend/api` | FastAPI application and webhook boundary |
| `backend/db` | SQLAlchemy models, sessions, repositories, migrations |
| `backend/domain` | Enums, snapshots, state transitions, taxonomy, recoverability |
| `backend/policy` | Pure deterministic policy gate and eligible-action rules |
| `backend/actions` | Action metadata and local message rendering |
| `backend/ingestion` | Provider payload normalization and pending-event processing |
| `backend/orchestration` | Case lifecycle, policy persistence, scheduling, execution, verification |
| `backend/gateway` | Provider-neutral gateway protocol and fail-closed Razorpay adapter |
| `backend/scheduler.py` | APScheduler/PostgreSQL job-store integration |
| `sim` | Stateful simulated gateway and hidden deterministic outcome model |
| `eval` | Scenario execution, evaluation arms, reports, and acceptance gate |
| `config` | Policy, message, taxonomy, and simulator configuration |

The architecture rule is important: production `backend/` code cannot import the hidden simulator
outcome model. The backend knows only the `GatewayAdapter` contract. This prevents accidental
leakage of test truth into production decision logic.

## 4. Task 1 — Domain contracts and persistence repositories

The first implementation task was to create stable boundaries between external provider data,
domain decisions, and database records.

`backend/domain/contracts.py` defines provider-neutral snapshots:

- `PaymentSnapshot`
- `OrderSnapshot`
- `SubscriptionSnapshot`
- `NormalizedEvent`
- `CaseSnapshot`

The advantage of snapshots is that policy code does not depend on Razorpay JSON shape. A Razorpay
adapter, simulator, or future provider can translate its own response into the same contract.

`backend/db/repositories/recovery.py` contains transaction-aware repository methods for creating
and finding merchants, customers, consent records, orders, subscriptions, payment attempts,
cases, decisions, policy evaluations, actions, messages, and audit events.

Repositories do not commit implicitly. The caller owns the transaction boundary. This matters
because a webhook should be acknowledged only after its raw event has been durably inserted, and
because an action record must exist before any outbound operation is attempted.

## 5. Task 2 — Database layer and migration safety

The database contains the durable source of truth for the recovery lifecycle.

The implemented tables are:

- `merchants`
- `customers`
- `customer_consent`
- `orders`
- `subscriptions`
- `payment_attempts`
- `recovery_cases`
- `recovery_decisions`
- `policy_evaluations`
- `recovery_actions`
- `human_approvals`
- `outbound_messages`
- `audit_events`
- `raw_events`

Important invariants:

- Money is stored as integer paise, never floating-point currency.
- Internal identifiers are ULIDs stored as text.
- Provider event IDs are unique.
- Provider payment IDs are unique when present.
- Only one unresolved recovery case can exist for an order.
- Payment attempts and audit events are append-only in PostgreSQL.
- `policy_config_hash` records the exact policy configuration used for each evaluation.
- `issuer_or_bank` is optional and allows outage detection at `(method, issuer/bank)` granularity.

`migrations/versions/0001_initial_schema.py` creates the initial schema. The follow-up
`0002_payment_rail.py` adds the optional rail dimension and is written defensively so it does not
fail when the initial migration has already created the latest model column.

## 6. Task 3 — Secure webhook ingestion

The endpoint is:

```text
POST /webhooks/razorpay
```

The webhook implementation in `backend/api/webhooks.py` performs these operations in order:

1. Reads the exact request body bytes.
2. Computes HMAC-SHA256 using `RAZORPAY_WEBHOOK_SECRET`.
3. Compares the expected signature using constant-time comparison.
4. Requires `x-razorpay-event-id`.
5. Parses JSON only after signature verification.
6. Inserts the event using a unique provider-event ID.
7. Returns HTTP 200 for both first delivery and duplicate delivery.

Why raw bytes matter: parsing and re-serializing JSON can change whitespace, key order, or escape
representation. A signature must be checked against the exact bytes Razorpay signed, not a
reconstructed JSON document.

Why duplicates return 200: providers retry events when acknowledgement is delayed or lost. A
duplicate is not a server failure; it is an already-known delivery. Returning an error would cause
unnecessary retries.

Downstream normalization is intentionally outside the request path. `backend/ingestion/processor.py`
processes unprocessed raw events after acknowledgement. This keeps provider retries fast and
prevents a slow policy or gateway call from blocking webhook delivery.

## 7. Task 4 — Normalization and classification

`backend/ingestion/normalizer.py` translates common provider payload shapes into a
`NormalizedEvent`. It extracts payment, order, and subscription entities, maps timestamps to UTC,
and distinguishes failed from captured payment events.

The normalizer does not trust arbitrary provider error names as recovery truth. It uses
`backend/domain/failure_taxonomy.py` and `config/taxonomy.yaml`. Unknown or unverified error codes
fall back to `FailureCategory.UNKNOWN`.

This is safer than trying to infer a recovery strategy from a new provider error string. An
unknown error can still be escalated or handled as assisted recovery, but it must not silently
become an automated mandate retry.

Class assignment is deterministic:

- A failed subscription payment becomes `A_MANDATE`.
- A failed one-off payment becomes `B_ONEOFF`.
- A stale unpaid order from a sweeper becomes `C_ABANDONED`.

The orchestrator also deduplicates at the case level, so replaying the same logical event does not
create a second open case.

## 8. Task 5 — Domain states and legal transitions

The canonical case states are:

```text
OPEN
CLASSIFIED
DECIDED
AWAITING_APPROVAL
SCHEDULED
EXECUTING
VERIFYING
RECOVERED
EXHAUSTED
STOPPED
EXPIRED
```

All transitions are defined once in `backend/domain/state_machine.py`. The `transition()` function
raises `IllegalTransition` for anything not in that map.

Examples:

- `OPEN -> CLASSIFIED` is legal.
- `DECIDED -> SCHEDULED` is legal.
- `VERIFYING -> RECOVERED` is legal.
- `RECOVERED -> EXECUTING` is illegal.
- Any terminal state cannot transition further.

Why centralize the map: scattered `if` statements eventually disagree. A single transition map
is easy to audit, test exhaustively, and use as a safety invariant in both the API and simulator.

## 9. Task 6 — Recoverability and eligible actions

`backend/domain/recoverability.py` applies deterministic classification:

- Temporary gateway error, temporary bank error, and insufficient funds on a mandate are
  automated candidates.
- Cancelled or invalid mandates are not recoverable automatically.
- Other cases are assisted recovery candidates.

`backend/policy/rules.py` generates eligible actions before the final policy gate. This separation
is important:

```text
Eligibility asks: “What could be considered for this case?”
Policy asks:      “What is safe and allowed right now?”
```

Examples:

- A mandate case may consider mandate retry, rescheduling, or human escalation.
- A one-off case may consider a payment link, reminder, alternate method, wait, or stop.
- A one-off case can never receive `RETRY_MANDATE_CHARGE` because the action registry allowlist
  excludes `B_ONEOFF`.

The action registry also declares whether an action is reversible and whether it consumes contact
or charge budget.

## 10. Task 7 — Pure deterministic policy engine

`backend/policy/engine.py` exposes a pure function:

```python
evaluate(case, decision, world, policy) -> PolicyVerdict
```

It does not perform database writes, network requests, or gateway calls. That makes it predictable,
unit-testable, and safe to rerun immediately before execution.

Implemented policy checks include:

- P01: action is allowed for the case class.
- P02: case is active.
- P03: customer has not opted out.
- P04: per-case and rolling seven-day contact budgets.
- P05: charge-attempt budget.
- P06: minimum action gap/cooldown.
- P07: communication window in IST.
- P08: high-value automatic ceiling.
- P09: rail outage deferral.
- P10: payment is still actionable.
- P11: approved contact channel and irreversible-action safety.
- P12: global kill switch.
- P13: maximum case age.
- P14/P15: disabled-safe placeholders for unverified regulatory retry-cap and pre-debit rules.

The approved channel is email. SMS is not enabled and requires explicit SMS opt-in in the policy
world state. Every rendered contact message must contain opt-out language.

### Rolling contact budget

The repository counts `outbound_messages` for the same customer during the previous seven days.
That count is combined with the per-case counter and compared with policy limits. This prevents a
customer from receiving unlimited reminders across multiple recovery cases.

### Rail outage signal

The SQL-derived signal looks at recent payment attempts for a payment method and optional issuer or
bank. It requires:

```text
recent attempts >= configured minimum
AND recent failure rate >= trailing baseline failure rate * multiplier
```

When the signal is true, a charge-consuming mandate action is downgraded to waiting. The policy
does not call an external outage API.

### Why P14/P15 are disabled

The official answers for retry caps and pre-debit notification requirements have not been verified
and recorded. Inventing those values would create a compliance risk. Therefore the policy keeps
those controls disabled and writes explicit `NOT_VERIFIED_A2_RETRY_CAP_DISABLED` and
`NOT_VERIFIED_A3_PRE_DEBIT_DISABLED` audit entries.

## 11. Task 8 — Case orchestrator and audit trail

`backend/orchestration/orchestrator.py` coordinates the lifecycle.

### Ingestion

`Orchestrator.ingest()`:

1. Ensures merchant and customer records exist.
2. Upserts provider order and subscription identity.
3. Persists the payment attempt.
4. Marks captured payments as paid.
5. Opens or reuses the recovery case for a failed payment.
6. Writes case-opened or case-deduplicated audit events.

`ingest_stale_order()` performs the corresponding class-C flow for unpaid stale orders without
pretending that an actual payment failure occurred.

### Decision and policy

`Orchestrator.process()`:

1. Moves the case through classification and decision states.
2. Persists the proposed decision and input snapshot.
3. Builds a fresh world state with consent, budgets, payment status, and outage signal.
4. Evaluates the deterministic policy.
5. Persists the verdict, fired rules, and policy hash.
6. Creates a human approval record for high-value cases.
7. Creates the durable action record before execution.
8. Schedules the action by its ID.

Every important event is written to `audit_events`, which makes the case timeline explainable to an
operator and defensible in an incident review.

## 12. Task 9 — Scheduling and action execution

`backend/scheduler.py` creates an APScheduler instance using `SQLAlchemyJobStore`. Jobs are:

- Stored in PostgreSQL.
- Keyed by `recovery-action:<action_id>`.
- Scheduled in UTC.
- Configured with one active instance and coalescing.
- Given a 15-minute misfire grace period.

The action id—not an in-memory case object—is passed to the job. This is important for process
restarts: the worker can reload the action and case from the database.

The idempotency key is SHA-256 of:

```text
case_id:action_type:charge_attempts_used:scheduled_for_iso8601
```

Before executing, `execute_action()` checks:

- The case is still scheduled.
- The action is due.
- The case has not expired.
- Fresh payment state is still unpaid/actionable.
- Consent and budgets still pass.
- The rail is not degraded for a charge action.
- The policy gate still allows the exact action.

If a customer paid between scheduling and execution, the action is marked `SKIPPED` and no gateway
operation occurs. This is the most important race-condition path in the demo.

## 13. Task 10 — Execution, verification, and compensation

The executor moves the case through:

```text
SCHEDULED -> EXECUTING -> VERIFYING
```

It does not treat an HTTP success response as proof of payment. It performs gateway read-back and
requires a paid state before marking the case recovered.

On verified recovery it:

- Persists a recovery payment attempt.
- Marks the order paid.
- Stores recovered amount and recovered attempt ID.
- Moves the case to `RECOVERED`.
- Writes a `RECOVERY_VERIFIED` audit event.

On failure it increments the relevant charge/contact budget and moves the case to `EXHAUSTED`.

Additional safety paths include:

- Payment-link expiration compensation.
- Duplicate captured-payment detection and refund-review audit event.
- Local-only message records; no email or SMS is sent.
- High-value approval queue with explicit approval state.

The simulated gateway updates its own order state, allowing the production-shaped verification path
to be tested without importing simulator truth into backend code.

## 14. Stateful simulator and evaluation

`sim/gateway.py` implements provider-shaped reads and calls:

- Get payment.
- Get order.
- Get subscription.
- Charge a mandate.
- Create a payment link.
- List stale orders.
- Execute a recovery action.

It tracks provider state, links, orders, subscriptions, payments, and idempotency results.

Scenario generation in `sim/scenarios.py` is seeded and deterministic. Scenarios now include:

- A mandate, B one-off, and C abandoned classes.
- Failure categories.
- Amount in paise.
- Payment method and issuer/bank.
- Payment age.
- Support notes.
- Organic payer flag.
- Organic and recovery probabilities.

The hidden outcome model remains in `sim/outcome_model.py`. It is available only to simulator and
evaluation code. This allows an unbiased experiment: the policy sees case facts, not the hidden
answer to which action will win.

The evaluation arms use the same persisted pipeline:

- Control uses a wait/no-treatment candidate.
- Naive uses the naive contact/retry candidate and configured +1h/+24h/+72h schedule constants.
- Rules uses deterministic eligible-action and policy logic.
- Rules+LLM is retained only as a deterministic fallback/evaluation compatibility arm; it is not
  part of the active deterministic-only product mode.
- Oracle is evaluation-only and uses hidden truth to provide an upper-bound comparison.

## 15. Current acceptance evidence

The current working tree has been verified with the project virtual environment:

```text
python -m pytest -q
74 passed, 1 skipped

ruff check backend sim eval tests
All checks passed

tests/unit/test_evaluation.py
4 passed

npm run build
Frontend production build passed

Budget and communication-window safety tests
Per-case, per-customer, charge-budget, IST boundary, and email-only channel checks passed

Integer-paise money-boundary tests
Domain snapshots, recovery cases, payment-link payloads, and negative/float rejection checks passed

Duplicate delivery, compensation, and scheduler restart tests
Duplicate webhooks create one case, duplicate captures create a compensation audit event, and
scheduled action jobs survive scheduler restart

Taxonomy validation tests
Every configured taxonomy value is validated, and unmapped or empty provider codes fall back to
`UNKNOWN`; the taxonomy remains empty until exact Razorpay codes are officially verified

alembic upgrade head
Clean SQLite migration tests passed

python -m eval.acceptance --count 500 --seed 42
naive: 500 terminal cases, 0 policy violations
rules: 500 terminal cases, 0 policy violations

python -m eval.run --arms all --split test --seed 42 --count 1000
Five evaluation arms completed and persisted category, safety, and deterministic-only LLM status metrics.
```

The one skipped test is the Docker Compose PostgreSQL migration test because Docker is unavailable
in the current environment. It should be run on a machine with Docker before a production/demo
freeze. Strict mypy is not yet clean and remains a hardening task before release freeze.

## 16. How to explain the system in an interview

### A concise two-minute explanation

“I built a simulator-first revenue recovery service around a durable case state machine. Razorpay
webhooks are verified against the exact raw body using HMAC-SHA256, deduplicated by provider event
ID, and stored before asynchronous processing. A normalizer converts provider payloads into
provider-neutral snapshots. The orchestrator classifies a failed payment into mandate, one-off, or
abandoned recovery, generates eligible actions, and sends the candidate through a pure deterministic
policy gate. The gate checks class restrictions, consent, budgets, IST communication windows,
high-value approval, payment freshness, and bank-rail outage signals. Every policy evaluation stores
the configuration hash and fired rules. Actions are inserted with a durable SHA-256 idempotency key
before execution and scheduled through a PostgreSQL-backed APScheduler. Immediately before
execution, the system revalidates the case; after execution it verifies provider state by read-back
rather than trusting an HTTP 200. The simulator implements the same gateway contract, while its
hidden outcome model is isolated from backend code. The 500-case acceptance gate produced terminal
cases for both naive and rules arms with zero policy violations.”

### Difficult question: How do you handle at-least-once webhooks?

“I assume delivery is at least once. The raw provider event ID has a database uniqueness constraint,
and insertion uses conflict-safe deduplication. The endpoint returns 200 for a known duplicate. Case
opening also checks for an existing unresolved case, so both event-level and business-level
duplicates are controlled.”

### Difficult question: What happens if the process crashes after charging?

“The action has a durable idempotency key and an action row exists before execution. On restart the
worker reloads that action by ID. The gateway call must use the same idempotency key, and verification
reads provider state. If a duplicate capture is detected, the system records a compensation/refund
review incident rather than silently claiming success.”

### Difficult question: Why is the policy function pure?

“A policy decision must be reproducible. Keeping evaluation side-effect free lets us unit-test every
rule, persist the exact input snapshot and policy hash separately, and rerun the same gate during
pre-execution revalidation. Database writes and gateway calls belong to orchestration, not policy.”

### Difficult question: How do you prevent a one-off payment from using a mandate retry?

“The action registry declares class allowlists. `RETRY_MANDATE_CHARGE` allows only `A_MANDATE`. The
policy gate checks that allowlist as P01 before any later rule can allow the action. There is also an
explicit test for a B one-off mandate retry being denied.”

### Difficult question: How do you avoid sending too many messages?

“Contact actions consume both a per-case budget and a customer rolling seven-day budget. The count
comes from persisted outbound message records. Consent, approved channel, IST communication window,
and opt-out language are checked before a message record is created. Actual email/SMS delivery is
not implemented; messages are rendered locally and labelled as not sent.”

### Difficult question: How is a bank outage detected?

“I do not call an external outage API. I derive a signal from payment attempts. For a method and
optional issuer/bank, I require a minimum number of recent attempts and compare the recent failure
rate with a trailing baseline multiplied by a configured factor. A degraded rail defers charge-
consuming mandate actions.”

### Difficult question: Why not enable retry caps and pre-debit notices now?

“Those values are compliance-sensitive and provider/legal answers are still unverified. The safe
behavior is fail closed: keep P14/P15 disabled, write a NotVerified audit event, and do not invent a
retry limit or notice lead time. They can be enabled only after the verified source and checked date
are recorded.”

### Difficult question: Why use a simulator instead of calling Razorpay in tests?

“A deterministic simulator gives repeatable tests and lets us test failure paths, outages, duplicate
events, paid-before-execution races, and exhaustion cheaply. The backend depends only on a gateway
protocol, so the simulator tests orchestration behavior without contaminating production logic with
hidden outcome truth.”

### Difficult question: What is the difference between eligibility and policy?

“Eligibility generates possible actions from domain facts. Policy is the final safety gate. For
example, a one-off case may be eligible for a payment link, but a kill switch, opt-out, budget limit,
expired case, paid order, outage, or high-value approval requirement can still deny or downgrade it.”

### Difficult question: How do you handle a customer paying just before a scheduled retry?

“The scheduler does not blindly execute the old decision. It reloads the latest case and payment
state, reruns policy, and skips the action if the order is paid. This prevents a duplicate charge and
records the skipped reason in the action and audit timeline.”

### Difficult question: What is still not production-ready?

“The real Razorpay adapter intentionally fails closed for operations whose official A1–A7/A4
behavior is not verified. The class-C real order sweeper is also gated by A4. The current dashboard
is a shell, messages are not sent, and simulator outcomes are not production recovery claims. Docker
PostgreSQL verification still needs to run where Docker is available.”

## 17. Phase 3 — Evaluation harness execution

Phase 3 is the evaluation harness described in §11 of the build specification. Its purpose is to
measure realized outcomes without circularly using the rules as their own ground truth.

### Separation of responsibilities

The harness keeps three artifacts separate:

- The scenario generator owns observable case features and creates deterministic seeded scenarios.
- The decision policy sees case features and chooses an eligible action.
- The hidden outcome model, used only through `SimulatedGateway`, decides whether that action
  succeeds.

There is no `optimal_action` label. The rules arm is measured by the outcome produced by the hidden
model, not by whether it agrees with a rule-generated answer. The oracle arm is evaluation-only and
provides a ceiling for interpretation.

### Fixed arms

`eval/harness.py` runs all five arms against the same scenario list and the same persisted
orchestration path:

- `control`: no treatment behavior; the current implementation represents this as a persisted wait
  candidate with no contact or charge side effect, so organic recovery can be measured.
- `naive`: uses the fixed candidate and executes at +1h, +24h, and +72h, reassessing between failed
  attempts.
- `rules`: uses deterministic eligible-action generation followed by the policy gate.
- `rules_llm`: retained as a compatibility arm that records deterministic-only availability status;
  it is not part of the active product mode.
- `oracle`: reads simulator-only outcome truth and is an upper-bound comparison.

All arms create the same database records: cases, decisions, policy evaluations, recovery actions,
payment attempts, messages, and audit events. This prevents a fast direct simulator call from
producing metrics that the real application could not reproduce.

### Attribution and incremental lift

A treatment is counted as recovered only when the case reaches `RECOVERED` and the successful
payment occurs within the configured 72-hour attribution window after the executed action. Control
provides the organic baseline. The harness reports:

```text
incremental recovery rate = treatment recovery rate - control recovery rate
incremental revenue       = treatment recovered paise - control recovered paise
```

The current comparison uses paired scenario rows, so treatment and control values are aligned by
scenario key. That makes the bootstrap estimate sensitive to the same case composition in both
arms.

### Statistical reporting

`eval/statistics.py` performs a seeded paired bootstrap with exactly 1,000 resamples and reports the
estimate, lower 2.5th percentile, upper 97.5th percentile, and resample count. The report does not
pretend that a positive point estimate is significant; if the interval crosses zero, that is the
correct finding to present.

### Metrics and artifacts

Each arm records:

- Money: recovered paise, revenue per case, incremental revenue, action cost, and cost per recovered
  rupee.
- Behavior: actions per case, contacts per recovered case, wasted actions against control,
  stop-rate, and mean time to recovery.
- Correctness: per-category precision/recall/F1, macro-F1, confusion matrix, and UNKNOWN rate.
- Safety: policy violations, denied rules, approval rate, duplicate-charge incidents, and messages
  outside the communication window.
- LLM: deterministic-only mode, availability status, schema failures, fallbacks, latency, cache
  hits, Brier/reliability status, and rules agreement. Calibration values are explicitly unavailable
  when no LLM confidence data exists; they are never fabricated.

The persisted `recovery_by_category` section reports cases, recovered cases, recovery rate, and
gross recovered paise for each expected failure category. The report also includes an explicit
metric-coverage section and does not label arm recovery rates as a reliability curve.

`eval/report.py` writes `metrics.json` and `report.md`. The JSON includes the seed, split, policy
hash, scenario-config hash, attribution window, and metric groups. `eval/charts.py` writes valid
PNG artifacts for reliability, recovery-by-category, and cumulative revenue without making
matplotlib a runtime requirement.

### Reproducibility

The same seed controls scenario generation, action outcomes, and bootstrap sampling. The evaluation
test runs the harness twice and compares the resulting `metrics.json` bytes. Reports are written to
separate directories so the timestamped directory name cannot affect the content comparison.

### Phase 3 commands

```powershell
# Final held-out-style evaluation report with all five arms
python -m eval.run --arms all --split test --seed 42 --count 1000

# Use all generated scenarios when a larger acceptance sweep is desired
python -m eval.run --arms all --split all --seed 42 --count 1000

# Phase 2 terminal-state gate remains available
python -m eval.acceptance --count 500 --seed 42
```

The report is explicitly simulator output. It is not a claim about live Razorpay recovery or
production customer behavior.

## 18. Optional LLM advisor code — inactive in deterministic-only mode

The repository contains an isolated advisor implementation, but the active product does not use
it. Deterministic taxonomy, recoverability, eligible-action generation, policy evaluation, and
message rendering are the only active decision path.

If the product decision is ever revisited, the advisor can propose an action or classify an unknown
failure, but it cannot create a new action, bypass eligibility, override a policy verdict, send a
message, or claim that a payment succeeded.

### Phase 4 scratch understanding

The decision path is:

```text
provider error
  -> deterministic taxonomy lookup
  -> if known: keep the rule category
  -> if UNKNOWN and an advisor is enabled: ask for a category
  -> compute deterministic recoverability and eligible actions
  -> ask the advisor to choose only from that eligible set
  -> validate strict JSON with Pydantic
  -> reject an ineligible action
  -> run the normal deterministic policy gate
  -> persist the proposal and provenance
```

`backend/llm/contracts.py` is the boundary. `LLMDecision` allows only an
`ActionType`, a bounded delay, confidence between zero and one, one to four reason
codes, and a short rationale. Extra fields are rejected. `LLMClassification` allows
only a known `FailureCategory`.

`agent/prompts/v1.txt` is versioned and intentionally narrow. It receives a
canonical input snapshot and the already-computed eligible action list. It does not
receive authority to choose a template, change money, or invent a gateway result.
The adapter requests temperature zero and has an eight-second timeout. A malformed
response gets one repair attempt; after that, the deterministic rule wins.

### Why the default is deterministic-only

`LLMAdvisor.from_environment()` creates an Anthropic provider only when
`ANTHROPIC_API_KEY` is present. The active deterministic-only configuration leaves this key empty,
so the product never depends on paid API access. The compatibility `rules_llm` evaluation arm
falls back to the same deterministic rule action.

### Cache and auditability

The SQLite cache key is SHA-256 over the model, prompt version, canonical input,
and eligible actions. A valid response is reused without another provider call.
Each LLM-backed decision can persist the input snapshot, model, prompt version,
cache key, raw parsed response, confidence, latency, and fallback reason in
`recovery_decisions`. The evaluator also reports request, schema-failure, fallback,
cache-hit, latency, and rules-agreement metrics. Confidence is kept as an audit
field; it is not shown as a trustworthy probability until calibration data exists.

### Phase 4 interview questions

**What if the model says `RETRY_MANDATE_CHARGE` for a one-off order?**

The deterministic eligible set for a class-B case does not contain that action.
Pydantic parses the shape, then the advisor rejects the value as ineligible and
falls back to the rule action. Even if that check were missed, the policy engine
would deny the class mismatch.

**What happens when the model is down or the key is absent?**

The source is recorded as `RULE`, the fallback reason is recorded, and the normal
rules path continues. The availability of an optional model cannot become a
business dependency.

**Why classify UNKNOWN before selecting an action?**

Failure category affects recoverability and eligibility. A model may help turn an
ambiguous provider error into a known category, but the resulting category still
passes through the same recoverability, action, and policy functions. If the model
cannot produce a valid category, the case stays `UNKNOWN`.

## 19. Phase 5 - Verified Razorpay path

Phase 5 connects only the provider behavior that has been verified for this
project. The webhook endpoint validates the raw request bytes with
`X-Razorpay-Signature` and HMAC-SHA256, deduplicates on
`x-razorpay-event-id`, and stores the event before returning success. The request
handler does not normalize, decide, contact the customer, or call Razorpay.

The background path is:

```text
POST /webhooks/razorpay
  -> verify signature against raw bytes
  -> insert raw event if event id is new
  -> return HTTP 200

worker
  -> load unprocessed raw event
  -> normalize provider payload
  -> persist order/subscription/payment attempt
  -> open or deduplicate recovery case
  -> classify, decide, policy-evaluate, and schedule
  -> in demo execution mode, call the adapter

adapter
  -> POST /v1/payment_links
  -> record provider link id and short URL
  -> wait for a captured-payment webhook
  -> mark the case recovered only after payment evidence arrives
```

### Verified payment-link operation

`backend/gateway/razorpay_adapter.py` uses HTTP Basic Auth from environment
variables and calls the documented Payment Links endpoint. The request uses
integer paise, `INR`, a unique case reference limited to 40 characters, a Unix
expiry timestamp, and notification/reminder suppression. The project decision is
a 24-hour expiry, `notify.email=false`, `notify.sms=false`, and
`reminder_enable=false`. The adapter requires `id` and `short_url` in the
response.

The provider documentation used for this boundary is:

- https://razorpay.com/docs/api/payments/payment-links/create-standard/
- https://razorpay.com/docs/webhooks/validate-test/?locale=en-US

There is deliberately no guessed provider idempotency header on this call. The
application still creates a durable SHA-256 action idempotency key and inserts the
action before execution. A retry of the same internal action therefore reuses the
same action record; provider-level idempotency is not claimed where it has not been
verified.

### What is and is not live

The adapter has a real Test Mode HTTP path and a fake-client integration test. A
live Test Mode request was not made during local implementation because it requires
the merchant's `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, database, and reachable
HTTPS tunnel. Once those are configured, the remaining acceptance step is to send
one real failure through the configured webhook, run the worker, open the returned
payment link, and send/receive the captured event. The case must finish in
`RECOVERED` only after that webhook is processed.

Mandate charging and regulatory retry/pre-debit rules remain disabled or fail
closed. The class-C sweeper is implemented in `backend/ingestion/sweeper.py`, but
the real adapter requires `RAZORPAY_ENABLE_ORDER_SWEEPER=true` before it will call
the Orders API. Its default is false until the merchant captures and verifies the
Test Mode response. Their provider endpoint, retry limits, legal requirements, or
idempotency behavior must not be inferred from the payment-link API.

### Phase 5 interview questions

**Why does a successful payment-link HTTP response not recover the case?**

Creating a link only creates an opportunity to pay. Recovery is a financial fact,
so the case remains `DECIDED` and the action records
`PAYMENT_LINK_CREATED_AWAITING_PAYMENT`. A captured-payment webhook is the evidence
that moves the case to `RECOVERED`.

**Why acknowledge the webhook before processing it?**

Webhook providers retry when acknowledgement is slow or unavailable. Persisting
the verified raw event and returning quickly makes the boundary reliable. A worker
can retry normalization or policy work without making the provider resend the
event, and the unique event id prevents duplicate cases.

**How do you prevent a duplicate charge?**

The action is revalidated immediately before execution. If the order is already
paid, the action is skipped. Gateway results are read back where that operation is
verified; captured webhook evidence is also idempotently stored by payment id.
Any race that creates multiple captured attempts emits the explicit duplicate-charge
incident event for refund review.

**What would you show a reviewer?**

Show the raw-event row, normalized payment attempt, case timeline, policy hash,
decision/action idempotency key, adapter response, and the captured webhook that
closed the case. Label the link call as real Test Mode, the message as rendered but
not sent, and simulator recovery results as modelled rather than production claims.

## 20. Phase 6 - API-backed dashboard

Phase 6 turns the visual shell into an operations console over persisted backend
state. The browser does not own business logic and does not recompute evaluation
metrics. It calls the API and renders the records already produced by ingestion,
orchestration, policy, and evaluation.

### Dashboard data flow

```text
React dashboard
  -> GET /api/cases?state=...
  -> GET /api/cases/{id}
  -> GET /api/approvals
  -> GET /api/policy
  -> GET /api/evaluation
  -> render persisted records
```

The Overview page shows at-risk money, confirmed recovered money, policy violations,
recent cases, and the latest stored rules metrics. The Cases page supports state
filtering and safe paise-to-rupee display. Selecting a case opens the timeline.

The timeline combines audit events, payment attempts, decisions, policy evaluations,
actions, and rendered messages, then sorts them by timestamp. Rendered messages are
explicitly labelled `not sent`, because the application does not send email or SMS.

The Policy page displays the active configuration and its SHA-256 hash. The
Evaluation page reads the latest `metrics.json` generated by `eval.run`; the UI does
not call the evaluator or change the numbers.

### Approval queue safety

High-value cases appear in the Approval Queue. Approval and rejection require the
restricted `X-Approval-Token` configured as `APPROVAL_API_TOKEN`. The endpoint
rejects missing or invalid tokens, rejects already-decided approvals, records the
human note, and writes an audit event. Approval changes the case state to
`DECIDED`; rejection resolves it as `STOPPED`. No action can execute before the
explicit approval state exists.

### Phase 6 interview questions

**Why does the dashboard not calculate recovery metrics itself?**

The evaluator is the source of truth for paired control comparisons, attribution
windows, bootstrap intervals, and scenario hashes. Recomputing in JavaScript could
produce a different result and would hide the evidence used to create the report.
The dashboard reads stored JSON and displays its metadata.

**How can a reviewer audit one case?**

The reviewer opens the case, sees the amount and classification, then follows the
timeline from raw ingestion through decision, policy hash and fired rules,
scheduling, action result, rendered communication, and payment evidence. Each row
contains its actor and payload.

**Why is the approval endpoint restricted?**

Approval is a privileged human control. A public unauthenticated route could turn
the queue into an execution bypass. The token is a small internal-demo boundary;
production deployment would additionally require authenticated identity, role
checks, CSRF protection, and an immutable operator identity.

**What is still not live in the dashboard?**

The UI is API-backed, but a live database must contain records before the pages show
cases. The payment-link call is real Test Mode only, messages remain rendered, and
the simulator's outcome model is never presented as live Razorpay recovery.

## 21. Commands to demonstrate the implementation

From the repository root:

```powershell
# Run all automated tests
.venv\Scripts\python.exe -m pytest -q

# Run lint
.venv\Scripts\ruff.exe check backend sim eval tests

# Check the deterministic 1,000-case generator acceptance test
.venv\Scripts\python.exe -m pytest tests/unit/test_evaluation.py -q

# Run the Phase 2 acceptance gate
.venv\Scripts\python.exe -m eval.acceptance --count 500 --seed 42

# Run the named evaluation arms and write a report
.venv\Scripts\python.exe -m eval.run --arms all --split test --seed 42 --count 1000

# Build the dashboard
cd frontend
npm run build
cd ..

# Start the local services when Docker is installed
docker compose up --build

# With DATABASE_URL and Razorpay Test Mode variables in local .env,
# process stored webhooks and execute the safe demo action.
.venv\Scripts\python.exe -m backend.ingestion.worker
```

For a demo, show a failed one-off case, prove that a mandate retry is denied for class B, show a
mandate case entering the schedule, mark the order paid before execution, and show the action being
skipped by revalidation. Then show a high-value case entering the manual approval queue.

## 22. Final positioning

The strongest engineering story is not “the simulator recovered money.” The accurate story is:

> The system makes recovery decisions explainable, policy-constrained, idempotent, restart-safe, and
> verifiable. The simulator demonstrates the behavior deterministically, while live Razorpay
> operations remain deliberately restricted until their provider and legal requirements are
> verified.
