# Track 03 — AI Revenue Recovery
## Build Specification for Claude Code (v2, corrected)

**Status of this document:** this is the *authoritative* build spec. It supersedes any
earlier plan. Where this document and an earlier plan disagree, this document wins.

---

# 0. READ THIS FIRST — Rules for the implementing agent

These rules exist because the previous version of this plan contained invented API
behaviour, invented metrics, and an evaluation design that measured its own simulator.
Follow these rules literally.

## 0.1 Never invent an external API

You may **only** call a Razorpay endpoint, field, error code, or webhook event that you
have confirmed exists. Confirmation means one of:

- it appears in `docs/razorpay-verified.md` in this repo (written by a human after
  reading the official docs), **or**
- you fetched the official documentation page in this session and can quote the field
  name from it.

If neither holds: **stop, write the question into `OPEN_QUESTIONS.md`, and implement
against the `SimulatedGateway` adapter instead.** Do not guess an endpoint path, a
field name, an error code string, or a rate limit.

## 0.2 Every number in this document that looks like a result is a placeholder

Any percentage, rupee amount, retry-count cap, or delay value shown as an *example* in
this document is illustrative. It is **not** a target and must **not** be hardcoded as a
constant that the system tries to reach. All real numbers come out of `eval/` at runtime.

Anything genuinely fixed is marked **[CONSTANT]** and lives in `config/policy.yaml`.

## 0.3 Confidence tags used below

- **[VERIFIED]** — checked against a primary source or is a plain engineering fact.
- **[ASSUMPTION]** — believed true, must be confirmed before it affects money movement.
  Every [ASSUMPTION] is repeated in §17 with the check that resolves it.
- **[DESIGN CHOICE]** — a decision made for this project; no external truth to verify.

## 0.4 Definition of done for any phase

A phase is done when: its acceptance test passes, `pytest` is green, and the phase's
row in `PROGRESS.md` is checked off with the commit SHA. Do not start phase N+1 with
phase N red.

---

# 1. What went wrong in the previous plan

Kept here deliberately so the same mistakes are not reintroduced.

| # | Problem | Severity | Fix in this spec |
|---|---------|----------|------------------|
| 1 | Treated "retry the failed payment" as the default recovery action for all failures. A merchant generally **cannot** re-charge a failed one-off card/UPI payment server-side — there is no saved instrument or customer consent to charge again. Retry is only meaningful where a mandate/token exists (subscriptions, UPI Autopay, e-mandate). | **Fatal** | §4 splits the world into *mandate-backed* and *one-off* cases with different action sets. §5.3 |
| 2 | Architecture was webhook-only, so **checkout abandonment was silently unhandled** — an abandoned checkout produces no payment object and therefore no `payment.failed` event. | **Fatal** | §6.2 adds an order-sweeper poller as a first-class ingestion path |
| 3 | Evaluation was circular: the same generator defined `optimal_action` as ground truth *and* decided outcomes, so the rule engine scores ~100% by construction and the LLM can only lose. The reported "recovery rate" would have been a number the team invented. | **Fatal** | §11 separates the hidden *outcome model* from the decision policy, adds a held-out scenario split, and adds a control holdout for incremental lift |
| 4 | Example eval output contained fabricated results (21.4% / 34.8% / ₹2.1L / ₹3.5L). If fed to a coding agent these become targets. | High | §0.2 |
| 5 | The rule engine was used as **both** the baseline and the system under test. No naive baseline existed. | High | §11.2 defines three arms: `naive`, `rules`, `rules+llm` (+ optional `oracle` ceiling) |
| 6 | Two incompatible state machines (§7 vs §24 of the old plan) with different state names. | High | §7 defines one canonical enum |
| 7 | `rollback()` on every action. You cannot roll back a sent SMS or a captured payment. | High | §9.4 replaces it with `compensate()` + an explicit `reversible: bool` that the policy gate reads |
| 8 | No double-charge protection. If a customer pays manually while a mandate retry is in flight, the system charges twice. | High | §9.5 pre-execution freshness check + idempotency + refund path |
| 9 | "Bank outage? → WAIT" with no data source. A coding agent will invent an outage API. | High | §8.4 defines outage as a derived signal computed from your own event stream |
| 10 | Confidence numbers (0.94, 92%) shown in the demo UI with no calibration. Uncalibrated confidence in a money system is worse than none. | Medium | §10.5 either measure calibration (Brier + reliability curve) or delete the field |
| 11 | Money as decimal rupees. | Medium | §7.1 integer **paise** everywhere |
| 12 | No consent model, no communication-window rules, no Indian outreach compliance — while the track brief explicitly asks for "compliant escalation". | Medium | §8.5 |
| 13 | No attribution rule for "recovered". A customer paying on their own 3 days later would have been counted as an agent win. | Medium | §11.4 attribution window + control group |
| 14 | Tables declared but never defined or used (`action_outcomes`, `notifications`, `policies`), and `recovery_cases.recommended_action` denormalized state that belongs in `recovery_actions`. | Medium | §7.2 full DDL, no orphan tables |
| 15 | Scope: Celery + Redis + RBAC + circuit breakers + OpenTelemetry + 44 sections for a hackathon. Guarantees a half-built demo. | Medium | §2.2 explicit non-goals |
| 16 | Every eval run would hit real Razorpay APIs — slow, rate-limited, and impossible to produce failures on demand. | Medium | §6.4 gateway adapter interface; eval runs against the simulator only |
| 17 | No timezone or scheduling-window definition. | Low | §7.1 UTC storage, IST business rules |
| 18 | The headline demo (retry a ₹7,500 insufficient-funds card payment) is not executable under problem #1. | Low | §15 rewritten demo with two cases |

---

# 2. Scope

## 2.1 What we are building

A **payment recovery decisioning system**. Given a revenue-at-risk event, it:

1. classifies why revenue is at risk,
2. decides whether it is recoverable and by what intervention,
3. schedules that intervention,
4. re-validates and executes it through a bounded, auditable, policy-gated path,
5. verifies the real outcome,
6. and reports measured incremental recovery against a naive baseline.

**Governing principle [DESIGN CHOICE]:**

> The LLM proposes. Deterministic code disposes. No LLM output ever reaches a
> money-moving API without passing a deterministic policy gate that can veto it.

## 2.2 Non-goals (do NOT build these)

