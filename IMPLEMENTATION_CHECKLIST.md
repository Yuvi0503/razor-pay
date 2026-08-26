# Revenue Recovery — Ordered Implementation Checklist

Last updated: 2026-08-26  
Authoritative requirements: `Track03_Revenue_Recovery_BUILD_SPEC_v2.md`

Status legend: `[x]` built and locally verified · `[-]` partially built · `[ ]` not started · `[!]` blocked pending verification or an owner decision.

## 0. Your actions — required before live Razorpay work

Complete these in order. Do **not** provide secrets in source control.

- [ ] Create a Razorpay Test Mode account/project and create Test Mode API keys.
- [ ] Configure a Test Mode webhook pointing to a reachable HTTPS endpoint for `POST /webhooks/razorpay`.
- [ ] Put the Test Mode values in a local `.env` copied from `.env.example`:
  - `RAZORPAY_KEY_ID`
  - `RAZORPAY_KEY_SECRET`
  - `RAZORPAY_WEBHOOK_SECRET`
  - `DATABASE_URL`
- [ ] Confirm whether you want an Anthropic-backed LLM advisor. If yes, add `ANTHROPIC_API_KEY`; if not, we keep a deterministic-only product.
- [ ] Verify and approve the official Razorpay/legal answers below, then record each source URL and checked date in `docs/razorpay-verified.md`:
  - [!] A1 — allowed mechanism and endpoint for a merchant-triggered retry of a mandate/subscription charge.
  - [!] A2 — retry caps for failed auto-debit / UPI Autopay mandates.
  - [!] A3 — pre-debit notification requirements and lead time.
  - [!] A4 — order status values and list-orders filtering needed for abandonment sweeping.
  - [!] A5 — consent basis for transactional outreach after a failed order.
  - [!] A6 — DLT registration and DND scrubbing obligations.
  - [!] A7 — supported idempotency behavior/header by endpoint.
  - [x] A8 — webhook header, raw-body requirement, and HMAC-SHA256 are documented.
  - [x] A9 — payment-link create fields are documented; decide the application-specific expiry and notification settings.
  - [ ] A10 — Test Mode failure flows to use in the live demo.
- [ ] Decide the merchant’s approved contact channels and provide compliant email/SMS templates; rendered messages must include opt-out language.
- [ ] Choose whether approval-queue actions will be performed manually in the UI or through a restricted internal API.

## 1. Foundation and project setup

- [x] Create Python project metadata, Docker Compose skeleton, `.env.example`, and local development documentation.
- [x] Add isolated virtual-environment instructions and a `.gitignore`.
- [x] Add FastAPI application with health endpoint and CORS configuration.
- [x] Add React/Vite dashboard scaffold and production build configuration.
- [x] Add pytest and Ruff configuration; current suite passes.
- [ ] Add Alembic configuration and an initial migration.
- [ ] Add SQLAlchemy models for every table in §7.2: merchants, customers, consent, orders, subscriptions, attempts, cases, decisions, policy evaluations, actions, approvals, messages, audit events, and raw events.
- [ ] Enforce Postgres native enums, paise-only money columns, timestamps, uniqueness constraints, append-only tables, and one-open-case-per-order semantics.
- [ ] Add database session lifecycle, repositories, transaction boundaries, and a clean-database migration check.
- [ ] Add log filtering that redacts every declared secret pattern.
- [ ] Create `ARCHITECTURE.md`, `DEMO.md`, and an updated `PROGRESS.md` including actual commit SHAs.

## 2. Domain correctness and deterministic rules

- [x] Define case classes, failure categories, recoverability, actions, consent, policy verdicts, and canonical case states.
- [x] Implement the single state-transition map and illegal-transition exception.
- [x] Implement failure taxonomy lookup with safe `UNKNOWN` fallback.
- [x] Implement deterministic recoverability classification.
- [x] Implement action registry with class allowlists, reversibility, and budget-consumption metadata.
- [x] Implement a pure policy engine with P01/P02/P03/P04/P05/P06/P07/P08/P09/P10/P12/P13 and disabled-safe P14/P15 placeholders.
- [ ] Persist policy configuration hash with every policy evaluation.
- [ ] Compute and persist the per-customer rolling seven-day contact budget.
- [ ] Implement the SQL-derived rail outage signal from real `payment_attempts` data.
- [ ] Implement P14/P15 only after A2/A3 are verified; keep them disabled otherwise and write the `NotVerified` audit entry.
- [ ] Implement eligible-action rule generation separately from the final policy gate.
- [ ] Add auditable rule results and human-readable policy explanations to persistent case timelines.

