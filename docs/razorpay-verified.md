# Razorpay verified facts

Record only facts verified from official Razorpay documentation, with source URL and date.

| Topic | Verified fact | Source | Checked |
|---|---|---|---|
| Webhook signature | `X-Razorpay-Signature` is HMAC-SHA256 of the raw request body using the webhook secret. Do not parse or cast the body before validation. | https://razorpay.com/docs/webhooks/validate-test/ | 2026-08-26 |
| Webhook dedupe | `x-razorpay-event-id` is unique per webhook event and can be used for duplicate detection. | https://razorpay.com/docs/webhooks/validate-test/ | 2026-08-26 |
| Payment links | `POST /v1/payment_links` supports smallest-unit `amount`, `expire_by`, unique `reference_id`, `notify`, and `reminder_enable`. | https://razorpay.com/docs/api/payments/payment-links/create-standard/ | 2026-08-26 |
| Subscription retries | Failed subscription charges move to pending and Razorpay documents automatic retries; manual charging details vary by method and require verification before implementation. | https://razorpay.com/docs/payments/subscriptions/payment-retries/ | 2026-08-26 |

## Still blocked

A1, A2, A3, A4, A5, A6, A7, A9 and A10 from the build specification remain unverified. The real adapter must keep those paths disabled.