Celery/RQ · Redis · Kubernetes · RBAC/multi-tenant auth · OpenTelemetry/Jaeger ·
circuit breakers · voice/IVR · WhatsApp integration · a chat interface · ML models ·
a real SMS/email sender (log-and-render only, see §9.3) · vector DB · RAG ·
multi-agent orchestration.

Every one of these is a plausible-sounding trap. Mention them in the "what's next"
slide; do not write code for them.

## 2.3 The three revenue-at-risk classes we cover

| Class | Trigger | Can we charge without the customer? |
|---|---|---|
| **A. Mandate-backed failure** — failed subscription / autopay / e-mandate debit | webhook | **Yes** — a real retry is possible [ASSUMPTION A1] |
| **B. One-off payment failure** — checkout attempt failed | webhook | **No** — recovery = re-engagement (link/reminder/alternate method) |
| **C. Checkout abandonment** — order created, no successful payment | **poller**, not webhook | **No** — recovery = re-engagement |

Class B and C are the same downstream; they differ only in ingestion and in how much
context exists. **Build A and B first. C is a stretch goal.**

---

# 3. Assumed constraints

- **[ASSUMPTION]** Team size and deadline unknown at time of writing. The phase plan in
  §13 is written as **D-7 → D-0** (seven working days). If you have fewer days, cut from
  the *end* of the list (Phase 8, then 7, then 6). Never cut Phase 3 (evaluation harness).
- Razorpay **test mode** only. No real money, ever.
- Single merchant. No multi-tenancy.
- Python 3.11+, Postgres 15+, Node 20+ for the frontend.

---

# 4. Domain model — the part that must be right

## 4.1 Failure taxonomy [DESIGN CHOICE]

Internal categories, deliberately gateway-agnostic. The mapping from Razorpay error
codes to these lives in exactly one file (`domain/failure_taxonomy.py`) and nowhere else.

```
TEMPORARY_GATEWAY_ERROR     # gateway-side transient
TEMPORARY_BANK_ERROR        # issuer/bank-side transient, incl. timeouts
INSUFFICIENT_FUNDS
LIMIT_EXCEEDED              # per-txn / daily limit hit
AUTHENTICATION_FAILED       # OTP/3DS/UPI PIN not completed
INSTRUMENT_EXPIRED
INSTRUMENT_INVALID          # bad card/VPA/closed account
RISK_DECLINE                # issuer or gateway risk rejection
MANDATE_INVALID             # mandate revoked, paused, or expired
CUSTOMER_ABANDONED          # class C: no attempt completed
CUSTOMER_CANCELLED          # explicit user cancel
UNKNOWN
```

**Rule:** any Razorpay error code not present in the mapping table resolves to `UNKNOWN`
and `UNKNOWN` is always routed to the LLM classifier (§10) and, if still ambiguous, to
the human queue. **[VERIFIED]** Razorpay returns a structured error object on failed
payments containing a code, a step, a reason, and a description — but the exact
enumeration of `reason` values must be read from the docs, not guessed. Write what you
find into `docs/razorpay-verified.md`.

## 4.2 Recoverability

A derived, three-valued field — not a boolean:

```
RECOVERABLE_AUTOMATED   # we may act without the customer (class A only)
RECOVERABLE_ASSISTED    # needs the customer to act; we can prompt them
NOT_RECOVERABLE         # stop; e.g. CUSTOMER_CANCELLED, MANDATE_INVALID w/o re-auth
```

The mapping from `(failure_category, class, attempt_history)` → recoverability is
deterministic and lives in `domain/recoverability.py`. It is **not** an LLM decision.

## 4.3 Action catalogue

| Action | Valid for class | Reversible | Costs money | Contacts customer |
|---|---|---|---|---|
| `RETRY_MANDATE_CHARGE` | A | no | yes (charges) | no |
| `RESCHEDULE_MANDATE_CHARGE` | A | yes | no | no (unless notice required) |
| `CREATE_PAYMENT_LINK` | B, C | yes (can expire it) | no | no by itself |
| `SEND_REMINDER` | A, B, C | **no** | no | **yes** |
| `SUGGEST_ALTERNATE_METHOD` | B, C | no | no | yes |
| `WAIT` | all | yes | no | no |
| `ESCALATE_TO_HUMAN` | all | yes | no | no |
| `STOP` | all | terminal | no | no |

`SEND_REMINDER` and `SUGGEST_ALTERNATE_METHOD` are irreversible in the only sense that
matters: you cannot unsend a message. They therefore consume the **contact budget**
(§8.3) and are subject to the communication window (§8.5).

---

# 5. Corrected recovery logic

## 5.1 Why "retry" is not the default

**[ASSUMPTION A1 — must verify, §17]** Re-charging a customer requires either an active
mandate/subscription or a saved token with recurring consent. A one-off failed payment
has neither, so for class B the merchant's only lever is to get the customer to pay
again. Any code path that tries to "retry" a class-B payment is a bug.

Enforcement: `actions/registry.py` declares `allowed_classes` per action, and
`PolicyEngine` rejects any action whose `allowed_classes` does not contain the case's
class. There is a unit test for exactly this (§14, T-07).

## 5.2 Class A flow (mandate-backed)

```
subscription/mandate charge fails
  → webhook → case opened (class=A)
  → classify failure
  → recoverability = RECOVERABLE_AUTOMATED (if category is transient/funds)
  → decide: RETRY_MANDATE_CHARGE at T+Δ, or RESCHEDULE, or ESCALATE
  → policy gate: retry budget, regulatory retry cap [ASSUMPTION A2],
                 pre-debit notice requirement [ASSUMPTION A3],
                 amount ceiling, outage guard, freshness
  → schedule
  → at execution time: RE-CHECK everything, then execute with idempotency key
  → verify by reading payment status back from the gateway (never trust HTTP 200)
  → RECOVERED | reassess | EXHAUSTED
```

## 5.3 Class B/C flow (one-off / abandoned)

```
payment fails / order goes stale
  → case opened (class=B or C)
  → classify failure
  → recoverability = RECOVERABLE_ASSISTED or NOT_RECOVERABLE
  → decide: CREATE_PAYMENT_LINK (+ SEND_REMINDER), SUGGEST_ALTERNATE_METHOD,
            WAIT, or STOP
  → policy gate: contact budget, communication window, consent, cooldown, dedupe
  → schedule + execute
  → verify: did a *new* successful payment appear for this order within the
            attribution window? (§11.4)
  → RECOVERED | reassess | EXHAUSTED
```