## 3. Simulator and scenario data

- [x] Build deterministic scenario generation with a seed and class-A/class-B cases.
- [x] Build a hidden outcome model used only by simulator/evaluation code.
- [x] Build a basic simulated gateway and deterministic configuration split.
- [x] Enforce architecture isolation: `backend/` cannot import `sim.outcome_model`.
- [ ] Move scenario parameters and hidden outcome probabilities into `config/sim/scenarios.yaml` and `config/sim/outcome_model.yaml`.
- [ ] Add class-C abandonment scenarios.
- [ ] Add method/issuer rail features, realistic failure histories, customer segments, support notes, and payment timing.
- [ ] Add injectable bank-outage windows and explicitly organic-paying customers.
- [ ] Add byte-identical 1,000-case generator acceptance test and distribution report.
- [ ] Implement full `GatewayAdapter` snapshots and action calls for the simulator.

## 4. Core pipeline, persistence, and execution

- [x] Implement raw-body Razorpay HMAC-SHA256 verification and event-ID duplicate behavior at the API boundary.
- [ ] Persist raw events with unique provider-event IDs; return HTTP 200 after dedupe insert and move processing off the request path.
- [ ] Normalize verified webhook payloads into orders, subscriptions, payment attempts, and cases.
- [ ] Add exact verified Razorpay error-code mapping to `config/taxonomy.yaml`.
- [ ] Implement case orchestrator: open → classify → decide → policy-evaluate → schedule.
- [ ] Add APScheduler using `SQLAlchemyJobStore`; configure jobs by recovery-action ID and 15-minute misfire handling.
- [ ] Implement action records, durable SHA-256 idempotency keys, and pre-outbound transaction insertion.
- [ ] Implement revalidation immediately before every action: freshness, payment state, mandate state, consent, budgets, outage, and policy gate.
- [ ] Implement state read-back verification rather than trusting an HTTP 200 response.
- [ ] Implement reassessment, exhaustion, stop, expiry, and recovery resolution flows.
- [ ] Implement `CREATE_PAYMENT_LINK` through the verified Razorpay Test Mode adapter.
- [ ] Implement local-only rendered message records for reminders/alternate-method guidance; do not send SMS or email.
- [ ] Implement payment-link expiration as compensation.
- [ ] Implement duplicate-charge detection, refund compensation path, and an explicit incident audit event after A1/A7 verification.
- [ ] Implement the class-C order sweeper only after A4 verification.

## 5. Evaluation harness

- [x] Run the five named evaluation arms: control, naive, rules, rules+LLM placeholder, and oracle.
- [x] Generate Markdown and JSON reports from a fixed seed.
- [ ] Implement the naive schedule exactly as configured (+1h, +24h, +72h) instead of a single simplified action.
- [ ] Drive every arm through the same persisted orchestration pipeline, not direct simulator calls.
- [ ] Implement actual treatment/control attribution windows and newly successful payment matching.
- [ ] Implement bootstrap 95% confidence intervals with 1,000 resamples.
- [ ] Report money, behavior, classification, safety, and LLM metrics required by §11.5.
- [ ] Generate reliability curve, recovery-by-category, and cumulative-revenue PNG charts.
- [ ] Include scenario/config hashes, seed, split, policy hash, and cost configuration in each report.
- [ ] Add reproducibility test: same seed produces bit-identical `metrics.json`.
- [ ] Display stored metrics JSON in the dashboard; never recompute metrics inside the UI.

## 6. LLM advisor — only after evaluation is reliable

