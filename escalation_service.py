"""Persistence and routing for customer human-support escalations."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from models import Escalation, SessionLocal, SupportEmployee, utc_now
from notifications import send_escalation_to_slack

VALID_CATEGORIES = {
    "booking": "booking_support",
    "payment": "billing_support",
    "billing": "billing_support",
    "technical": "technical_support",
    "customer_support": "customer_support",
    "general": "customer_support",
}


def _valid_contact(method: str | None, email: str | None, phone: str | None) -> tuple[bool, str | None]:
    method = (method or "").strip().casefold()
    if method not in {"email", "phone"}:
        return False, "Please choose email or phone as your preferred contact method."
    if method == "email":
        candidate = (email or "").strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", candidate):
            return False, "Please provide a valid email address."
    if method == "phone":
        digits = re.sub(r"\D", "", phone or "")
        if not 7 <= len(digits) <= 15:
            return False, "Please provide a valid phone number, including the country code when needed."
    return True, None


def _assign_employee(session, category: str) -> SupportEmployee | None:
    team = VALID_CATEGORIES.get(category.casefold(), "customer_support")
    # Small deterministic least-loaded assignment. If no employee is configured,
    # leave the ticket unassigned rather than inventing an employee.
    candidates = session.scalars(
        select(SupportEmployee)
        .where(SupportEmployee.active.is_(True), SupportEmployee.team == team)
        .order_by(SupportEmployee.id)
    ).all()
    if not candidates and team != "customer_support":
        candidates = session.scalars(
            select(SupportEmployee)
            .where(SupportEmployee.active.is_(True), SupportEmployee.team == "customer_support")
            .order_by(SupportEmployee.id)
        ).all()
    if not candidates:
        return None
    open_counts = {
        employee.id: session.query(Escalation).filter(
            Escalation.assigned_employee_id == employee.id,
            Escalation.status.in_(["assigned", "in_progress", "pending"]),
        ).count()
        for employee in candidates
    }
    eligible = [
        employee for employee in candidates
        if employee.max_open_tickets is None
        or open_counts[employee.id] < employee.max_open_tickets
    ]
    return min(eligible or candidates, key=lambda employee: (open_counts[employee.id], employee.id)) if eligible else None


def create_support_escalation(
    *,
    user_id: str,
    conversation_id: str,
    category: str,
    details: str,
    priority: str = "normal",
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    preferred_contact_method: str | None = None,
    contact_consent: bool = False,
    booking_id: int | None = None,
) -> dict[str, Any]:
    category = (category or "general").strip().casefold()
    if category not in VALID_CATEGORIES:
        category = "general"
    if not user_id or not conversation_id:
        return {"error": "A valid customer and conversation are required to create an escalation."}
    if not details or not details.strip():
        return {"error": "Please provide a short description of the issue."}
    if len(details) > 4000:
        return {"error": "Please keep the issue description under 4,000 characters."}
    if contact_consent:
        valid, error = _valid_contact(preferred_contact_method, customer_email, customer_phone)
        if not valid:
            return {"error": error}
    else:
        customer_email = None
        customer_phone = None
        preferred_contact_method = None

    try:
        with SessionLocal() as session:
            # A pending ticket from the same conversation is reused to protect
            # against accidental duplicate tool calls/retries.
            existing = session.scalar(
                select(Escalation)
                .where(
                    Escalation.user_id == user_id,
                    Escalation.conversation_id == conversation_id,
                    Escalation.status.in_(["pending", "assigned", "in_progress"]),
                )
                .order_by(Escalation.id.desc())
            )
            if existing:
                return {
                    "escalation_id": existing.id,
                    "status": existing.status,
                    "slack_status": existing.slack_status,
                    "assigned_employee_name": existing.assigned_employee.name if existing.assigned_employee else None,
                    "message": "Your support request is already recorded.",
                }

            employee = _assign_employee(session, category)
            record = Escalation(
                user_id=user_id,
                conversation_id=conversation_id,
                reason=category,
                details=details.strip(),
                priority=priority if priority in {"low", "normal", "high", "urgent"} else "normal",
                status="assigned" if employee else "pending",
                customer_name=(customer_name or "").strip()[:150] or None,
                customer_email=(customer_email or "").strip()[:254] or None,
                customer_phone=(customer_phone or "").strip()[:30] or None,
                preferred_contact_method=preferred_contact_method if contact_consent else None,
                contact_consent=bool(contact_consent),
                booking_id=booking_id,
                assigned_employee=employee,
                slack_status="pending",
            )
            session.add(record)
            session.commit()
            session.refresh(record)

            employee_name = employee.name if employee else None
            employee_team = employee.team if employee else None
            ticket = {
                "escalation_id": record.id,
                "user_id": user_id,
                "reason": category,
                "details": record.details,
                "priority": record.priority,
                "status": record.status,
                "customer_name": record.customer_name,
                "customer_email": record.customer_email,
                "customer_phone": record.customer_phone,
                "preferred_contact_method": record.preferred_contact_method,
                "assigned_employee_name": employee_name,
                "assigned_team": employee_team,
                "booking_id": booking_id,
            }
            # Commit the support ticket before calling an external service.
            notification = send_escalation_to_slack(ticket)
            record.slack_status = "sent" if notification["sent"] else "failed"
            record.slack_message_ts = notification.get("message_ts")
            record.notification_error = notification.get("error")
            record.updated_at = utc_now()
            session.commit()

            return {
                "escalation_id": record.id,
                "status": record.status,
                "slack_status": record.slack_status,
                "assigned_employee_name": employee_name,
                "assigned_team": employee_team,
                "notification_error": notification.get("error"),
                "message": (
                    "Your request has been recorded and the support team was notified."
                    if notification["sent"]
                    else "Your request has been saved. The Slack notification could not be confirmed; the support record is retained."
                ),
            }
    except SQLAlchemyError:
        return {"error": "Your support request could not be saved because of a database error. Please try again."}
