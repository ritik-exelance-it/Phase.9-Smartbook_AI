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
    No customer contact details are sent unless explicitly supplied to the
    escalation record; keep the target channel restricted to support staff.
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


def _slack_message(ticket: dict[str, Any]) -> str:
    def safe(value: Any, fallback: str = "Not provided") -> str:
        if value is None or not str(value).strip():
            return fallback
        # Slack mrkdwn is not HTML; escape angle brackets to prevent accidental links/mentions.
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:2000]

    return "\n".join(
        [
            f"*New SmartBook support escalation — #{safe(ticket.get('escalation_id'))}*",
            f"*Category:* {safe(ticket.get('reason'))}",
            f"*Priority:* {safe(ticket.get('priority'))}",
            f"*Status:* {safe(ticket.get('status'))}",
            f"*Customer ID:* {safe(ticket.get('user_id'))}",
            f"*Customer name:* {safe(ticket.get('customer_name'))}",
            f"*Preferred contact:* {safe(ticket.get('preferred_contact_method'))}",
            f"*Email:* {safe(ticket.get('customer_email'))}",
            f"*Phone:* {safe(ticket.get('customer_phone'))}",
            f"*Assigned employee:* {safe(ticket.get('assigned_employee_name'), 'Unassigned')}",
            f"*Assigned team:* {safe(ticket.get('assigned_team'), 'Unassigned')}",
            f"*Booking ID:* {safe(ticket.get('booking_id'))}",
            "*Issue details:*",
            safe(ticket.get("details"), "No additional details provided."),
        ]
    )
