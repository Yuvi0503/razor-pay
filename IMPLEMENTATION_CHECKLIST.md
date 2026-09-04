# Revenue Recovery — Ordered Implementation Checklist

Last updated: 2026-08-26  
Authoritative requirements: `Track03_Revenue_Recovery_BUILD_SPEC_v2.md`

Status legend: `[x]` built and locally verified · `[-]` partially built · `[ ]` not started · `[!]` blocked pending verification or an owner decision.

Current execution checkpoint: Phase 1 is complete through point 54. The product mode is
deterministic-only; the optional Anthropic advisor is not part of the active product scope and
must remain disabled unless this decision is explicitly revisited.

## 0. Your actions — required before live Razorpay work

Complete these in order. Do **not** provide secrets in source control.

- [x] Create a Razorpay Test Mode account/project and create Test Mode API keys.
- [x] Configure a Test Mode webhook pointing to a reachable HTTPS endpoint for `POST /webhooks/razorpay`.
- [x] Put the Test Mode values in a local `.env` copied from `.env.example`:
  - `RAZORPAY_KEY_ID`
  - `RAZORPAY_KEY_SECRET`
  - `RAZORPAY_WEBHOOK_SECRET`
  - `DATABASE_URL`
- [x] Product mode decision: deterministic-only. Do not configure or require `ANTHROPIC_API_KEY` for the active product.
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
- [x] Decide the merchant’s approved contact channels and provide compliant email/SMS templates; rendered messages must include opt-out language.
- [x] Choose whether approval-queue actions will be performed manually in the UI or through a restricted internal API.

## 1. Foundation and project setup

- [x] Create Python project metadata, Docker Compose skeleton, `.env.example`, and local development documentation.
- [x] Add isolated virtual-environment instructions and a `.gitignore`.
- [x] Add FastAPI application with health endpoint and CORS configuration.
- [x] Add React/Vite dashboard scaffold and production build configuration.
- [x] Add pytest and Ruff configuration; current suite passes.
- [x] Add Alembic configuration and an initial migration.
- [x] Add SQLAlchemy models for every table in §7.2: merchants, customers, consent, orders, subscriptions, attempts, cases, decisions, policy evaluations, actions, approvals, messages, audit events, and raw events.
- [x] Enforce Postgres native enums, paise-only money columns, timestamps, uniqueness constraints, append-only tables, and one-open-case-per-order semantics.
- [x] Add database session lifecycle, repositories, transaction boundaries, and a clean-database migration check.
- [x] Add log filtering that redacts every declared secret pattern.
- [x] Create `ARCHITECTURE.md`, `DEMO.md`, and an updated `PROGRESS.md` including actual commit SHAs.

## 2. Domain correctness and deterministic rules

- [x] Define case classes, failure categories, recoverability, actions, consent, policy verdicts, and canonical case states.
- [x] Implement the single state-transition map and illegal-transition exception.
- [x] Implement failure taxonomy lookup with safe `UNKNOWN` fallback.
- [x] Implement deterministic recoverability classification.
- [x] Implement action registry with class allowlists, reversibility, and budget-consumption metadata.
- [x] Implement a pure policy engine with P01/P02/P03/P04/P05/P06/P07/P08/P09/P10/P12/P13 and disabled-safe P14/P15 placeholders.
- [x] Persist policy configuration hash with every policy evaluation.
- [x] Compute and persist the per-customer rolling seven-day contact budget.
- [x] Implement the SQL-derived rail outage signal from real `payment_attempts` data.
- [x] Implement P14/P15 only after A2/A3 are verified; keep them disabled otherwise and write the `NotVerified` audit entry.
- [x] Implement eligible-action rule generation separately from the final policy gate.
- [x] Add auditable rule results and human-readable policy explanations to persistent case timelines.

## 3. Simulator and scenario data

- [x] Build deterministic scenario generation with a seed and class-A/class-B cases.
- [x] Build a hidden outcome model used only by simulator/evaluation code.
- [x] Build a basic simulated gateway and deterministic configuration split.
- [x] Enforce architecture isolation: `backend/` cannot import `sim.outcome_model`.
- [x] Move scenario parameters and hidden outcome probabilities into `config/sim/scenarios.yaml` and `config/sim/outcome_model.yaml`.
- [x] Add class-C abandonment scenarios.
- [x] Add method/issuer rail features, realistic failure histories, customer segments, support notes, and payment timing.
- [x] Add injectable bank-outage windows and explicitly organic-paying customers.
- [ ] Add byte-identical 1,000-case generator acceptance test and distribution report.
- [x] Implement full `GatewayAdapter` snapshots and action calls for the simulator.

## 4. Core pipeline, persistence, and execution

- [x] Implement raw-body Razorpay HMAC-SHA256 verification and event-ID duplicate behavior at the API boundary.
- [x] Persist raw events with unique provider-event IDs; return HTTP 200 after dedupe insert and move processing off the request path.
- [x] Normalize verified webhook payloads into orders, subscriptions, payment attempts, and cases.
- [ ] Add exact verified Razorpay error-code mapping to `config/taxonomy.yaml`.
- [x] Implement case orchestrator: open → classify → decide → policy-evaluate → schedule.
- [x] Add APScheduler using `SQLAlchemyJobStore`; configure jobs by recovery-action ID and 15-minute misfire handling.
- [x] Implement action records, durable SHA-256 idempotency keys, and pre-outbound transaction insertion.
- [x] Implement revalidation immediately before every action: freshness, payment state, mandate state, consent, budgets, outage, and policy gate.
- [x] Implement state read-back verification rather than trusting an HTTP 200 response.
- [x] Implement reassessment, exhaustion, stop, expiry, and recovery resolution flows.
- [x] Implement `CREATE_PAYMENT_LINK` through the verified Razorpay Test Mode adapter.
- [x] Implement local-only rendered message records for reminders/alternate-method guidance; do not send SMS or email.
- [x] Implement payment-link expiration as compensation.
- [x] Implement duplicate-charge detection, refund compensation path, and an explicit incident audit event after A1/A7 verification.
- [x] Implement the class-C order sweeper behind `RAZORPAY_ENABLE_ORDER_SWEEPER=false`; enable only after A4 Test Mode response verification.

