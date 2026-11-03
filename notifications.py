"""Slack notifications for SmartBook support escalations.

Notification failures are returned to the caller and never undo a saved ticket.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def send_escalation_to_slack(escalation: dict[str, Any]) -> dict[str, Any]:
    """Post one support escalation to the configured Slack channel.

    Returns {"sent": bool, "message_ts": str|None, "error": str|None}.
    Customer contact details are sent only when the customer consented.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_ESCALATION_CHANNEL_ID", "").strip()
    if not token or not channel:
        return {
            "sent": False,
            "message_ts": None,
            "error": "Slack is not configured. Set SLACK_BOT_TOKEN and SLACK_ESCALATION_CHANNEL_ID.",
        }

    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        client = WebClient(token=token, timeout=10)
        text = _slack_message(escalation)
        response = client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=build_escalation_blocks(escalation),
            mrkdwn=True,
            unfurl_links=False,
            unfurl_media=False,
        )
        return {
            "sent": bool(response.get("ok")),
            "message_ts": response.get("ts"),
            "error": None if response.get("ok") else "Slack did not confirm message delivery.",
        }
    except Exception as exc:  # Slack/API/network errors must not fail escalation creation.
        logger.exception("Slack escalation notification failed")
        message = str(exc)
        # Avoid persisting or exposing request headers/tokens in error strings.
        if "token" in message.casefold() or "authorization" in message.casefold():
            message = "Slack authentication or delivery failed. Check the bot configuration."
        return {"sent": False, "message_ts": None, "error": message[:500]}


def _safe_value(value: Any, fallback: str = "Not provided", limit: int = 2000) -> str:
    if value is None or not str(value).strip():
        return fallback
    # Slack mrkdwn is not HTML; escape angle brackets to prevent accidental links/mentions.
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:limit]


def _contact_values(ticket: dict[str, Any]) -> tuple[str, str, str, str]:
    if not ticket.get("contact_consent"):
        withheld = "Not shared (no consent)"
        return withheld, withheld, withheld, withheld
    return (
        _safe_value(ticket.get("customer_name")),
        _safe_value(ticket.get("customer_email")),
        _safe_value(ticket.get("customer_phone")),
        _safe_value(ticket.get("preferred_contact_method")),
    )


def build_escalation_blocks(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a compact Slack summary, withholding contact details without consent."""
    customer_name, customer_email, customer_phone, preferred_contact = _contact_values(ticket)
    employee = _safe_value(ticket.get("assigned_employee_name"), "Unassigned")
    employee_code = _safe_value(ticket.get("assigned_employee_code"), "Not provided")
    team = _safe_value(ticket.get("assigned_team"), "Unassigned").replace("_", " ").title()
    customer = _safe_value(ticket.get("user_id"))
    if ticket.get("contact_consent"):
        customer = f"{customer}\nName: {customer_name}"
        contact = " | ".join(
            value for value in (customer_email, customer_phone, preferred_contact)
            if value != "Not provided"
        ) or "No contact method provided"
    else:
        contact = "Contact details not shared (no consent)"

    fields = [
        ("Category", _safe_value(ticket.get("reason")).replace("_", " ").title()),
        ("Priority", _safe_value(ticket.get("priority")).title()),
        ("Status", _safe_value(ticket.get("status")).replace("_", " ").title()),
        ("Booking", f"#{_safe_value(ticket.get('booking_id'))}" if ticket.get("booking_id") else "Not provided"),
    ]
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Support escalation #{_safe_value(ticket.get('escalation_id'), limit=100)}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*{label}*\n{value}"}
                for label, value in fields
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Assigned to*\n{employee} ({employee_code})"},
                {"type": "mrkdwn", "text": f"*Team*\n{team}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Customer*\n{customer}"},
                {"type": "mrkdwn", "text": f"*Contact*\n{contact}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Issue details*\n{_safe_value(ticket.get('details'), 'No additional details provided.')}",
            },
        },
    ]
    return blocks


def _slack_message(ticket: dict[str, Any]) -> str:
    customer_name, customer_email, customer_phone, preferred_contact = _contact_values(ticket)
    lines = [
        f"*Support escalation #{_safe_value(ticket.get('escalation_id'))}*",
        (
            f"*Category:* {_safe_value(ticket.get('reason')).replace('_', ' ').title()}  "
            f"*Priority:* {_safe_value(ticket.get('priority')).title()}  "
            f"*Status:* {_safe_value(ticket.get('status')).replace('_', ' ').title()}"
        ),
        (
            f"*Assigned to:* {_safe_value(ticket.get('assigned_employee_name'), 'Unassigned')} "
            f"({_safe_value(ticket.get('assigned_employee_code'), 'Not provided')}) | "
            f"{_safe_value(ticket.get('assigned_team'), 'Unassigned').replace('_', ' ').title()}"
        ),
        f"*Booking:* #{_safe_value(ticket.get('booking_id'))}" if ticket.get("booking_id") else "*Booking:* Not provided",
        f"*Customer:* {_safe_value(ticket.get('user_id'))}",
    ]
    if ticket.get("contact_consent"):
        lines.extend([
            f"*Name:* {customer_name}",
            f"*Contact:* {' | '.join((customer_email, customer_phone, preferred_contact))}",
        ])
    else:
        lines.append("*Contact:* Not shared (no consent)")
    lines.extend(["", "*Issue details*", _safe_value(ticket.get("details"), "No additional details provided.")])
    return "\n".join(lines)