Note the asymmetry: in class B we are measuring whether *the customer* paid, which is why
the control holdout in §11.4 is not optional. Some of them would have paid anyway.

---

# 6. Architecture

```
   ┌──────────────┐        ┌──────────────────┐
   │  Razorpay    │        │ SimulatedGateway │   ← eval + tests run here
   │  (test mode) │        │  (outcome model) │
   └──────┬───────┘        └────────┬─────────┘
          │                         │
          └──────────┬──────────────┘
                     ▼
            GatewayAdapter (interface)          §6.4
                     │
   ┌─────────────────┼─────────────────┐
   ▼                 ▼                 ▼
Webhook API     Order Sweeper      Action calls
(class A,B)     (class C)          (outbound)
   │                 │                 ▲
   └────────┬────────┘                 │
            ▼                          │
   Event Ingest → dedupe → normalize   │
            │                          │
            ▼                          │
   ┌────────────────────┐              │
   │  Postgres          │              │
   │  (single source    │              │
   │   of truth)        │              │
   └─────────┬──────────┘              │
             ▼                         │
      Case Orchestrator ───────────────┘
             │
   ┌─────────┴──────────┐
   ▼                    ▼
Rule Engine        LLM Advisor          §10
   │                    │
   └─────────┬──────────┘
             ▼
      POLICY ENGINE  ← the only door to money        §8
             │
             ▼
        Scheduler (APScheduler)                      §9.2
             │
             ▼
   Re-validate → Execute → Verify                    §9.5
             │
             ▼
      Audit log + Metrics → Dashboard / eval report
```

## 6.1 Process layout [DESIGN CHOICE]

One FastAPI process. APScheduler runs **in-process** with a Postgres jobstore. No Celery,
no Redis, no separate worker container. `docker-compose` has exactly two services:
`api` and `db`.

## 6.2 Ingestion paths

- `POST /webhooks/razorpay` — classes A and B.
- **Order sweeper** — APScheduler job, every 5 minutes **[CONSTANT]**, lists orders whose
  status is not paid and whose `created_at` is older than the abandonment threshold
  (default 30 min **[CONSTANT]**), and opens class-C cases. Required because abandonment
  emits no webhook. **[ASSUMPTION A4]** — confirm the exact order-status values and the
  list-orders filter parameters from the docs before implementing.

## 6.3 Webhook handler — the two bugs everyone hits

1. **Signature verification must use the raw request body bytes.**
   `X-Razorpay-Signature` is an HMAC-SHA256 of the exact bytes Razorpay sent, keyed on the
   webhook secret. If you parse the JSON and re-serialize it, verification fails
   intermittently and mysteriously. In FastAPI: `raw = await request.body()`, verify
   against `raw`, and only then `json.loads(raw)`. Compare with
   `hmac.compare_digest`. **[VERIFIED]** as a general HMAC-webhook fact; confirm the
   header name and algorithm in the docs and record it in `docs/razorpay-verified.md`.
2. **At-least-once delivery.** Persist the event with a unique constraint on the
   provider event id; on conflict, return 200 and do nothing. The handler must return 200
   fast (< 2s) and hand off all real work to the scheduler — retries triggered by your own
   slow handler will duplicate cases.

Handler contract: verify → dedupe-insert `raw_events` → 200. Everything else is a job.

## 6.4 Gateway adapter — mandatory

```python
class GatewayAdapter(Protocol):
    def get_payment(self, payment_id: str) -> PaymentSnapshot: ...
    def get_order(self, order_id: str) -> OrderSnapshot: ...
    def charge_mandate(self, sub_id: str, amount_paise: int,
                       idempotency_key: str) -> ChargeResult: ...
    def create_payment_link(self, case_id: str, amount_paise: int,
                            expires_at: datetime,
                            idempotency_key: str) -> PaymentLink: ...
    def list_stale_orders(self, older_than: datetime) -> list[OrderSnapshot]: ...
```

Two implementations: `RazorpayAdapter` (live demo, test mode) and `SimulatedGateway`
(eval + all tests). **The evaluation harness never touches the network.** This is what
makes a 2,000-scenario eval run in seconds instead of hours, and it is what lets you
produce failure types on demand that Razorpay test mode will not give you.

---

# 7. Data model

## 7.1 Global conventions [CONSTANT]

- Money: **integer paise**, column name always suffixed `_paise`. Never float, never
  `Decimal` in the API layer, never rupees in the DB.
- Time: all timestamps `TIMESTAMPTZ`, stored **UTC**. Business rules that reference hours
  of day (communication windows) convert to `Asia/Kolkata` at the point of evaluation, in
  one helper function.
- IDs: ULIDs as `TEXT` for internal entities; provider IDs stored separately and never
  used as primary keys.
- Every table has `created_at`; mutable tables have `updated_at`.
- Enums: Postgres native enums, mirrored by Python `StrEnum`. One source of truth in
  `domain/enums.py`; Alembic migration generated from it.

## 7.2 Schema

