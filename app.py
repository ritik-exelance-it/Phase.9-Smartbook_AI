from __future__ import annotations

import uuid
import logging
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from db import initialize_database
from tools import (
    append_conversation_message,
    create_or_get_conversation,
    get_conversation_history,
    list_user_conversations,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Thin adapter to the existing SmartBook LangGraph backend.
# Keep this file beside agent.py. No movie or booking data is fabricated here.
try:
    from agent import chat as backend_chat
except Exception as exc:
    backend_chat = None
    BACKEND_IMPORT_ERROR = exc
    logger.exception("Could not import the SmartBook backend")
else:
    BACKEND_IMPORT_ERROR = None

st.set_page_config(
    page_title="SmartBook | Cinema",
    page_icon="🎟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

initialize_database()

# Dark-only palette: ink, warm charcoal, espresso brown, burgundy, and restrained sage.
st.markdown(
    """
    <style>
    :root {
      color-scheme: dark;
      --ink: #171514;
      --charcoal: #211D1B;
      --panel: #292321;
      --panel-raised: #302824;
      --espresso: #493326;
      --burgundy: #813D4B;
      --burgundy-hover: #985260;
      --ivory: #F2E9DC;
      --muted: #C0B3A5;
      --sage: #A7B39B;
      --line: #493D36;
      --danger: #E5A49D;
    }
    html, body, [class*="css"], .stApp {
      color: var(--ivory) !important;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
    }
    .stApp { background: var(--ink) !important; }
    [data-testid="stHeader"] { background: rgba(23,21,20,.98) !important; }
    [data-testid="stToolbar"] { right: 1rem; }
    [data-testid="stSidebar"] {
      background: #201A17 !important;
      border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] * { color: var(--ivory); }
    [data-testid="stSidebar"] .stButton > button {
      text-align: left; justify-content: flex-start;
    }
    .sb-wordmark {
      color: var(--ivory); font-family: Georgia, "Times New Roman", serif;
      font-size: 1.65rem; letter-spacing: -.045em; font-weight: 600;
      line-height: 1.1; margin: .25rem 0 .2rem;
    }
    .sb-overline {
      color: var(--sage); text-transform: uppercase; letter-spacing: .16em;
      font-size: .68rem; font-weight: 700;
    }
    .sb-rule { border-top: 1px solid var(--line); margin: 1.05rem 0; }
    .sb-hero {
      border: 1px solid var(--line); border-radius: 12px;
      background: linear-gradient(110deg, #30241F 0%, #241D1A 62%, #211D1B 100%);
      padding: clamp(1.2rem, 3vw, 2.2rem); margin: .2rem 0 1.25rem;
      box-shadow: none;
    }
    .sb-hero h1 {
      font-family: Georgia, "Times New Roman", serif; color: var(--ivory) !important;
      font-size: clamp(2rem, 4.1vw, 3.15rem); font-weight: 500;
      letter-spacing: -.045em; line-height: 1.08; margin: .5rem 0 .65rem;
    }
    .sb-hero p { color: var(--muted) !important; max-width: 42rem; margin: 0; line-height: 1.65; }
    .sb-heading {
      font-family: Georgia, "Times New Roman", serif; font-size: 1.3rem;
      color: var(--ivory); margin: .35rem 0 .25rem;
    }
    .sb-muted { color: var(--muted) !important; font-size: .88rem; line-height: 1.55; }
    .sb-label {
      color: var(--sage) !important; text-transform: uppercase; letter-spacing: .12em;
      font-size: .7rem; font-weight: 700;
    }
    .sb-pill {
      display: inline-block; border: 1px solid #53604F; background: #293027;
      color: #D6E0D0 !important; border-radius: 999px; padding: .22rem .6rem;
      font-size: .75rem; margin: .1rem .2rem .1rem 0;
    }
    .sb-card {
      background: var(--charcoal); border: 1px solid var(--line); border-radius: 11px;
      padding: 1rem 1.1rem; margin: .3rem 0 .75rem;
    }
    .sb-card-title {
      color: var(--ivory) !important; font-family: Georgia, serif;
      font-size: 1.1rem; font-weight: 600; margin-bottom: .25rem;
    }
    .sb-ticket {
      border: 1px solid #745343; border-left: 4px solid var(--burgundy);
      background: #2B211D; border-radius: 10px; padding: 1rem 1.1rem; margin: .5rem 0;
    }
    .sb-ticket .value { color: var(--ivory) !important; font-weight: 600; }
    .sb-ticket .key { color: var(--muted) !important; font-size: .78rem; }
    /* Force readable foreground/background on Streamlit widgets. */
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span,
    [data-testid="stMarkdownContainer"] label { color: var(--ivory); }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
      color: var(--muted) !important;
    }
    [data-testid="stChatMessage"] {
      background: #272220 !important; border: 1px solid var(--line) !important;
      border-radius: 12px !important; padding: .9rem 1rem !important;
      margin: .45rem 0 .7rem !important;
    }
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li,
    [data-testid="stChatMessage"] span { color: var(--ivory) !important; }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
      background: #33261F !important; border-color: #624737 !important;
    }
    /* Make the entire bottom chat area match the app background */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
    background: #171514 !important;
    background-color: #171514 !important;
}

/* Chat input styling */
[data-testid="stChatInput"] {
    background: #171514 !important;
    background-color: #171514 !important;
    border: 1px solid #60483B !important;
    border-radius: 12px !important;
    box-shadow: none !important;
}

[data-testid="stChatInput"] > div {
    background: #171514 !important;
}

[data-testid="stChatInput"] textarea {
    color: #F2E9DC !important;
    caret-color: #F2E9DC !important;
    background: #171514 !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: #B4A69A !important;
}

/* Remove the white bottom fade/gradient */
[data-testid="stBottom"]::before {
    background: #171514 !important;
}
    [data-testid="stChatInput"] textarea {
      color: var(--ivory) !important; caret-color: var(--ivory) !important;
      background: transparent !important;
    }
    [data-testid="stChatInput"] textarea::placeholder { color: #B4A69A !important; }
    .stTextInput input, .stNumberInput input, .stSelectbox [data-baseweb="select"] *,
    .stTextArea textarea {
      color: var(--ivory) !important; background: #2B2522 !important;
      border-color: #5A4940 !important;
    }
    [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {
      background: #2B2522 !important; color: var(--ivory) !important;
    }
    [role="option"] { color: var(--ivory) !important; }
    .stButton > button, .stDownloadButton > button {
      background: #30251F !important; color: var(--ivory) !important;
      border: 1px solid #634B3C !important; border-radius: 8px !important;
      min-height: 2.45rem; font-weight: 600; box-shadow: none !important;
      transition: background .15s ease, border-color .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
      background: #493326 !important; border-color: #9B735A !important; color: #FFF8EF !important;
    }
    .stButton > button[kind="primary"], .stFormSubmitButton > button {
      background: var(--burgundy) !important; border-color: var(--burgundy) !important;
      color: #FFF8F1 !important;
    }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {
      background: var(--burgundy-hover) !important;
    }
    div[data-testid="stAlert"] { background: #302824 !important; color: var(--ivory) !important; border-color: #695344 !important; }
    div[data-testid="stAlert"] p { color: var(--ivory) !important; }
    hr { border-color: var(--line) !important; }
    [data-testid="stExpander"] { border-color: var(--line) !important; background: #211D1B !important; }
    [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p { color: var(--ivory) !important; }
    [data-testid="stProgressBar"] > div > div { background: var(--burgundy) !important; }
    a { color: #D9B5A1 !important; }
    @media (max-width: 700px) {
      .sb-hero { padding: 1.15rem; }
      [data-testid="stChatMessage"] { padding: .7rem !important; }
      .sb-wordmark { font-size: 1.45rem; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; animation: none !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def start_new_conversation() -> None:
    st.session_state.conversation_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.backend_error = None
    st.session_state.active_view = "Chat"
    create_or_get_conversation(
        st.session_state.user_id,
        st.session_state.conversation_id,
    )
    st.query_params["conversation"] = st.session_state.conversation_id


def enqueue_prompt(message: str) -> None:
    st.session_state.pending_prompt = message
    st.session_state.active_view = "Chat"


if "user_id" not in st.session_state:
    guest_token = st.query_params.get("guest")
    try:
        st.session_state.user_id = f"guest-{uuid.UUID(guest_token)}"
    except (ValueError, TypeError, AttributeError):
        guest_uuid = uuid.uuid4()
        st.session_state.user_id = f"guest-{guest_uuid}"
        st.query_params["guest"] = str(guest_uuid)
if "conversation_id" not in st.session_state:
    conversation_token = st.query_params.get("conversation")
    try:
        conversation_uuid = str(uuid.UUID(conversation_token))
    except (ValueError, TypeError, AttributeError):
        conversation_uuid = str(uuid.uuid4())
    conversation_record = create_or_get_conversation(
        st.session_state.user_id,
        conversation_uuid,
    )
    if conversation_record.get("error"):
        conversation_uuid = str(uuid.uuid4())
        create_or_get_conversation(st.session_state.user_id, conversation_uuid)
    st.session_state.conversation_id = conversation_uuid
    st.session_state.messages = get_conversation_history(
        st.session_state.user_id,
        conversation_uuid,
    )
    st.query_params["conversation"] = conversation_uuid
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_view" not in st.session_state:
    st.session_state.active_view = "Chat"
if "backend_error" not in st.session_state:
    st.session_state.backend_error = None

# Streamlit's server-side session gets an isolated demo identity. Production
# deployments should replace this with an ID from authenticated server-side auth.
user_id = st.session_state.user_id
role = "customer"

with st.sidebar:
    st.markdown('<div class="sb-wordmark">SmartBook</div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-overline">Cinema, considered.</div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-rule"></div>', unsafe_allow_html=True)

    st.markdown('<div class="sb-label">Workspace</div>', unsafe_allow_html=True)
    nav_items = [
        ("Chat", "✳  Concierge"),
        ("Movies", "▣  Movies"),
        ("Bookings", "▤  My bookings"),
        ("FAQs", "?  Help & policies"),
    ]
    for view, label in nav_items:
        if st.button(label, key=f"nav_{view}", use_container_width=True,
                     type="primary" if st.session_state.active_view == view else "secondary"):
            st.session_state.active_view = view
            if view == "Movies":
                st.session_state.pending_prompt = "What movies are available?"
            elif view == "Bookings":
                st.session_state.pending_prompt = "Show my bookings or help me check a booking."
            elif view == "FAQs":
                st.session_state.pending_prompt = "Tell me the cinema policies and frequently asked questions."
            st.rerun()

    st.markdown('<div class="sb-rule"></div>', unsafe_allow_html=True)
    if st.button("＋  New conversation", use_container_width=True):
        start_new_conversation()
        st.rerun()

    st.markdown('<div class="sb-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-label">Recent conversations</div>', unsafe_allow_html=True)
    conversations = list_user_conversations(user_id)
    conversation_ids = [item["conversation_id"] for item in conversations]
    current_index = (
        conversation_ids.index(st.session_state.conversation_id)
        if st.session_state.conversation_id in conversation_ids
        else 0
    )
    if conversation_ids:
        selected_conversation_id = st.selectbox(
            "Choose a conversation",
            options=conversation_ids,
            index=current_index,
            format_func=lambda value: next(
                (item["title"][:48] for item in conversations if item["conversation_id"] == value),
                "Conversation",
            ),
            label_visibility="collapsed",
        )
        if (
            selected_conversation_id is not None
            and selected_conversation_id != st.session_state.conversation_id
        ):
            st.session_state.conversation_id = selected_conversation_id
            st.session_state.messages = get_conversation_history(
                user_id,
                selected_conversation_id,
            )
            st.query_params["conversation"] = selected_conversation_id
            st.rerun()
    else:
        st.markdown('<div class="sb-muted">Your conversation will appear here once you get started.</div>', unsafe_allow_html=True)
    st.caption("Guest mode is not authentication. Anyone with this guest link can access its bookings; do not share the URL.")
    st.markdown('<div class="sb-rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-muted">Connected to your SmartBook booking agent.</div>', unsafe_allow_html=True)

def safe_response_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def send_to_backend(message: str) -> None:
    message = message.strip()
    if not message:
        return
    if backend_chat is None:
        raise RuntimeError("The SmartBook backend could not be imported.") from BACKEND_IMPORT_ERROR

    st.session_state.messages.append({"role": "user", "content": message})
    with st.chat_message("user", avatar="👤"):
        st.markdown(message)

    history_saved = True
    try:
        append_conversation_message(
            user_id,
            st.session_state.conversation_id,
            "user",
            message,
        )
    except Exception:
        logger.exception("Could not persist a user conversation message")
        history_saved = False

    try:
        with st.spinner("Checking with the cinema desk…"):
            answer = backend_chat(
                message=message,
                user_id=user_id,
                role=role,
                conversation_id=st.session_state.conversation_id,
            )
        answer = safe_response_text(answer)
        if not answer:
            answer = "I didn't receive a usable response from the booking service. Please try again."
    except Exception:
        logger.exception("SmartBook backend chat turn failed")
        answer = (
            "I couldn't reach the booking service just now, so I can't verify whether that action completed. "
            "Please try again in a moment. If it continues, check that the backend and database are running."
        )
    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant", avatar="🎟️"):
        st.markdown(answer)
    try:
        append_conversation_message(
            user_id,
            st.session_state.conversation_id,
            "assistant",
            answer,
        )
    except Exception:
        logger.exception("Could not persist an assistant conversation message")
        history_saved = False
    st.session_state.backend_error = None
    if not history_saved:
        st.warning("This turn was processed, but conversation history could not be saved.")


# Header changes with the selected navigation section.
view_copy = {
    "Chat": ("A quieter way to book.", "Your cinema concierge for movie details, bookings, cancellations, and the little questions in between."),
    "Movies": ("Find tonight's story.", "Ask the connected movie catalogue what is available. Details appear only when your backend provides them."),
    "Bookings": ("Your plans, in one place.", "Check a booking, ask about its status, or request a cancellation through the booking service."),
    "FAQs": ("The practical details.", "Ask about cinema policies and get answers grounded in your connected knowledge base."),
}
headline, subhead = view_copy.get(st.session_state.active_view, view_copy["Chat"])
st.markdown(
    f'<section class="sb-hero"><div class="sb-overline">SMARTBOOK · CINEMA CONCIERGE</div>'
    f'<h1>{headline}</h1><p>{subhead}</p></section>',
    unsafe_allow_html=True,
)

if backend_chat is None:
    st.error("The SmartBook backend could not be imported. Place this `app.py` beside your existing `agent.py` and install the project's dependencies.")
    with st.expander("Developer details"):
        st.code(f"{type(BACKEND_IMPORT_ERROR).__name__}: {BACKEND_IMPORT_ERROR}")
    st.stop()

if not st.session_state.messages:
    st.markdown('<div class="sb-heading">Good evening.</div>', unsafe_allow_html=True)
    st.markdown('<p class="sb-muted">Start with a question below, or choose a prompt to get going.</p>', unsafe_allow_html=True)
    quick_cols = st.columns(3)
    suggestions = [
        ("Browse films", "What movies are available?"),
        ("Booking status", "Help me check my booking status."),
        ("Cinema policies", "What is the cancellation policy?"),
    ]
    for col, (label, text) in zip(quick_cols, suggestions):
        with col:
            if st.button(label, key=f"empty_{label}", use_container_width=True):
                enqueue_prompt(text)
                st.rerun()

# Conversation history is session-persistent; LangGraph receives the same thread ID each turn.
for item in st.session_state.messages:
    with st.chat_message(item["role"], avatar="👤" if item["role"] == "user" else "🎟️"):
        st.markdown(item["content"])

pending = st.session_state.pop("pending_prompt", None)
if pending:
    send_to_backend(pending)
    st.rerun()

prompt = st.chat_input("Ask about a film, your booking, or a cinema policy…")
if prompt:
    send_to_backend(prompt)
    st.rerun()

st.markdown('<div class="sb-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sb-muted">Booking details and availability come from the connected backend. '
    'Always rely on the service confirmation for booking or cancellation status.</div>',
    unsafe_allow_html=True,
)
