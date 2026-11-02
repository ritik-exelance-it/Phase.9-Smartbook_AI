import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import escalation_service
from models import Base, Escalation, SupportEmployee


class EscalationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 'support.db'}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session_patch = patch.object(escalation_service, "SessionLocal", self.session_factory)
        self.session_patch.start()
        with self.session_factory.begin() as session:
            session.add_all([
                SupportEmployee(name="Booking Agent", team="booking_support", email="booking@example.com", active=True),
                SupportEmployee(name="Billing Agent", team="billing_support", email="billing@example.com", active=True),
            ])

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": True, "message_ts": "123.456", "error": None})
    def test_create_escalation_assigns_employee_and_records_slack(self, notify):
        result = escalation_service.create_support_escalation(
            user_id="guest-a", conversation_id="conv-a", category="booking",
            details="I paid but got no ticket.", customer_name="Test Customer",
            customer_email="test@example.com", preferred_contact_method="email",
            contact_consent=True,
        )
        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["slack_status"], "sent")
        self.assertEqual(result["assigned_employee_name"], "Booking Agent")
        notify.assert_called_once()
        with self.session_factory() as session:
            row = session.get(Escalation, result["escalation_id"])
            self.assertEqual(row.customer_email, "test@example.com")
            self.assertTrue(row.contact_consent)
            self.assertEqual(row.slack_message_ts, "123.456")

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": False, "message_ts": None, "error": "Slack unavailable"})
    def test_notification_failure_does_not_delete_saved_escalation(self, _notify):
        result = escalation_service.create_support_escalation(
            user_id="guest-b", conversation_id="conv-b", category="billing",
            details="Please check my payment.",
        )
        self.assertEqual(result["slack_status"], "failed")
        with self.session_factory() as session:
            rows = session.query(Escalation).filter_by(user_id="guest-b").all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].details, "Please check my payment.")

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": True, "message_ts": "1.2", "error": None})
    def test_duplicate_open_ticket_is_reused(self, notify):
        first = escalation_service.create_support_escalation(
            user_id="guest-c", conversation_id="conv-c", category="technical", details="App crashed"
        )
        second = escalation_service.create_support_escalation(
            user_id="guest-c", conversation_id="conv-c", category="technical", details="Retry after timeout"
        )
        self.assertEqual(first["escalation_id"], second["escalation_id"])
        notify.assert_called_once()

    def test_contact_requires_consent_and_valid_data(self):
        no_consent = escalation_service.create_support_escalation(
            user_id="guest-d", conversation_id="conv-d", category="general",
            details="Need help", customer_email="private@example.com",
        )
        self.assertNotIn("error", no_consent)
        with self.session_factory() as session:
            row = session.query(Escalation).filter_by(user_id="guest-d").one()
            self.assertIsNone(row.customer_email)

        invalid = escalation_service.create_support_escalation(
            user_id="guest-e", conversation_id="conv-e", category="general",
            details="Need help", customer_email="not-an-email",
            preferred_contact_method="email", contact_consent=True,
        )
        self.assertIn("error", invalid)


if __name__ == "__main__":
    unittest.main()
