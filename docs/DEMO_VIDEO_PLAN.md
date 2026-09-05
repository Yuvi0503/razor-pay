# RecoverGuard Demo Video Plan

## Goal

Record a 5–8 minute end-to-end walkthrough that proves the system can accept a signed Razorpay Test Mode-shaped event, process it asynchronously, and expose an explainable recovery case in the dashboard.

## Before recording

- Start Docker Desktop.
- Create `.env` from `.env.example`; keep all secrets off-screen.
- Run `docker compose up -d --build`.
- Confirm `http://localhost:8000/health` returns `{"status":"ok"...}`.
- In a second terminal, run `cd frontend`, `npm install`, and `npm run dev`.
- Generate evaluation evidence with `python -m eval.run --arms all --split test --seed 42`.
- Open `http://localhost:5173` and keep the API/worker logs available in another terminal.
- Optional real-delivery setup: use a fresh HTTPS zrok URL and configure Razorpay Test Mode to post to `/webhooks/razorpay`.

## Shot list and narration

### 1. Product objective — 30 seconds

Show the RecoverGuard title and say: “RecoverGuard is a safety-first revenue recovery console. It distinguishes one-off failures from mandate-backed retries, applies deterministic policy controls, and leaves an audit trail for every decision.”

### 2. Architecture — 45 seconds

Show the terminal or a simple split view of the repository. Explain:

- PostgreSQL is the durable source of truth.
- The API verifies and stores the raw webhook quickly.
- The worker normalizes pending events out of band.
- The policy engine decides what is allowed; the dashboard displays persisted data.

Do not show `.env` contents.

### 3. Start-up proof — 30 seconds

Show `docker compose ps`, the health response, and the frontend loading at `localhost:5173`. Briefly show the Evaluation tab if the report was generated.

### 4. Webhook proof — 60 seconds

If using Razorpay Test Mode, show the webhook configuration with the secret obscured, then show the API log receiving a delivery. State that the real external interaction is Test Mode only. If no external account is available, use the signed fixture in `DEMO.md` and state that it is a shaped local event used to exercise the verified webhook boundary.

### 5. Recovery case — 90 seconds

Post one signed `payment.failed` fixture. Show the API response, then the worker log processing the pending event. Refresh the Overview. Point out the `₹1.00` at-risk metric and the single open `B_ONEOFF` case.

### 6. Explainability — 90 seconds

Open Cases, select the case, and scroll through the timeline. Call out ingest, classification, decision, policy evaluation, action scheduling, and rendered-message evidence. Then show the Policy tab and its configuration hash.

### 7. Evaluation and safety — 45 seconds

Open Evaluation and explain that the metrics are stored output, not recomputed by the browser. Show that policy violations remain zero. Mention that messages are rendered locally and not sent, and unsafe live mandate actions remain gated.

### 8. Duplicate safety check — 30 seconds

Replay the same provider event ID if convenient. Show that the API acknowledges it as a duplicate and that the dashboard still has one case, not two.

## Closing line

“The demo proves the durable, explainable recovery workflow. Razorpay delivery is real only in Test Mode; recovery outcomes, outbound messages, and unverified regulatory or mandate operations remain simulated or feature-gated.”

## Recording hygiene

- Hide API keys, webhook secrets, approval tokens, tunnel tokens, email addresses, and browser autofill.
- Use a fresh demo database or reset the Compose volume before a retake.
- Keep browser zoom around 90–100% and widen the window so the case table is readable.
- Do not claim that a successful payment creates a recovery case; it should not.
- Keep the log terminal ready so the asynchronous API → worker handoff is visible.

## Fast recovery if the demo is empty

1. Check `Invoke-RestMethod http://localhost:8000/health`.
2. Check `docker compose logs --tail 100 api worker`.
3. Confirm the frontend is using `http://localhost:8000`.
4. Re-run the signed failure fixture from `DEMO.md`.
5. Wait 5–10 seconds and hard-refresh the dashboard.
