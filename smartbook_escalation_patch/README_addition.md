## Human support escalations (Slack)

SmartBook can record a human-support escalation in SQLite, assign it to an active employee from `support_employees`, and post a notification to the configured Slack channel. The escalation record is committed before Slack delivery is attempted. A Slack failure therefore does not delete the support ticket; its `slack_status` is stored as `failed` for later inspection.

### Configure Slack

1. Create a Slack app in the workspace.
2. Add the bot permission `chat:write`, install the app, and invite it to the support channel.
3. Copy the bot token and channel ID into `.env`:

```dotenv
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_ESCALATION_CHANNEL_ID=C0123456789
```

4. Install dependencies with `pip install -r requirements.txt`.
5. Insert real support employees into `support_employees`. The assignment code intentionally does not invent employee records. Teams supported by the initial routing are `booking_support`, `billing_support`, `technical_support`, and `customer_support`.
6. Start the app normally. `initialize_database()` applies the additive support schema migration. Back up `cinema.db` before the first startup after updating.

The Slack channel should be private to staff who are authorized to handle customer support. Slack notifications include the customer's supplied contact information only when the customer has consented. Do not send passwords, OTPs, card details, or other payment credentials to support channels.

### Current scope and limitations

- The current escalation flow stores support tickets and can notify a configured Slack channel.
- Employee assignment requires actual employee records. When no eligible employee is configured, tickets remain unassigned rather than using fabricated names.
- This demo uses an anonymous guest identity and is not production authentication. Do not deploy it for real customer personal information until trusted authentication, authorization, privacy controls, and secure secret management are implemented.
- A failed Slack notification is retained as a failed status; this initial implementation does not yet provide a retry queue or email fallback.
- Cancellation records a booking cancellation only; it does not issue an actual payment refund.

## Planned features

### Email notification fallback

- Send an email when Slack is unavailable or notification delivery fails.
- Add configurable retry policies, delivery attempts, and notification audit history.
- Allow administrators to configure fallback recipients and escalation channels.

### Human-support workspace

- Employee dashboard for viewing, filtering, assigning, and resolving escalations.
- Employee notes, reassignment, priority changes, and status history.
- Customer-facing ticket status and follow-up messages.
- Response-time and resolution-time reporting.

### Real billing and payment system

- Integrate a supported payment provider and verify transactions through trusted server-side APIs and webhooks.
- Store provider transaction references and payment state; never store card numbers, CVV, OTP, or payment credentials.
- Reconcile payment state against booking records and provide verified billing inquiry tools.

### Real refund processing

- Check refund eligibility using verified provider transaction and booking data.
- Require the appropriate employee approval before initiating refunds.
- Execute refunds through the payment provider's supported API and store the provider refund reference.
- Track pending, succeeded, and failed refunds and notify customers only from verified provider results.

These are roadmap items, not implemented functionality. The current booking cancellation operation must not be described as a payment refund.