```sql
-- identity ------------------------------------------------------------
merchants(id PK, name, created_at)

customers(
  id PK, merchant_id FK, external_ref,
  email_hash, phone_hash,            -- never store raw PII in plaintext
  created_at,
  UNIQUE(merchant_id, external_ref)
)

customer_consent(
  id PK, customer_id FK,
  channel ENUM(EMAIL, SMS),
  state ENUM(OPTED_IN, OPTED_OUT, UNKNOWN),
  captured_at, source,
  UNIQUE(customer_id, channel)
)

-- money ---------------------------------------------------------------
orders(
  id PK, merchant_id FK, customer_id FK,
  provider_order_id UNIQUE, amount_paise BIGINT, currency,
  status ENUM(CREATED, ATTEMPTED, PAID, EXPIRED),
  created_at, updated_at
)

subscriptions(                        -- class A only
  id PK, customer_id FK, provider_sub_id UNIQUE,
  status, amount_paise BIGINT, next_charge_at,
  mandate_active BOOLEAN, created_at, updated_at
)

payment_attempts(                     -- append-only, never UPDATE a row's outcome
  id PK, order_id FK NULL, subscription_id FK NULL,
  attempt_number INT,
  provider_payment_id, method,
  amount_paise BIGINT,
  status ENUM(CREATED, AUTHORIZED, CAPTURED, FAILED),
  raw_error_code, raw_error_reason, raw_error_description,
  failure_category ENUM(...),         -- normalized, §4.1
  classified_by ENUM(RULE, LLM, HUMAN),
  initiated_by ENUM(CUSTOMER, RECOVERY_SYSTEM),
  recovery_action_id FK NULL,         -- set when we caused this attempt
  occurred_at, created_at,
  CHECK (order_id IS NOT NULL OR subscription_id IS NOT NULL)
)

-- recovery ------------------------------------------------------------
recovery_cases(
  id PK, merchant_id FK, customer_id FK,
  order_id FK NULL, subscription_id FK NULL,
  case_class ENUM(A_MANDATE, B_ONEOFF, C_ABANDONED),
  amount_at_risk_paise BIGINT,
  failure_category ENUM(...),
  recoverability ENUM(...),
  state ENUM(...),                    -- §7.3, single canonical enum
  contacts_used INT DEFAULT 0,
  charge_attempts_used INT DEFAULT 0,
  next_action_at TIMESTAMPTZ NULL,
  experiment_arm TEXT NULL,           -- 'control' | 'treatment' | eval arm name
  opened_at, resolved_at NULL,
  resolution ENUM(RECOVERED, EXHAUSTED, STOPPED, EXPIRED) NULL,
  recovered_amount_paise BIGINT NULL,
  recovered_attempt_id FK NULL,       -- the attempt that closed it; attribution proof
  UNIQUE(order_id) WHERE order_id IS NOT NULL     -- one open case per order
)

recovery_decisions(                   -- what was PROPOSED, by whom
  id PK, case_id FK,
  proposed_action ENUM(...),
  proposed_delay_minutes INT NULL,
  source ENUM(RULE, LLM),
  rule_id TEXT NULL,
  reason_codes TEXT[],
  llm_model TEXT NULL, llm_confidence NUMERIC NULL,
  llm_raw_response JSONB NULL, llm_latency_ms INT NULL,
  input_snapshot JSONB NOT NULL,      -- exact features the decider saw
  created_at
)

policy_evaluations(                   -- what the gate DID about it
  id PK, decision_id FK, case_id FK,
  verdict ENUM(ALLOW, DENY, DOWNGRADE, REQUIRE_HUMAN),
  final_action ENUM(...) NULL,
  rules_fired JSONB,                  -- [{rule_id, passed, detail}, ...]
  evaluated_at
)

recovery_actions(                     -- what we actually DID
  id PK, case_id FK, policy_evaluation_id FK,
  action_type ENUM(...),
  idempotency_key TEXT UNIQUE NOT NULL,
  scheduled_for TIMESTAMPTZ,
  state ENUM(SCHEDULED, REVALIDATING, EXECUTING, EXECUTED, SKIPPED, FAILED, CANCELLED),
  skip_reason TEXT NULL,              -- why a scheduled action did not run
  executed_at NULL, provider_ref NULL,
  result JSONB NULL, created_at, updated_at
)

human_approvals(
  id PK, case_id FK, decision_id FK,
  requested_at, decided_at NULL,
  decision ENUM(APPROVED, REJECTED) NULL, note TEXT NULL
)

outbound_messages(                    -- rendered, NOT sent (§9.3)
  id PK, case_id FK, action_id FK,
  channel ENUM(EMAIL, SMS), template_id TEXT,
  rendered_subject TEXT NULL, rendered_body TEXT,
  generated_by ENUM(TEMPLATE, LLM),
  created_at
)

audit_events(                         -- append-only, no UPDATE, no DELETE
  id PK, case_id FK NULL,
  event_type TEXT, actor ENUM(SYSTEM, RULE, LLM, HUMAN, GATEWAY),
  payload JSONB, occurred_at
)

raw_events(                           -- webhook dedupe + replay
  id PK, provider_event_id TEXT UNIQUE, event_type TEXT,
  signature_valid BOOLEAN, payload JSONB,
  processed_at NULL, received_at
)
```

Four tables from the old plan (`payments`, `payment_failures`, `action_outcomes`,
`notifications`, `policies`) are gone: merged, renamed, or never used. Policies are
**config**, not rows — see §8.1.

## 7.3 Canonical case state machine

One enum. Nothing else.

```
OPEN
  → CLASSIFIED
  → DECIDED
  → AWAITING_APPROVAL     (only from DECIDED, when policy = REQUIRE_HUMAN)
  → SCHEDULED
  → EXECUTING
  → VERIFYING
  → RECOVERED     (terminal)
  → EXHAUSTED     (terminal — budget spent, still unpaid)
  → STOPPED       (terminal — policy or consent says never contact/charge again)
  → EXPIRED       (terminal — order/mandate no longer chargeable)
```

Legal transitions live in `domain/state_machine.py` as an explicit dict. Any
transition not in that dict raises `IllegalTransition`. `VERIFYING → DECIDED` is the
reassessment loop. Nothing may leave a terminal state. Test T-03 asserts the full matrix.

---

# 8. Policy engine — the only door to money

## 8.1 Form

A pure function. No I/O, no LLM, no network:

```python
def evaluate(case: CaseSnapshot,
             decision: Decision,
             world: WorldState,
             policy: PolicyConfig) -> PolicyVerdict
```

`WorldState` carries everything time-dependent (now, outage signals, consent, current
order status). It is passed in, never fetched inside, so the function is deterministic
and trivially testable. `PolicyConfig` is loaded from `config/policy.yaml` — policies are
versioned config, and the loaded config **hash is written into every
`policy_evaluations` row** so a judge can prove which rules were in force.

Verdict is one of `ALLOW` / `DENY` / `DOWNGRADE` / `REQUIRE_HUMAN`, plus `rules_fired`
listing every rule with pass/fail and a human-readable detail string. `DOWNGRADE` means
"not that action, but this weaker one is allowed" (e.g. `RETRY_MANDATE_CHARGE` →
`SEND_REMINDER`). Downgrade is what stops the system oscillating between "do the risky
thing" and "do nothing".

## 8.2 Rule set (all [CONSTANT], all in `policy.yaml`)

Ordered; first `DENY` wins, `REQUIRE_HUMAN` beats `ALLOW`.

