import os
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch
from notifications import build_escalation_blocks, send_escalation_to_slack

class SlackBlockKitTests(unittest.TestCase):
    def test_block_kit_includes_assignment_and_structured_fields(self):
        blocks = build_escalation_blocks({
            "escalation_id": 22, "reason": "payment_refund", "priority": "high", "status": "assigned",
            "user_id": "guest-22", "customer_name": "Ritik", "customer_email": "r@example.com",
            "customer_phone": "+919999999999", "preferred_contact_method": "email", "contact_consent": True,
            "assigned_employee_name": "Khushi Patel", "assigned_employee_code": "EMP002",
            "assigned_team": "customer_support", "booking_id": 8, "details": "Refund not credited",
        })
        self.assertEqual(blocks[0]["type"], "header")
        rendered = str(blocks)
        for value in ("Khushi Patel", "EMP002", "r@example.com", "9999999999", "payment_refund", "Refund not credited"):
            self.assertIn(value, rendered)

    def test_contacts_are_redacted_without_consent(self):
        rendered = str(build_escalation_blocks({
            "escalation_id": 2, "customer_email": "private@example.com", "customer_phone": "9999999999",
            "customer_name": "Private Name", "contact_consent": False,
        }))
        self.assertNotIn("private@example.com", rendered)
        self.assertNotIn("9999999999", rendered)
        self.assertNotIn("Private Name", rendered)

    def test_slack_sender_posts_blocks_and_redacts_contacts_without_consent(self):
        slack_sdk = ModuleType("slack_sdk")
        web_client = MagicMock()
        web_client.return_value.chat_postMessage.return_value = {
            "ok": True, "ts": "123.456"
        }
        setattr(slack_sdk, "WebClient", web_client)
        slack_errors = ModuleType("slack_sdk.errors")
        setattr(slack_errors, "SlackApiError", Exception)
        ticket = {
            "escalation_id": 2,
            "customer_email": "private@example.com",
            "customer_phone": "9999999999",
            "customer_name": "Private Name",
            "contact_consent": False,
            "details": "Tickets were not received.",
        }
        with (
            patch.dict(os.environ, {
                "SLACK_BOT_TOKEN": "test-token",
                "SLACK_ESCALATION_CHANNEL_ID": "C123",
            }),
            patch.dict(sys.modules, {
                "slack_sdk": slack_sdk,
                "slack_sdk.errors": slack_errors,
            }),
        ):
            result = send_escalation_to_slack(ticket)

        self.assertTrue(result["sent"])
        payload = web_client.return_value.chat_postMessage.call_args.kwargs
        self.assertIn("blocks", payload)
        self.assertNotIn("private@example.com", payload["text"])
        self.assertNotIn("9999999999", payload["text"])
        self.assertNotIn("Private Name", str(payload["blocks"]))

if __name__ == "__main__":
    unittest.main()
