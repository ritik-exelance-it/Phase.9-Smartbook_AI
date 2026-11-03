"""Conversation flow and structured extraction for optional human-support details."""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, Field

from contact_validation import normalize_email, normalize_phone


class EscalationIntentAnalysis(BaseModel):
    category: Literal["booking", "cancellation", "payment_refund", "technical", "account_profile", "general"] = "general"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    issue_summary: str = Field(default="Customer requested human support.", max_length=1200)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    booking_id: int | None = None


def _fallback_extract(message: str) -> dict:
    email_match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", message, re.I)
    phone_match = re.search(r"(?<!\w)(?:\+?\d[\d ()-]{5,}\d)(?!\w)", message)
    booking_match = re.search(r"\b(?:booking|reservation)\s*(?:id|number|#)?\s*[:#-]?\s*(\d+)\b", message, re.I)
    clean = message
    if email_match:
        clean = clean.replace(email_match.group(0), "[email provided]")
    if phone_match:
        clean = clean.replace(phone_match.group(0), "[phone provided]")
    if booking_match:
        clean = clean.replace(booking_match.group(0), "[booking ID provided]")
    category = "general"
    low = message.casefold()
    if re.search(r"\bcancel|cancellation\b", low):
        category = "cancellation"
    elif re.search(r"\b(refund|payment|paid|deducted|charged|transaction)\b", low):
        category = "payment_refund"
    elif re.search(r"\b(booking|ticket|reservation|showtime)\b", low):
        category = "booking"
    elif re.search(r"\b(app|website|error|bug|crash|technical)\b", low):
        category = "technical"
    priority = "normal"
    if re.search(r"\b(urgent|immediately|fraud|double charged|money deducted)\b", low):
        priority = "high"
    return {
        "category": category,
        "priority": priority,
        "issue_summary": clean[:1200],
        "customer_name": None,
        "customer_email": email_match.group(0) if email_match else None,
        "customer_phone": phone_match.group(0) if phone_match else None,
        "booking_id": int(booking_match.group(1)) if booking_match else None,
    }


def _valid_email(value: str | None) -> bool:
    try:
        return normalize_email(value) is not None
    except ValueError:
        return False


def _valid_phone(value: str | None) -> bool:
    try:
        return normalize_phone(value) is not None
    except ValueError:
        return False


def begin_escalation(message: str, analysis_llm) -> dict:
    """Extract known facts first, then ask only for missing optional information."""
    extracted = None
    try:
        extracted = analysis_llm.invoke([
            {"role": "system", "content": (
                "Analyze this cinema support complaint. Extract only explicitly stated facts. "
                "Choose category from booking, cancellation, payment_refund, technical, "
                "account_profile, general. Choose priority low, normal, high, urgent. "
                "Use high for financial/booking disruption and urgent only for immediate serious impact. "
                "Extract customer name, email, phone, numeric booking ID. Summarize the issue "
                "without copying email addresses or phone numbers into issue_summary."
            )},
            {"role": "user", "content": message},
        ])
    except Exception:
        extracted = None
    data = extracted.model_dump() if extracted else _fallback_extract(message)
    fallback = _fallback_extract(message)
    for key in ("customer_email", "customer_phone", "booking_id"):
        if not data.get(key):
            data[key] = fallback.get(key)
    try:
        data["customer_email"] = normalize_email(data.get("customer_email"))
    except ValueError:
        data["customer_email"] = None
    try:
        data["customer_phone"] = normalize_phone(data.get("customer_phone"))
    except ValueError:
        data["customer_phone"] = None
    if data.get("booking_id") is not None:
        try:
            data["booking_id"] = int(data["booking_id"])
            if data["booking_id"] < 1:
                data["booking_id"] = None
        except (TypeError, ValueError):
            data["booking_id"] = None
    # Keep the raw request for context, while storing contact details separately.
    summary = str(data.get("issue_summary") or fallback["issue_summary"]).strip()
    for key in ("customer_email", "customer_phone"):
        value = data.get(key)
        if value:
            summary = summary.replace(value, "[contact detail provided]")
    data["details"] = summary[:1200] or "Customer requested human support."
    data["contact_consent"] = False
    data["preferred_contact_method"] = None
    data["step"] = _first_missing_step(data)
    return _prompt_state(data)


def _first_missing_step(draft: dict) -> str:
    for key, step in (("customer_name", "name"), ("customer_email", "email"), ("customer_phone", "phone")):
        if not draft.get(key):
            return step
    return "preferred_contact" if draft.get("customer_email") or draft.get("customer_phone") else "consent"


