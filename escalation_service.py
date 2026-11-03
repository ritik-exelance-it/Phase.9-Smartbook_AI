"""Escalation persistence, global employee round robin, and Slack delivery."""
from __future__ import annotations
import re
from typing import Any
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from models import Escalation, SessionLocal, SupportEmployee, SupportAssignmentState, utc_now
from notifications import send_escalation_to_slack

VALID_CATEGORIES = {"booking", "cancellation", "payment_refund", "technical", "account_profile", "general"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


def _assign_next_employee(session) -> SupportEmployee | None:
    """Advance a DB-backed pointer. Caller must hold SQLite BEGIN IMMEDIATE."""
    state = session.get(SupportAssignmentState, 1)
    employees = session.scalars(
        select(SupportEmployee)
        .where(SupportEmployee.active.is_(True), SupportEmployee.employee_code.in_([f"EMP{i:03d}" for i in range(1, 8)]))
        .order_by(SupportEmployee.employee_code)
    ).all()
    if not employees:
        return None
    index = (state.next_employee_index if state else 0) % len(employees)
    employee = employees[index]
    if state is None:
        state = SupportAssignmentState(id=1, next_employee_index=0)
        session.add(state)
    state.next_employee_index = (index + 1) % len(employees)
    state.updated_at = utc_now()
    return employee


def create_support_escalation(*, user_id: str, conversation_id: str, category: str,
    details: str, priority: str = "normal", customer_name: str | None = None,
    customer_email: str | None = None, customer_phone: str | None = None,
    preferred_contact_method: str | None = None, contact_consent: bool = False,
    booking_id: int | None = None) -> dict[str, Any]:
    category = (category or "general").casefold().strip()
    priority = (priority or "normal").casefold().strip()
    if category not in VALID_CATEGORIES: category = "general"
    if priority not in VALID_PRIORITIES: priority = "normal"
    if not user_id or not conversation_id or not details or not details.strip():
        return {"error": "A customer, conversation and issue summary are required."}
    if len(details) > 4000: return {"error": "Issue summary must be 4,000 characters or fewer."}
    if booking_id is not None:
        try:
            booking_id = int(booking_id)
            if booking_id < 1: booking_id = None
        except (TypeError, ValueError): booking_id = None
    customer_email = (customer_email or "").strip()[:254] or None
    customer_phone = (customer_phone or "").strip()[:30] or None
    customer_name = (customer_name or "").strip()[:150] or None
    if customer_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", customer_email):
        return {"error": "The email address is invalid. Please correct it or skip it."}
    if customer_phone and not 7 <= len(re.sub(r"\D", "", customer_phone)) <= 15:
        return {"error": "The phone number is invalid. Please correct it or skip it."}
    if preferred_contact_method not in {None, "email", "phone"}:
        preferred_contact_method = None
    if preferred_contact_method == "email" and not customer_email: preferred_contact_method = None
    if preferred_contact_method == "phone" and not customer_phone: preferred_contact_method = None
    try:
        with SessionLocal() as session:
            # Serialize deduplication + assignment + insert on SQLite.
            session.execute(text("BEGIN IMMEDIATE"))
            existing = session.scalar(select(Escalation).where(
                Escalation.user_id == user_id,
                Escalation.conversation_id == conversation_id,
                Escalation.status.in_(["pending", "assigned", "in_progress"]),
            ).order_by(Escalation.id.desc()))
            if existing:
                result = {"escalation_id": existing.id, "status": existing.status,
                    "slack_status": existing.slack_status,
                    "assigned_employee_name": existing.assigned_employee.name if existing.assigned_employee else None,
                    "message": "Your support request is already recorded."}
                session.rollback()
                return result
            employee = _assign_next_employee(session)
            record = Escalation(
                user_id=user_id, conversation_id=conversation_id, reason=category,
                details=details.strip(), priority=priority,
                status="assigned" if employee else "pending", customer_name=customer_name,
                customer_email=customer_email, customer_phone=customer_phone,
                preferred_contact_method=preferred_contact_method,
                contact_consent=bool(contact_consent), booking_id=booking_id,
                assigned_employee=employee, slack_status="pending")
            session.add(record); session.commit(); session.refresh(record)
            ticket = {"escalation_id": record.id, "user_id": user_id, "reason": category,
                "details": record.details, "priority": priority, "status": record.status,
                "customer_name": customer_name, "customer_email": customer_email,
                "customer_phone": customer_phone, "preferred_contact_method": preferred_contact_method,
                "contact_consent": bool(contact_consent),
                "assigned_employee_name": employee.name if employee else None,
                "assigned_employee_code": employee.employee_code if employee else None,
                "assigned_team": employee.team if employee else None, "booking_id": booking_id}
            notification = send_escalation_to_slack(ticket)
            record.slack_status = "sent" if notification["sent"] else "failed"
            record.slack_message_ts = notification.get("message_ts")
            record.notification_error = notification.get("error")
            record.updated_at = utc_now(); session.commit()
            return {"escalation_id": record.id, "status": record.status,
                "slack_status": record.slack_status,
                "assigned_employee_name": employee.name if employee else None,
                "assigned_employee_code": employee.employee_code if employee else None,
                "assigned_team": employee.team if employee else None,
                "message": "Your support ticket was created and Slack confirmed delivery." if notification["sent"]
                    else "Your support ticket was saved, but Slack delivery could not be confirmed."}
    except SQLAlchemyError:
        return {"error": "The support request could not be saved because of a database error."}
