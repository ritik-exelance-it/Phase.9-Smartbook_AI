import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import escalation_service
from models import Base, Escalation, SupportEmployee, SupportAssignmentState

NAMES = ["Ritik Mishra", "Khushi Patel", "Sairam Madduri", "Anshika Dixit", "Akash Sahoo", "Devyani Patil", "Ayush Singh"]

class EscalationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'support.db'}")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patch = patch.object(escalation_service, "SessionLocal", self.factory)
        self.patch.start()
        with self.factory.begin() as session:
            session.add_all([
                SupportEmployee(employee_code=f"EMP{i:03d}", name=name, team="customer_support", email=f"emp{i}@example.invalid", active=True)
                for i, name in enumerate(NAMES, 1)
            ])
            session.add(SupportAssignmentState(id=1, next_employee_index=0))

    def tearDown(self):
        self.patch.stop(); self.engine.dispose(); self.temp.cleanup()

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": True, "message_ts": "123.456", "error": None})
    def test_global_round_robin_cycles_after_seven(self, notify):
        assigned = []
        for i in range(8):
            result = escalation_service.create_support_escalation(
                user_id=f"guest-{i}", conversation_id=f"conv-{i}",
                category="payment_refund" if i % 2 else "booking",
                priority="high", details=f"Issue {i}", booking_id=100 + i,
            )
            assigned.append(result["assigned_employee_name"])
        self.assertEqual(assigned, NAMES + [NAMES[0]])
        self.assertEqual(notify.call_count, 8)

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": True, "message_ts": "1.2", "error": None})
    def test_duplicate_open_ticket_does_not_consume_next_employee(self, notify):
        first = escalation_service.create_support_escalation(user_id="g", conversation_id="c", category="general", details="First")
        second = escalation_service.create_support_escalation(user_id="g", conversation_id="c", category="general", details="Retry")
        third = escalation_service.create_support_escalation(user_id="g2", conversation_id="c2", category="general", details="Next")
        self.assertEqual(first["escalation_id"], second["escalation_id"])
        self.assertEqual(first["assigned_employee_name"], NAMES[0])
        self.assertEqual(third["assigned_employee_name"], NAMES[1])
        self.assertEqual(notify.call_count, 2)

    @patch("escalation_service.send_escalation_to_slack", return_value={"sent": False, "message_ts": None, "error": "offline"})
    def test_notification_failure_keeps_ticket_and_customer_details(self, _notify):
        result = escalation_service.create_support_escalation(
            user_id="g", conversation_id="c", category="cancellation", details="Refund missing",
            customer_name="A Customer", customer_email="a@example.com", customer_phone="+919999999999",
            preferred_contact_method="email", contact_consent=False,
        )
        self.assertEqual(result["slack_status"], "failed")
        with self.factory() as session:
            row = session.query(Escalation).filter_by(user_id="g").one()
            self.assertEqual(row.customer_email, "a@example.com")
            self.assertEqual(row.customer_phone, "+919999999999")
            self.assertFalse(row.contact_consent)
            self.assertEqual(row.reason, "cancellation")

    def test_invalid_contact_rejected(self):
        result = escalation_service.create_support_escalation(
            user_id="g", conversation_id="c", category="general", details="Help",
            customer_email="bad-email",
        )
        self.assertIn("error", result)

if __name__ == "__main__":
    unittest.main()