| id | Rule | Default |
|---|---|---|
| P01 | Action must be permitted for this `case_class` | hard |
| P02 | Case must not be in a terminal state | hard |
| P03 | Consent: no contact action if `OPTED_OUT` | hard |
| P04 | Contact budget: `contacts_used < max_contacts` | 3 per case |
| P05 | Charge budget: `charge_attempts_used < max_charge_attempts` | 3 per case |
| P06 | Cooldown: no action within `min_gap_minutes` of the last one | 360 |
| P07 | Communication window (§8.5) — else DOWNGRADE to reschedule | 09:00–20:00 IST |
| P08 | Amount ceiling: `amount_at_risk > auto_ceiling` → REQUIRE_HUMAN | 10,00,000 paise |
| P09 | Outage guard (§8.4): if the target rail is degraded → DOWNGRADE to WAIT | — |
| P10 | Freshness: order/mandate must still be chargeable and unpaid | hard |
| P11 | Irreversible actions require `verdict != REQUIRE_HUMAN` pending | hard |
| P12 | Global kill switch | off |
| P13 | Case age: no action after `max_case_age_hours` | 168 |
| P14 | Regulatory retry cap for mandate charges | [ASSUMPTION A2] |
| P15 | Pre-debit notice: mandate charge needs notice sent ≥ N hours prior | [ASSUMPTION A3] |

P14 and P15 must **not** be given invented numeric values. Implement them as rules that
read from config, ship them **disabled with a loud `NotVerified` warning in the audit
log**, and enable them only when a human fills in the verified value. This is a feature:
a slide that says "these two rules are regulatory and we refused to guess the numbers" is
worth more to a payments judge than a confident wrong number.

## 8.3 Budgets are per-case and per-customer

`max_contacts` is enforced per case **and** per customer per rolling 7 days
**[CONSTANT: 5]**. Without the second cap, a customer with four failing orders gets
twelve messages and the system looks like spam.

## 8.4 Outage signal — derived, not fetched

```
degraded(rail, now) := over the last 15 min window [CONSTANT],
    attempts(rail) >= 20 [CONSTANT]
    AND failure_rate(rail) >= 2.5x [CONSTANT] the trailing 24h baseline for that rail
```

`rail` = `(method, issuer_or_bank)` where known, else `method`. Computed by a SQL query
over `payment_attempts`. Do **not** call any external status API — none is defined for
this project. When degraded, mandate charges are deferred until the window clears plus a
cooldown **[CONSTANT: 30 min]**.

This is also a genuinely good demo beat: show the system voluntarily *not* retrying
during a simulated bank outage while the naive baseline burns its retry budget.

## 8.5 Communication compliance

- Window: 09:00–20:00 IST **[CONSTANT]**. Outside it → `DOWNGRADE` to a reschedule at the
  next window open, never a silent send.
- Consent state must be `OPTED_IN` for SMS. `UNKNOWN` is treated as **not** opted in for
  SMS and as allowed for transactional email tied to an existing order
  **[ASSUMPTION A5 — this is a legal question; flag it, do not lawyer it]**.
- Every rendered message carries an opt-out line.
- **[ASSUMPTION A6]** Indian SMS to customers generally requires DLT-registered
  templates and DND scrubbing. Since we do not actually send (§9.3), we model this as a
  `template_id` that must exist in `config/templates.yaml` with a
  `dlt_registered: true|false` flag, and the policy engine refuses templates flagged
  false. Say in the demo that this is modelled, not integrated.

---

# 9. Execution

## 9.1 Action interface

```python
class RecoveryAction(Protocol):
    action_type: ActionType
    allowed_classes: set[CaseClass]
    reversible: bool
    consumes_contact_budget: bool
    consumes_charge_budget: bool

    def preconditions(self, ctx) -> list[CheckResult]: ...
    def execute(self, ctx, idempotency_key: str) -> ActionResult: ...
    def compensate(self, ctx) -> CompensationResult: ...   # best-effort, may be NO_OP
```

`compensate()` returns `NO_OP` with a reason for irreversible actions. It does not
pretend. For `CREATE_PAYMENT_LINK`, compensation is expiring the link. For a mandate
charge that succeeded after the customer already paid, compensation is **initiating a
refund** and marking the case `RECOVERED` with a `duplicate_charge_refunded` flag —
see §9.5.

## 9.2 Scheduling

APScheduler with a `SQLAlchemyJobStore` on the same Postgres, so schedules survive a
restart (they will not survive it with the default in-memory store, and your demo will
restart). Jobs are keyed by `recovery_actions.id`. Misfire grace time 15 min
**[CONSTANT]**; a job that misfires beyond that is marked `SKIPPED` with a reason and the
case returns to `DECIDED` for reassessment — never silently executed late.

## 9.3 Messages are rendered, not sent

No SMS/email provider integration. `SEND_REMINDER` writes a fully rendered message to
`outbound_messages` and the dashboard displays it exactly as the customer would receive
it. This is honest, costs nothing, avoids DLT/DND entirely, and demos identically.
Say so out loud in the demo — claiming a send you didn't do is the kind of thing that
loses the room.

## 9.4 Idempotency

`idempotency_key = sha256(f"{case_id}:{action_type}:{charge_attempts_used}:{scheduled_for.isoformat()}")`

Stored with a `UNIQUE` constraint on `recovery_actions.idempotency_key`. Insert the row
**before** the outbound call, inside a transaction; the unique violation is your guard,
not an in-memory set. Also pass the key to the gateway where the API supports one
**[ASSUMPTION A7 — check which Razorpay endpoints accept an idempotency header]**.

## 9.5 Execution sequence — re-validate, then act

`SCHEDULED` does not mean `EXECUTE`. It means `RECHECK → AUTHORIZE → EXECUTE → VERIFY`.

```
1. Load fresh case + world state.
2. Re-run the policy engine in full. Anything can have changed in six hours:
   the customer paid, the mandate was revoked, the bank went down, consent
   was withdrawn, the order expired.
3. If verdict != ALLOW → mark action SKIPPED with reason, transition case to
   DECIDED, and re-decide. Log an audit event. Do not execute.
4. Insert action row with idempotency key (unique constraint = the real lock).
5. Execute via GatewayAdapter.
6. VERIFY by reading state back from the gateway. An HTTP 200 is not an outcome.
   Poll up to N times [CONSTANT: 5] with backoff before declaring UNKNOWN.
7. Double-charge check: if the order was already PAID at step 2 but a charge
   landed anyway (race), initiate refund via compensate() and log it loudly.
8. Persist outcome, update budgets, transition state.
```

Step 2 is the single most important block of code in the project and the easiest to
skip. It is also the most demoable: show a scheduled retry being *cancelled* because the
customer paid in the meantime.