def _next_step_after(draft: dict, step: str) -> str:
    if step == "name":
        if not draft.get("customer_email"):
            return "email"
        if not draft.get("customer_phone"):
            return "phone"
    elif step == "email" and not draft.get("customer_phone"):
        return "phone"
    if draft.get("customer_email") or draft.get("customer_phone"):
        return "preferred_contact"
    return "consent"


def _prompt_state(draft: dict) -> dict:
    prompts = {
        "name": "May I have your name? This is optional; reply 'skip' to continue.",
        "email": "Would you like to provide an email address? This is optional; reply 'skip' to continue.",
        "phone": "Would you like to provide a phone number? This is optional; reply 'skip' to continue.",
        "preferred_contact": "Would you prefer the support team to contact you by email or phone? You can reply 'skip'.",
        "consent": "May I share the contact details you provided with your assigned support employee in Slack? Reply yes or no.",
        "confirm": "I have the support details. Reply yes to create your ticket, or 'cancel request' to stop.",
    }
    return {
        "intent": "general", "escalation_draft": draft, "escalation_pending": True,
        "result_data": {"message": prompts[draft["step"]]},
        "pending_action": None, "error": "",
    }


def continue_escalation(draft: dict, message: str) -> dict:
    draft = dict(draft)
    answer = message.strip()
    normalized = answer.casefold()
    extracted = _fallback_extract(answer)
    for key in ("customer_email", "customer_phone", "booking_id"):
        if extracted.get(key):
            draft[key] = extracted[key]
    skip = {"skip", "no", "no thanks", "prefer not", "rather not", "none", "not provided"}
    if normalized in {"cancel request", "cancel escalation", "stop", "never mind", "nevermind"}:
        return {"intent": "general", "escalation_draft": {}, "escalation_pending": False,
                "result_data": {"message": "Okay, I cancelled the support request. No ticket was created."},
                "pending_action": None, "error": ""}
    step = draft.get("step", "name")
    if step == "name":
        repeated_issue = bool(
            extracted.get("customer_email")
            or extracted.get("customer_phone")
            or extracted.get("booking_id")
            or re.search(r"\b(?:human|agent|connect|tickets?|seats?|booking|amount|issue)\b", normalized)
        )
        if normalized not in skip and not repeated_issue:
            draft["customer_name"] = answer[:150]
        draft["step"] = _next_step_after(draft, "name")
    elif step == "email":
        if normalized not in skip:
            match = re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", answer)
            if not match:
                return _prompt_state({**draft, "step": "email"}) | {"result_data": {"message": "Please enter a valid email address or reply 'skip'."}}
            try:
                draft["customer_email"] = normalize_email(match.group(0))
            except ValueError:
                return _prompt_state({**draft, "step": "email"}) | {
                    "result_data": {"message": "Please enter a valid email address or reply 'skip'."}
                }
        draft["step"] = _next_step_after(draft, "email")
    elif step == "phone":
        if normalized not in skip:
            phone = extracted.get("customer_phone") or answer
            try:
                draft["customer_phone"] = normalize_phone(phone)
            except ValueError:
                return _prompt_state({**draft, "step": "phone"}) | {
                    "result_data": {"message": "Please enter a valid phone number with country code if needed, or reply 'skip'."}
                }
        draft["step"] = "preferred_contact" if draft.get("customer_email") or draft.get("customer_phone") else "consent"
    elif step == "preferred_contact":
        choice = normalized.replace("by ", "").strip()
        if choice in {"email", "phone"}:
            if choice == "email" and not draft.get("customer_email"):
                return _prompt_state({**draft, "step": "preferred_contact"}) | {"result_data": {"message": "No email was provided. Choose phone or reply 'skip'."}}
            if choice == "phone" and not draft.get("customer_phone"):
                return _prompt_state({**draft, "step": "preferred_contact"}) | {"result_data": {"message": "No phone number was provided. Choose email or reply 'skip'."}}
            draft["preferred_contact_method"] = choice
        elif choice not in skip:
            return _prompt_state({**draft, "step": "preferred_contact"})
        draft["step"] = "consent"
    elif step == "consent":
        if normalized in {"yes", "yes please", "i agree", "agree", "i consent"}:
            draft["contact_consent"] = True
        elif normalized in {"no", "no thanks", "i do not consent", "decline"}:
            draft["contact_consent"] = False
            draft["preferred_contact_method"] = None
        else:
            return _prompt_state({**draft, "step": "consent"})
        draft["step"] = "confirm"
    elif step == "confirm":
        if normalized not in {"yes", "yes please", "confirm", "create ticket", "go ahead"}:
            return _prompt_state({**draft, "step": "confirm"}) | {"result_data": {"message": "Reply yes to create the support ticket, or 'cancel request' to stop."}}
        return {"intent": "escalate", "escalation_draft": draft, "escalation_pending": False,
                "pending_action": None, "error": ""}
    return _prompt_state(draft)
