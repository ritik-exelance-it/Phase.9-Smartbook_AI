from __future__ import annotations

import re
import phonenumbers
from phonenumbers import NumberParseException

_EMAIL_RE = re.compile(
    r"^(?=.{3,254}$)(?=.{1,64}@)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

def normalize_email(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    email = str(value).strip()
    if not _EMAIL_RE.fullmatch(email):
        raise ValueError("The email address is invalid. Please correct it or skip it.")
    local, domain = email.rsplit("@", 1)
    return f"{local}@{domain.casefold()}"

def normalize_phone(value: str | None, default_region: str = "IN") -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        parsed = phonenumbers.parse(raw, None if raw.startswith("+") else default_region)
    except NumberParseException as exc:
        raise ValueError("The phone number is invalid. Include the country code if needed.") from exc
    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        raise ValueError("The phone number is invalid. Include the country code if needed.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