---

# 10. The LLM layer

## 10.1 Where the LLM is allowed

Exactly three jobs:

1. **Ambiguous failure classification** — only when the deterministic mapping returns
   `UNKNOWN`.
2. **Action recommendation** — proposes an action + delay from the *already filtered*
   list of actions the rule engine deemed eligible.
3. **Customer message drafting** — fills a template's variable slots. It does not choose
   the template and cannot introduce new claims about the payment.

Everywhere else it is banned: state transitions, policy, budgets, idempotency,
scheduling arithmetic, amount handling.

## 10.2 Contract

Input: a JSON `input_snapshot` — the exact object is persisted in `recovery_decisions`,
so the decision is replayable. Output validated by Pydantic:

```python
class LLMDecision(BaseModel):
    action: ActionType
    delay_minutes: int = Field(ge=0, le=10080)
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=4)
    rationale: str = Field(max_length=400)
```

`ActionType` and `ReasonCode` are closed enums. Free-text `rationale` is for the UI and
the audit log only; **nothing downstream ever parses it**.

## 10.3 Hard requirements

- `temperature=0`, fixed model string pinned in config.
- Timeout **[CONSTANT: 8s]**; 1 retry; then fall back to the rule engine and record
  `source=RULE, reason_codes=["LLM_UNAVAILABLE"]`.
- Schema-invalid output → one repair attempt with the validation error appended → then
  fall back. Count both in `llm_failure_rate`.
- **Action not in the eligible set → reject and fall back.** The LLM can only pick from
  what the rules already permit. It narrows; it never widens.
- **Response cache**, keyed by `sha256(model + prompt_version + canonical_json(input))`,
  stored in a local sqlite file. Without this, a 2,000-case eval sweep is unaffordable and
  non-reproducible. With it, re-runs are free and deterministic.
- Prompt lives in `agent/prompts/vN.txt`, version pinned in config, version recorded on
  every decision row.

## 10.4 What the LLM must actually be good for

If the LLM's only behaviour is reproducing the rule table, delete it and say so — that
is a finding, not a failure, and stating it will impress the judges more than a fake
uplift. Design the scenarios so there is genuine headroom for judgement:

- conflicting signals (strong customer history + high amount + second failure),
- failure categories deliberately left out of the rule table,
- free-text merchant notes / customer support snippets in the snapshot that the rule
  engine cannot read but that change the right answer,
- cases where waiting longer beats acting now.

The rule engine cannot use unstructured context. That is the LLM's actual edge — engineer
the dataset so that edge exists and then *measure* it.

## 10.5 Confidence must be earned

If you display a confidence number, you must show its **calibration**: bucket decisions
by predicted confidence, plot realized success rate per bucket, report Brier score and a
reliability curve in the eval report. If it turns out uncalibrated, either apply a
monotonic recalibration on a held-out split or remove the number from the UI. Do not ship
a 92% badge that means nothing.

---

# 11. Evaluation — the part that wins or loses this track

The track brief asks for *measured money recovered across a batch*. This section is
non-negotiable and is built in Phase 3, before the LLM exists.

## 11.1 The circularity fix

Three artefacts that must stay strictly separate:

