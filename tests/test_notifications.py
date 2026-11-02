import sys
import types
import unittest
from unittest.mock import patch

from notifications import _slack_message, send_escalation_to_slack


class SlackNotificationTests(unittest.TestCase):
    def test_message_contains_assignment_and_customer_contact(self):
        message = _slack_message({
            "escalation_id": 12,
            "reason": "booking",
            "priority": "high",
            "status": "assigned",
            "user_id": "guest-1",
            "customer_name": "Demo Customer",
            "preferred_contact_method": "email",
            "customer_email": "demo@example.com",
            "customer_phone": None,
            "assigned_employee_name": "Support Agent",
            "assigned_team": "booking_support",
            "booking_id": 45,
            "details": "Payment completed but ticket missing <check>",
        })
        self.assertIn("#12", message)
        self.assertIn("Support Agent", message)
        self.assertIn("demo@example.com", message)
        self.assertIn("booking_support", message)
        self.assertIn("&lt;check&gt;", message)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_configuration_returns_failure_without_exception(self):
        result = send_escalation_to_slack({"escalation_id": 1})
        self.assertFalse(result["sent"])
        self.assertIsNone(result["message_ts"])
        self.assertIn("not configured", result["error"])

    @patch.dict("os.environ", {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_ESCALATION_CHANNEL_ID": "C123456",
    })
    def test_slack_failure_is_returned_not_raised(self):
        fake_sdk = types.ModuleType("slack_sdk")
        class FakeWebClient:
            def __init__(self, **kwargs):
                pass

            def chat_postMessage(self, **kwargs):
                raise RuntimeError("network error")

        fake_sdk.WebClient = FakeWebClient
        fake_errors = types.ModuleType("slack_sdk.errors")
        fake_errors.SlackApiError = RuntimeError
        with patch.dict(sys.modules, {"slack_sdk": fake_sdk, "slack_sdk.errors": fake_errors}):
            result = send_escalation_to_slack({"escalation_id": 1})
        self.assertFalse(result["sent"])
        self.assertIn("network error", result["error"])


if __name__ == "__main__":
    unittest.main()
