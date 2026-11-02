from typing import Iterable

ROLE_PERMISSIONS = {
    "customer": {"search_knowledge", "list_movies", "movie_details", "create_booking", "check_own_booking", "list_own_bookings", "cancel_own_booking", "request_human"},
    "support_agent": {"search_knowledge", "list_movies", "movie_details", "check_own_booking", "request_human", "review_escalations"},
    "admin": {"search_knowledge", "list_movies", "movie_details", "create_booking", "check_own_booking", "list_own_bookings", "cancel_own_booking", "request_human", "review_escalations"},
}

def validate_message(message: str, max_length: int = 4000) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Please enter a message.")
    if len(message) > max_length:
        raise ValueError(f"Message is too long. Limit: {max_length} characters.")
    return message.strip()

def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())

def require_permission(role: str, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionError("You don't have permission to perform that action.")

def validate_positive_int(value: int | None, field_name: str, maximum: int = 10) -> int:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"{field_name} must be a whole number between 1 and {maximum}.")
    return value