| Artefact | Owns | May the decision policy see it? |
|---|---|---|
| **Scenario generator** | case features, customer history, failure category, unstructured notes | yes (that's the input) |
| **Outcome model** | `P(success \| action, delay, failure_category, customer_segment, hidden_state)` | **NO — never** |
| **Ground-truth labels** | true failure category (for classification metrics only) | no |

The outcome model lives in `sim/outcome_model.py` and is imported **only** by
`SimulatedGateway`. Add a test (T-12) that fails if anything under `backend/` imports it.

**Critical:** there is no `optimal_action` label. The old plan's `ground_truth =
retry_later` is exactly the circularity — the rule engine would be graded against the
rules. Action quality is measured by **realized outcome under the hidden model**, not by
agreement with a label. Classification accuracy uses labels; decision quality does not.

## 11.2 Arms

| Arm | Description |
|---|---|
| `control` | do nothing — measures organic recovery. **Mandatory.** |
| `naive` | fixed policy: retry/remind at +1h, +24h, +72h regardless of anything |
| `rules` | deterministic engine + policy gate |
| `rules_llm` | rules generate eligible set, LLM chooses, policy gates |
| `oracle` | has read access to the outcome model — the achievable ceiling |

Report all five. `oracle` is what makes the numbers legible: "naive 18%, rules 27%,
+LLM 31%, ceiling 39%" tells a story that a bare 31% does not. `control` is what makes
them honest.

## 11.3 Splits

Scenario **configurations** (not just instances) are split 60/20/20 into
train / dev / test with a fixed seed. You tune rules and prompts on train+dev. The final
report uses **test only**, run once. Record the seed and the config hash in the report.
Deliberately include in test a few configurations with failure categories or
signal combinations absent from train — the rule engine will do badly on them and if the
LLM does better, that is your real finding.

## 11.4 Attribution — what counts as "recovered"

A case is `RECOVERED` only if a successful payment for that order/subscription lands
**within the attribution window [CONSTANT: 72h] of an executed action**, and the case was
not already paid at decision time.

Because customers pay on their own, the headline metric is **incremental** lift:

```
incremental_recovery_rate = rate(treatment) − rate(control)
incremental_revenue_paise = Σ recovered(treatment) − (Σ recovered(control) scaled to n)
```

Report a bootstrap 95% confidence interval on the difference **[CONSTANT: 1,000
resamples]**. If the interval crosses zero, say so. A team that reports "+4.1pp,
CI [−0.3, +8.4], not yet significant at n=500" outranks a team that reports "+13.4%" with
no interval, in front of anyone numerate.

## 11.5 Metrics to report

**Money**: gross recovered, incremental recovered (vs control), recovery rate, revenue
per case, cost per recovered rupee (using `config/costs.yaml` per-action costs).

**Behaviour**: actions per case, contacts per recovered case, wasted actions (executed on
cases that would have recovered anyway — estimable from control), stop-rate (cases
correctly terminated), mean time to recovery.

**Correctness**: classification precision/recall/F1 per failure category, macro-F1,
confusion matrix, `UNKNOWN` rate.

**Safety**: policy violations (must be **0** — any non-zero is a bug, not a metric),
denied-action counts by rule, human-escalation rate, double-charge incidents (must be 0),
messages outside the communication window (must be 0).

**LLM**: schema-failure rate, fallback rate, mean latency, cache hit rate, Brier score,
reliability curve, and **agreement rate with the rule engine** (if ~100%, the LLM is
decorative and you should say so).

## 11.6 Output

`python -m eval.run --arms all --split test --seed 42` writes:
- `eval/reports/<timestamp>/report.md` — tables + findings
- `eval/reports/<timestamp>/metrics.json` — machine readable
- `eval/reports/<timestamp>/*.png` — reliability curve, recovery-by-category bars,
  cumulative recovered revenue over time
- and prints a compact summary table to stdout

The dashboard's evaluation page reads `metrics.json`. It does **not** recompute anything.

---

# 12. Configuration

```
config/
├── policy.yaml       # all policy constants, versioned, hash logged per evaluation
├── costs.yaml        # per-action cost in paise (for the cost metric)
├── templates.yaml    # message templates + dlt_registered flags
├── taxonomy.yaml     # razorpay error code → internal failure category
└── sim/
    ├── outcome_model.yaml   # hidden probabilities — NEVER imported by backend/
    └── scenarios.yaml       # scenario configuration space
```

`.env` holds only secrets: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, `DATABASE_URL`. `.env.example` ships with
every key present and every value blank. Secrets are never logged; add a log filter that
redacts anything matching the key patterns.

---

# 13. Phase plan

Written as D-7 → D-0. Each phase has a hard acceptance test. **Do not proceed on red.**

## Phase 0 — Foundations (D-7, first half)
- Repo skeleton (§16), `docker-compose` with `api` + `db`, Alembic, `pytest`, ruff, mypy.
- `domain/enums.py`, `domain/state_machine.py`, full Alembic migration for §7.2.
- `docs/razorpay-verified.md` created; a human reads the Razorpay docs and fills in:
  webhook signature header + algorithm, the failed-payment error object fields, order
  statuses, subscription/mandate charge endpoint, payment-link create endpoint,
  idempotency support. **This is a blocking human task — do it on day one.**
- **Accept:** `alembic upgrade head` on a clean DB; T-03 (state machine matrix) green.

## Phase 1 — Simulator + scenario generator (D-7, second half → D-6)
Built **before** the app, deliberately.
- `sim/scenarios.py` — generates cases across the configuration space with a seed.
- `sim/outcome_model.py` — hidden probabilities; the only thing that decides success.
- `sim/gateway.py` — `SimulatedGateway` implementing `GatewayAdapter`, including
  injectable bank-outage windows and customers-who-pay-organically.
- `eval/dataset.py` — deterministic train/dev/test split by configuration.
- **Accept:** generate 1,000 cases twice with the same seed → byte-identical; T-12
  (import isolation) green; distribution summary printed.

## Phase 2 — Core pipeline, no AI (D-6 → D-5)
- Ingestion (webhook + order sweeper), dedupe, normalization, taxonomy mapping.
- Case orchestrator, rule engine, policy engine, action registry, scheduler,
  execute → verify loop, audit log.
- Runs end-to-end against `SimulatedGateway`.
- **Accept:** `naive` and `rules` arms both run 500 cases to terminal states with zero
  illegal transitions and zero policy violations.

## Phase 3 — Evaluation harness (D-5 → D-4)
- Arms, metrics, bootstrap CI, control holdout, report generation.
- **Accept:** `eval/run.py` produces `report.md` + `metrics.json` for
  `control | naive | rules | oracle` on the test split. **You now have a defensible
  submission even if everything after this fails.** Tag this commit.

## Phase 4 — LLM layer (D-4 → D-3)
- Advisor, Pydantic contract, eligible-set constraint, fallback, cache, prompt v1.
- Add the `rules_llm` arm; run the full comparison.
- **Accept:** `rules_llm` runs the full test split with 0 policy violations and
  0 schema failures reaching execution; agreement-rate with rules reported.
- **Decision gate:** if `rules_llm` shows no improvement over `rules`, do **not** hide it.
  Either improve the scenarios so judgement matters (§10.4) or keep the finding and
  present it. A negative result honestly reported beats a fabricated positive.

## Phase 5 — Real Razorpay path (D-3)
- `RazorpayAdapter`, live webhook endpoint with signature verification, test-mode
  payment-link creation, order sweeper against the real orders list.
- **Accept:** one real test-mode failure ingested end-to-end to a terminal state, with a
  real payment link created; signature verification unit-tested with a known-good and a
  tampered payload.

## Phase 6 — Dashboard (D-3 → D-2)
Pages: Overview · Cases · **Case timeline** · Approval queue · Policy view · Evaluation.
The case timeline is the most important screen in the product — it is the audit trail the
brief asks for. Every row: timestamp, actor, what was proposed, what policy said and why,
what executed, what the gateway returned.
- **Accept:** a judge can open one case and read the entire life of it without asking a
  question.

## Phase 7 — Calibration, hardening, polish (D-2 → D-1)
- Confidence calibration or removal (§10.5).
- Double-charge race test, restart-survival test, secret redaction, README, seed data,
  one-command demo reset (`make demo-reset`).

## Phase 8 — Demo + submission (D-1 → D-0)
- Rehearse §15 end to end at least three times. Record a backup video.
- Freeze the code the night before. Fix nothing on demo day.

**If you run short:** cut Phase 8's polish, then Phase 7, then Phase 6 down to the case
timeline alone. Never cut Phase 3.

---

# 14. Test matrix

| id | Level | Asserts |
|---|---|---|
| T-01 | unit | Every Razorpay error code in `taxonomy.yaml` maps to a valid category; unmapped → `UNKNOWN` |
| T-02 | unit | Webhook signature: known-good passes, tampered body fails, re-serialized body still passes only if raw bytes used |
| T-03 | unit | Full state-transition matrix: every legal transition allowed, every illegal one raises |
| T-04 | unit | Policy: each of P01–P15 fires in isolation with a crafted case |
| T-05 | unit | Contact budget exhausted → DENY; charge budget exhausted → DENY |
| T-06 | unit | Communication window: 21:30 IST → DOWNGRADE to reschedule at 09:00 |
| T-07 | unit | `RETRY_MANDATE_CHARGE` on a class-B case → DENY (the #1 correctness bug) |
| T-08 | unit | Money never crosses a boundary as a float |
| T-09 | integration | Duplicate webhook (same event id) → exactly one case |
| T-10 | integration | Scheduled action re-validated: order paid in the interim → SKIPPED, not executed |
| T-11 | integration | Double-charge race → refund path invoked, incident logged |
| T-12 | architecture | Nothing under `backend/` imports `sim.outcome_model` |
| T-13 | integration | LLM returns an ineligible action → rejected, rule fallback used, recorded |
| T-14 | integration | LLM returns malformed JSON twice → fallback, `llm_failure_rate` incremented |
| T-15 | integration | Scheduler restart: pending jobs survive a process restart |
| T-16 | scenario | Bank outage window: `rules` defers, `naive` burns its budget; asserted in metrics |
| T-17 | scenario | Opted-out customer: zero outbound messages, case → STOPPED |
| T-18 | scenario | Amount above ceiling → AWAITING_APPROVAL, nothing executes without approval |
| T-19 | eval | Same seed → identical `metrics.json` (bit-for-bit reproducibility) |
| T-20 | eval | Policy-violation count is 0 across every arm |

T-07, T-10, T-12 and T-20 are the four that actually protect the submission.

---

# 15. Demo script (7 minutes)

Two cases, because one case cannot show both halves of the product.

**0:00 — Frame the problem in one sentence, with the money number from your own eval.**
No slides about what AI is.

**0:30 — Case 1, class B (one-off failure).** Trigger a real test-mode failed payment.
Show: webhook lands → case opens → classified `INSUFFICIENT_FUNDS` → recoverability
`RECOVERABLE_ASSISTED` → **explicitly state that we cannot re-charge this customer, so
retry is not on the table** (this one sentence separates you from every other team) →
system creates a payment link + drafts a reminder → policy panel shows the window check
and the contact budget → rendered message shown as the customer would see it.

**2:00 — Case 2, class A (mandate).** Show a real retry being scheduled with a delay, the
policy gate approving it, and then — the beat that matters — **the customer pays manually
before the retry fires**. Show the re-validation step cancelling the scheduled charge and
the audit log recording why. "The system knows when not to act."

**3:30 — Bank outage.** Flip the simulated outage on. Show the naive arm retrying into a
dead rail while yours defers, side by side.

**4:15 — Escalation.** A high-value case landing in the approval queue. Approve it live.

**5:00 — The numbers.** One screen: control / naive / rules / rules+LLM / oracle, with
incremental lift and confidence interval, n, and the seed. Say the sample size and the
interval out loud. State plainly what the LLM did and did not add.

**6:15 — What is real and what is modelled.** Test-mode APIs are real. Messages are
rendered, not sent. Regulatory retry caps are implemented but disabled pending
verification. Outcome model is ours and its parameters are in the repo.

**6:45 — One line on the production path.** Stop.

The single strongest moment available to you is the cancelled retry. Rehearse it until it
cannot fail.

---

# 16. Repository structure

```
revenue-recovery/
├── backend/
│   ├── api/            main.py webhooks.py cases.py approvals.py eval_report.py
│   ├── domain/         enums.py state_machine.py failure_taxonomy.py
│   │                   recoverability.py models.py
│   ├── ingestion/      webhook_handler.py order_sweeper.py normalizer.py
│   ├── decisioning/    rule_engine.py orchestrator.py features.py
│   ├── policy/         engine.py rules.py config_loader.py
│   ├── agent/          advisor.py schemas.py cache.py prompts/v1.txt
│   ├── actions/        base.py registry.py retry_mandate.py payment_link.py
│   │                   reminder.py alternate_method.py escalate.py
│   ├── gateway/        base.py razorpay_adapter.py
│   ├── scheduler/      jobs.py runner.py
│   ├── db/             models.py session.py repositories.py
│   └── observability/  audit.py logging.py metrics.py
├── sim/                gateway.py outcome_model.py scenarios.py customers.py
├── eval/               run.py arms.py dataset.py metrics.py stats.py report.py
│                       reports/
├── config/             policy.yaml costs.yaml templates.yaml taxonomy.yaml sim/
├── frontend/           React + Vite
├── tests/              unit/ integration/ scenario/ architecture/
├── docs/               razorpay-verified.md ARCHITECTURE.md DEMO.md
├── alembic/
├── docker-compose.yml  Makefile  README.md  .env.example
├── OPEN_QUESTIONS.md   PROGRESS.md
└── SPEC.md             ← this file
```

`sim/` sits **outside** `backend/` for a reason: it is the environment, not the system.
T-12 enforces it.

---

# 17. Open questions — resolve before the corresponding rule goes live

Each must be answered by reading official documentation and recorded in
`docs/razorpay-verified.md` with the source URL and date. Until answered, the dependent
code path stays behind a disabled flag.

| id | Question | Blocks |
|---|---|---|
| A1 | What exactly is required to charge a customer again without their live participation — subscription, e-mandate, tokenized card with recurring consent? Which endpoint? | §5.1, all class-A retry code |
| A2 | Is there a regulatory or NPCI cap on retry attempts for a failed auto-debit / UPI Autopay mandate, and over what window? | P14 |
| A3 | Pre-debit notification requirement for e-mandate/Autopay: required? how many hours before? who sends it? | P15 |
| A4 | Exact order status values and the list-orders filter needed to detect abandonment | §6.2 order sweeper |
| A5 | Consent basis for transactional email/SMS tied to an existing failed order | P03, §8.5 |
| A6 | DLT template registration + DND scrubbing obligations for this message class | §8.5 |
| A7 | Which Razorpay endpoints accept an idempotency key, and under what header | §9.4 |
| A8 | Webhook signature header name, algorithm, and whether the raw body is the signed payload | §6.3 |
| A9 | Payment-link creation params: expiry, partial payment, notification suppression, reference id | `CREATE_PAYMENT_LINK` |
| A10 | Test-mode: which failure types can actually be produced, and how | Phase 5 |

Answering A1 and A2 changes the product. Answer them first.

---

# 18. Final instruction to the implementing agent

Build in the order given. Do not skip Phase 3 to get to the LLM sooner — the evaluation
harness *is* the submission; the agent is a component inside it. If you find yourself
about to write a Razorpay field name you have not read in the docs, stop and add it to
`OPEN_QUESTIONS.md` instead.

And if the LLM arm turns out not to beat the rules arm: report that. The brief asks for
measured money recovered and an honest exception list. It never asks you to prove the AI
helped.
