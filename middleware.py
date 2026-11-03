"""SmartBook AI middleware and guardrails."""
from __future__ import annotations
import re
from typing import Any

ROLE_PERMISSIONS = {
    "customer": {"search_knowledge", "list_movies", "movie_details", "search_external_metadata", "create_booking", "check_own_booking", "list_own_bookings", "cancel_own_booking", "request_human"},
    "support_agent": {"search_knowledge", "list_movies", "movie_details", "search_external_metadata", "check_own_booking", "request_human", "review_escalations"},
    "admin": {"search_knowledge", "list_movies", "movie_details", "search_external_metadata", "create_booking", "check_own_booking", "list_own_bookings", "cancel_own_booking", "request_human", "review_escalations"},
}
MAX_APPLICATION_TOOL_EXECUTIONS_PER_TURN = 1
MAX_ASSISTANT_OUTPUT_LENGTH = 6000
MAX_CATALOGUE_OUTPUT_LENGTH = 50000
INTENT_PERMISSIONS = {
    "list_movies": "list_movies", "list_available_movies": "list_movies",
    "movie_search": "list_movies", "movie_details": "movie_details",
    "external_movie_search": "search_external_metadata",
    "external_movie_details": "search_external_metadata",
    "movie_question": "search_external_metadata", "knowledge": "search_knowledge",
    "book_ticket": "create_booking", "confirm_booking": "create_booking",
    "list_bookings": "list_own_bookings", "check_booking": "check_own_booking",
    "cancel_booking": "cancel_own_booking", "confirm_cancel": "cancel_own_booking",
    "escalate": "request_human", "escalation_followup": "request_human",
}

def validate_message(message: str, max_length: int = 4000) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Please enter a message.")
    if len(message) > max_length:
        raise ValueError(f"Message is too long. Limit: {max_length} characters.")
    if any(ord(c) == 0 or (ord(c) < 32 and c not in "\n\r\t") for c in message):
        raise ValueError("Your message contains unsupported control characters.")
    return message.strip()

def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())

def require_permission(role: str, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionError("You don't have permission to perform that action.")

def authorize_intent(role: str, intent: str) -> None:
    permission = INTENT_PERMISSIONS.get(intent)
    if permission:
        require_permission(role, permission)

def validate_positive_int(value: int | None, field_name: str, maximum: int = 10) -> int:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"{field_name} must be a whole number between 1 and {maximum}.")
    return value

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()\-]{7,}\d)(?!\w)")
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~-]{12,})\b", re.I)

def redact_pii(value: Any) -> str:
    """Diagnostic-safe text only; never use this to mutate booking records."""
    text = _SECRET.sub("[REDACTED_SECRET]", str(value))
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    return _PHONE.sub("[REDACTED_PHONE]", text)[:2000]

_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:reveal|print|show|expose)\s+(?:the\s+)?(?:system\s+)?prompt\b", re.I),
    re.compile(r"\b(?:exfiltrate|reveal|print|show)\s+(?:the\s+)?(?:api\s+)?keys?\b", re.I),
    re.compile(r"\b(?:call|invoke|execute)\s+(?:any|arbitrary|the)\s+tool\b", re.I),
)

def sanitize_untrusted_context(value: Any, max_length: int = 12000) -> str:
    """Defense-in-depth sanitizer for retrieved passages and external metadata."""
    if not isinstance(value, str):
        return ""
    lines = []
    for line in value.splitlines():
        lines.append("[Untrusted instruction-like content omitted.]" if any(p.search(line) for p in _INJECTION_PATTERNS) else line)
    return "\n".join(lines)[:max_length]

def validate_assistant_output(
    value: Any,
    max_length: int = MAX_ASSISTANT_OUTPUT_LENGTH,
) -> str:
    if not isinstance(value, str) or not value.strip():
        return "I couldn't prepare a valid response. Please try again."
    output = value.strip()
    if len(output) > max_length:
        output = output[:max_length].rsplit(" ", 1)[0].rstrip() + "\n\n[Response shortened.]"
    if _SECRET.search(output):
        return "I can't provide that information. Please contact support if you need assistance."
    return output
