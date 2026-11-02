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