## 5. Evaluation harness

- [x] Run the five named evaluation arms: control, naive, rules, rules+LLM placeholder, and oracle.
- [x] Generate Markdown and JSON reports from a fixed seed.
- [x] Implement the naive schedule exactly as configured (+1h, +24h, +72h) instead of a single simplified action.
- [x] Drive every arm through the same persisted orchestration pipeline, not direct simulator calls.
- [x] Implement actual treatment/control attribution windows and newly successful payment matching.
- [x] Implement bootstrap 95% confidence intervals with 1,000 resamples.
- [x] Report money, behavior, classification, safety, and LLM-status metrics required by §11.5; calibration metrics are explicitly unavailable in deterministic-only mode.
- [x] Generate reliability curve, recovery-by-category, and cumulative-revenue PNG charts.
- [x] Include scenario/config hashes, seed, split, policy hash, and cost configuration in each report.
- [x] Add reproducibility test: same seed produces bit-identical `metrics.json`.
- [ ] Display stored metrics JSON in the dashboard; never recompute metrics inside the UI.

## 6. LLM advisor — only after evaluation is reliable

- [x] Decide and pin model/provider and add its key only to local `.env`.
- [x] Create versioned prompt file and Pydantic `LLMDecision` contract.
- [x] Send ambiguous taxonomy cases to the LLM classifier only when deterministic mapping returns `UNKNOWN`.
- [x] Restrict LLM action choice to a deterministic eligible-action set.
- [x] Implement temperature 0, 8-second timeout, one retry, one schema-repair attempt, and rule fallback.
- [x] Persist input snapshot, prompt version, model, raw response, latency, fallback reason, and cache key.
- [x] Add local SQLite response cache keyed by model, prompt version, and canonicalized input.
- [x] Implement templated message drafting only; prevent new payment claims or template selection by the LLM.
- [x] Add LLM ineligible-action and malformed-output integration tests.
- [x] Measure agreement, failure/fallback/cache rates, Brier score, and calibration; remove UI confidence if uncalibrated.

## 7. Dashboard and demo experience

- [x] Build and compile an initial dashboard visual shell.
- [x] Replace sample dashboard rows with API-backed data.
- [x] Build Overview page: at-risk money, incremental recovery, safety invariants, recent activity.
- [x] Build Cases page: filtering, class/category/state/action details, and safe currency formatting.
- [x] Build Case Timeline: every ingest, classification, proposal, policy result, scheduled action, verification, and audit event in order.
- [x] Build Approval Queue: high-value cases, explicit approve/reject action, rationale, and no execution before approval.
- [x] Build Policy View: active values, policy config hash, disabled regulatory rules, and fired-rule summaries.
- [x] Build Evaluation page from persisted `metrics.json`, including control comparison and confidence interval.
- [x] Build rendered-message preview and clearly label it “not sent”.
- [x] Add visible labels distinguishing Test Mode, simulated outcomes, real gateway calls, and modelled compliance controls.

## 8. Tests and acceptance gates

- [x] T-03 partial: legal state transition and terminal-state rejection tests.
- [x] T-07: mandate retry on a class-B one-off case is denied.
- [x] T-12: backend cannot import hidden outcome model.
- [x] Raw webhook signature unit behavior: valid raw payload passes and tampered bytes fail.
- [x] T-01: validate every configured taxonomy entry and `UNKNOWN` fallback. No unverified Razorpay codes were added.
- [x] T-02: FastAPI integration test proving raw-body handling and re-serialization behavior.
- [x] T-03 full matrix: every legal and illegal transition pair.
- [x] T-04: isolated tests for all P01–P15.
- [x] T-05/T-06: contact/charge budget and IST-window downgrade tests.
- [x] T-08: reject float money across API, domain, and persistence boundaries.
- [x] T-09: duplicate webhook produces exactly one stored case.
- [x] T-10: paid-between-schedule-and-execution action is skipped.
- [x] T-11: duplicate-charge compensation path is invoked and logged.
- [x] T-13/T-14: LLM invalid-action and malformed-JSON fallbacks.
- [x] T-15: scheduler job survives restart.
- [x] T-16/T-17/T-18: outage deferral, opt-out stop, high-value approval scenarios.
- [x] T-19/T-20: bit-for-bit reproducibility and zero policy violations across all arms.
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

- [x] Backend tests: `74 passed, 1 skipped` (Docker/PostgreSQL integration is skipped only when Docker is unavailable to the test process).
- [x] Backend lint: `ruff check backend sim eval tests` passes.
- [x] Frontend: `npm run build` passes from `frontend/`.
- [x] Evaluation command runs: `python -m eval.run --arms all --split test --seed 42`.
- [!] Current evaluation figures are simulator outputs only; they are **not** production recovery claims and must never be presented as real Razorpay results.