- [ ] Decide and pin model/provider and add its key only to local `.env`.
- [ ] Create versioned prompt file and Pydantic `LLMDecision` contract.
- [ ] Send ambiguous taxonomy cases to the LLM classifier only when deterministic mapping returns `UNKNOWN`.
- [ ] Restrict LLM action choice to a deterministic eligible-action set.
- [ ] Implement temperature 0, 8-second timeout, one retry, one schema-repair attempt, and rule fallback.
- [ ] Persist input snapshot, prompt version, model, raw response, latency, fallback reason, and cache key.
- [ ] Add local SQLite response cache keyed by model, prompt version, and canonicalized input.
- [ ] Implement templated message drafting only; prevent new payment claims or template selection by the LLM.
- [ ] Add LLM ineligible-action and malformed-output integration tests.
- [ ] Measure agreement, failure/fallback/cache rates, Brier score, and calibration; remove UI confidence if uncalibrated.

## 7. Dashboard and demo experience

- [x] Build and compile an initial dashboard visual shell.
- [ ] Replace sample dashboard rows with API-backed data.
- [ ] Build Overview page: at-risk money, incremental recovery, safety invariants, recent activity.
- [ ] Build Cases page: filtering, class/category/state/action details, and safe currency formatting.
- [ ] Build Case Timeline: every ingest, classification, proposal, policy result, scheduled action, verification, and audit event in order.
- [ ] Build Approval Queue: high-value cases, explicit approve/reject action, rationale, and no execution before approval.
- [ ] Build Policy View: active values, policy config hash, disabled regulatory rules, and fired-rule summaries.
- [ ] Build Evaluation page from persisted `metrics.json`, including control comparison and confidence interval.
- [ ] Build rendered-message preview and clearly label it “not sent”.
- [ ] Add visible labels distinguishing Test Mode, simulated outcomes, real gateway calls, and modelled compliance controls.

## 8. Tests and acceptance gates

- [x] T-03 partial: legal state transition and terminal-state rejection tests.
- [x] T-07: mandate retry on a class-B one-off case is denied.
- [x] T-12: backend cannot import hidden outcome model.
- [x] Raw webhook signature unit behavior: valid raw payload passes and tampered bytes fail.
- [ ] T-01: validate every verified taxonomy entry and `UNKNOWN` fallback.
- [ ] T-02: FastAPI integration test proving raw-body handling and re-serialization behavior.
- [ ] T-03 full matrix: every legal and illegal transition pair.
- [ ] T-04: isolated tests for all P01–P15.
- [ ] T-05/T-06: contact/charge budget and IST-window downgrade tests.
- [ ] T-08: reject float money across API, domain, and persistence boundaries.
- [ ] T-09: duplicate webhook produces exactly one stored case.
- [ ] T-10: paid-between-schedule-and-execution action is skipped.
- [ ] T-11: duplicate-charge refund path is invoked and logged.
- [ ] T-13/T-14: LLM invalid-action and malformed-JSON fallbacks.
- [ ] T-15: scheduler job survives restart.
- [ ] T-16/T-17/T-18: outage deferral, opt-out stop, high-value approval scenarios.
- [ ] T-19/T-20: bit-for-bit reproducibility and zero policy violations across all arms.
- [ ] Run `alembic upgrade head`, full pytest suite, Ruff, mypy, backend API checks, and frontend production build before each demo freeze.

## 9. Final demo readiness

- [ ] Seed the two scripted demo cases: class-B failed one-off payment and class-A mandate failure.
- [ ] Rehearse a scheduled mandate retry being cancelled because a manual payment arrived first.
- [ ] Rehearse simulated bank outage: naive burns budget while rules defer.
- [ ] Rehearse high-value approval flow.
- [ ] Generate the final evaluation report once on the held-out test split; record sample size, seed, interval, and limitations.
- [ ] Prepare the “real vs modelled” disclosure: Test Mode APIs real; messages rendered; outcome model simulated; regulatory policy disabled until verified.
- [ ] Record backup demo video and freeze the release before demo day.

## Current verification snapshot

- [x] Backend tests: `7 passed`.
- [x] Backend lint: `ruff check backend sim eval tests` passes.
- [x] Frontend: `npm run build` passes from `frontend/`.
- [x] Evaluation command runs: `python -m eval.run --arms all --split test --seed 42`.
- [!] Current evaluation figures are simulator outputs only; they are **not** production recovery claims and must never be presented as real Razorpay results.
