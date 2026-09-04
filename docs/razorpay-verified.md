# Razorpay verified facts

Record only facts verified from official Razorpay documentation, with source URL and date.

| Topic | Verified fact | Source | Checked |
|---|---|---|---|
| Webhook signature | `X-Razorpay-Signature` is HMAC-SHA256 of the raw request body using the webhook secret. Do not parse or cast the body before validation. | https://razorpay.com/docs/webhooks/validate-test/ | 2026-08-26 |
| Webhook dedupe | `x-razorpay-event-id` is unique per webhook event and can be used for duplicate detection. | https://razorpay.com/docs/webhooks/validate-test/ | 2026-08-26 |
| Payment links | `POST /v1/payment_links` supports smallest-unit `amount`, `expire_by`, unique `reference_id`, `notify`, and `reminder_enable`. | https://razorpay.com/docs/api/payments/payment-links/create-standard/ | 2026-08-26 |
| Subscription retries | Failed subscription charges move to pending and Razorpay documents automatic retries; manual charging details vary by method and require verification before implementation. | https://razorpay.com/docs/payments/subscriptions/payment-retries/ | 2026-08-26 |
| A1 mandate retry boundary | Razorpay documents manual Attempt Charge for an issued subscription invoice from the Dashboard; no public API endpoint for the project’s automated mandate retry has been verified. Automated mandate charging remains disabled. | https://razorpay.com/docs/payments/subscriptions/manually-charge-card/ | 2026-08-28 |
| A2 retry behavior | Razorpay’s Test Subscription flow says four consecutive failed test charges exhaust available retries and move the Subscription to `halted`. This does not establish a universal UPI Autopay regulatory cap. | https://razorpay.com/docs/payments/subscriptions/test/ | 2026-08-28 |
| A3 pre-debit notice | RBI’s e-mandate framework requires the issuer to send a pre-debit notification at least 24 hours before the actual debit. Razorpay-specific implementation and exceptions remain unverified. | https://www.rbi.org.in/scripts/bs_circularindexdisplay.aspx/Scripts/BS_CircularIndexDisplay.aspx?Id=12722 | 2026-08-28 |
| A4 order states and listing | Razorpay documents `created`, `attempted`, and `paid` order states and the `GET /v1/orders` collection endpoint with pagination. The sweeper must locally filter recent non-paid orders after a Test Mode response is confirmed. | https://razorpay.com/docs/api/orders/fetch-all/ | 2026-08-28 |
| A5 communication classification | TRAI describes service communication as facilitating or confirming a transaction the recipient previously consented to enter into. Merchant/legal approval is still required for this product’s email wording and consent basis. | https://www.trai.gov.in/advice-to-senders | 2026-08-28 |
| A6 SMS controls | TRAI’s sender guidance requires sender registration, headers, content templates, and customer consent controls for commercial communication. SMS remains disabled; DLT/DND compliance is not enabled. | https://www.trai.gov.in/advice-to-senders | 2026-08-28 |
| A7 idempotency scope | Razorpay’s documented `X-Payout-Idempotency` header applies to RazorpayX payout APIs. No provider idempotency header has been verified for the Payment Link or Subscription endpoints used by this project. | https://razorpay.com/docs/api/x/payout-idempotency/make-request/ | 2026-08-28 |
| A9 application settings | The application will use a 24-hour Payment Link expiry, `notify.email=false`, `notify.sms=false`, and `reminder_enable=false`; the unique internal case/order reference is used as `reference_id`. | https://razorpay.com/docs/api/payments/payment-links/create-standard/ | 2026-08-28 |
| A10 Test Mode flows | Official Test Mode documentation supports `failure@razorpay` for UPI failures, mock-bank Success/Failure controls for cards, and Dashboard Charge this now failure simulation for subscriptions. The actual event payloads still need to be captured from this merchant account. | https://razorpay.com/docs/payments/payments/test-upi-details/; https://razorpay.com/docs/payments/payments/test-card-details/; https://razorpay.com/docs/payments/subscriptions/test/ | 2026-08-28 |

## Still blocked

A1, A2, A3, A4, A5, A6, A7 and A10 remain blocked pending endpoint confirmation, live Test Mode capture, or merchant/legal approval. A9 has an application decision recorded above. The real adapter must keep unverified operations disabled.

## Project decisions

- Approved contact channel: email-only, rendered locally, with an opt-out line; SMS is disabled.
- Approval queue: manual dashboard/UI decision; no executable approval API.
- These are project decisions, not Razorpay or legal certifications.
