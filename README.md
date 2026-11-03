# SmartBook AI v1

A local, role-aware LangGraph agent using OpenRouter, SQLite, deterministic tools, a small Markdown knowledge base, and basic human escalation records. The first configured domain is a cinema demo.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your OpenRouter API key and a currently supported model ID from OpenRouter's model catalogue.
4. Run the command-line app with `python main.py`, or launch the Streamlit UI with `python -m streamlit run app.py`. Run these commands after activating the virtual environment so they use the installed project dependencies.

## Important demo limitations

- The CLI uses a fixed demo identity (`demo-customer`). Streamlit uses an anonymous guest identity carried in the `guest` URL parameter so the same guest can restore conversations and bookings from that link. This is not authentication: anyone with the link can act as that guest, so do not share it. Production deployments must use trusted server-side authentication and derive identity and role from it.
- The knowledge retriever ranks a small number of relevant Markdown passages using deterministic keyword matching; it is not vector RAG.
- Movie catalogue requests return every matching database-backed title and its scheduled screenings. Availability requests return screenings with seats remaining; catalogue titles and available screenings are reported separately.
- Movie-title searches accept partial names and spelling variations when the match is clear; ambiguous searches return candidate titles instead of guessing.
- Booking requests collect missing details, verify the selected screening and seat capacity, show the calculated total, and create the booking only after an explicit confirmation.
- Confirmed bookings are scoped to the guest identity, use the exact selected screening, and have an idempotency key to prevent duplicate confirmations on retries.
- Streamlit conversation transcripts and business records are stored in `cinema.db`. LangGraph conversation checkpoints persist separately in `conversation_checkpoints.sqlite`; set `SMARTBOOK_CHECKPOINT_DB` in `.env` to choose another checkpoint database path.
- The initial movie library and weekly schedule are loaded from `movies_normalized.csv` and `showtimes_normalized.csv`. Movies and dated, screened showtimes are stored relationally. Legacy bookings are retained as historical records during migration.
- Escalations are stored locally; no human is notified automatically.
- The cancellation behavior records a cancellation; it does not process an actual payment refund.
- The startup migration can replace the legacy flat movie schema. Back up any existing `cinema.db` before using this version, and do not point it at a production database.

## Example requests

- `List movies`
- `Tell me about Inception`
- `Book 2 tickets for Inception for Ritik`
- `Check booking 1`
- `Cancel booking 1`
- `What is your cancellation policy?`
- `I want to speak to a human`

## Roles

The CLI defaults to `customer`. The role is supplied by application code and should come from a trusted authentication layer in a deployed application. Never trust a role supplied inside the user's message.

# V2

## Human support escalations (Slack)

SmartBook can record a human-support escalation in SQLite, assign it to an active employee from `support_employees`, and post a notification to the configured Slack channel. This queues a support ticket; it does not establish a live chat or confirm that an employee has responded. The escalation record is committed before Slack delivery is attempted. A Slack failure therefore does not delete the support ticket; its `slack_status` is stored as `failed` for later inspection.

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

## V 2.1 features

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

## Updated support escalation implementation

- The agent extracts issue category, priority, customer name, email, phone and booking ID from the initial request before asking follow-up questions. AI output is constrained to supported categories and priorities; deterministic validation/fallbacks handle malformed or missing values.
- Missing name, email and phone fields are asked separately and can each be skipped. Details included in later replies are extracted too, so repeating the issue while answering a follow-up does not overwrite the name or lose the email/booking ID. Preferred contact is captured only when a corresponding contact method was supplied. The customer is asked for explicit consent before email/phone/name are included in Slack. Voluntarily supplied contact details remain in the escalation record even when Slack sharing is declined.
- Seven demo support employees are seeded idempotently: EMP001 Ritik Mishra, EMP002 Khushi Patel, EMP003 Sairam Madduri, EMP004 Anshika Dixit, EMP005 Akash Sahoo, EMP006 Devyani Patil, EMP007 Ayush Singh. Demo emails use the reserved non-deliverable `example.invalid` domain and must be replaced with verified addresses before any employee email workflow is added.
- New tickets use a persistent global round-robin pointer across the active seeded employees, independent of category. The ticket is committed before Slack delivery; notification failures remain visible in `slack_status`. Duplicate open tickets in the same customer/conversation do not consume another assignment slot.
- Slack messages use Block Kit and include ticket/category/priority, customer and booking details, assignment, issue summary and consent status. Keep the destination channel private and limited to authorized support staff.


## TMDB movie information

- Set `TMDB_READ_ACCESS_TOKEN` in `.env` to enable read-only TMDB metadata. Without it, external movie questions return a clear configuration message; the cinema catalogue and booking tools continue to work.
- After a movie is selected, ask “tell me about this” for its external overview, or ask for its age rating, runtime, release year, or poster. Age classifications are reported by country from TMDB release-date data; they are not converted into a universal minimum age.
- Follow-up questions such as “should I watch this with my family?” use the selected movie's cached synopsis, genres, and country-specific certifications to answer the new question directly rather than repeating the entire movie summary. Recommendations are guidance, not official ratings; share viewer ages and country for a more relevant suitability answer.
- Local screenings, availability, prices, and bookings remain sourced from the cinema database. TMDB metadata does not verify cinema availability.
- This product uses the TMDB API but is not endorsed or certified by TMDB.

# Future roadmap (not implemented)

**Email fallback:** add verified employee email addresses, configurable recipient mapping, Slack-failure fallback, retry/backoff, delivery audit records and alerting for failed notifications.

**Human-support workspace:** add authenticated employee sign-in, ticket inbox, search/filter, employee reassignment, internal notes, status transitions, SLA tracking, customer-visible status and resolution analytics.

**Billing and payment verification:** integrate a payment provider's server-side API and signed webhooks; reconcile transaction references with booking records; expose read-only verified billing inquiry tools. Never store card numbers, CVV, OTPs or payment credentials.

**Real refund execution:** add eligibility checks against verified provider records, employee approval, provider refund API execution, idempotency, audit history, pending/succeeded/failed states and customer notification based only on provider-confirmed outcomes. Cancellation in the current demo is not a refund.

These roadmap items are future work and are not part of this patch.
