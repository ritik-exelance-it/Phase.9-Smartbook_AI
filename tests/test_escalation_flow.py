import unittest
from unittest.mock import patch
import agent
from escalation_flow import begin_escalation, continue_escalation

class FakeResult:
    def model_dump(self):
        return {"category": "cancellation", "priority": "high", "issue_summary": "Cancellation refund not credited.",
                "customer_name": None, "customer_email": "user@example.com", "customer_phone": "+919999999999", "booking_id": 17}
class FakeLLM:
    def invoke(self, _messages): return FakeResult()

class EscalationFlowTests(unittest.TestCase):
    def test_follow_up_can_add_contact_and_booking_details_during_name_prompt(self):
        state = begin_escalation(
            "I am booking number 2. I did not get my tickets and the seat amount is different. Connect me to a human.",
            None,
        )
        draft = state["escalation_draft"]
        self.assertEqual(draft["step"], "name")
        self.assertEqual(draft["booking_id"], 2)

        state = continue_escalation(
            draft,
            "I am booking number 2, I have a ticket issue. I did not get tickets and the seat amount is different. "
            "Connect me to a human; my email is customer@example.com.",
        )
        draft = state["escalation_draft"]
        self.assertIsNone(draft.get("customer_name"))
        self.assertEqual(draft["customer_email"], "customer@example.com")
        self.assertEqual(draft["booking_id"], 2)
        self.assertEqual(draft["step"], "phone")

    def test_agent_preserves_escalation_prompts_instead_of_claiming_handoff(self):
        first_message = (
            "I am booking number 2. I did not get my tickets and the seat amount is different. "
            "Connect me to a human."
        )
        initial = begin_escalation(first_message, None)
        with patch("agent.begin_escalation", return_value=initial):
            classified = agent.classify_node(
                {"user_message": first_message, "role": "customer"}
            )
        with patch("agent.create_support_escalation") as create_ticket:
            execution = agent.execute_node(classified)
            create_ticket.assert_not_called()
        response = agent.respond_node(classified | execution)["response"]
        self.assertIn("May I have your name?", response)
        self.assertNotIn("connect you", response.casefold())

        follow_up = (
            "I am booking number 2, I have a ticket issue. I did not get tickets and the seat amount is "
            "different. Connect me to a human; my email is customer@example.com."
        )
        classified = agent.classify_node({
            "user_message": follow_up,
            "role": "customer",
            "escalation_draft": initial["escalation_draft"],
        })
        with patch("agent.create_support_escalation") as create_ticket:
            execution = agent.execute_node(classified)
            create_ticket.assert_not_called()
        response = agent.respond_node(classified | execution)["response"]
        self.assertIn("phone number", response)
        self.assertNotIn("connect you", response.casefold())

    def test_extracts_existing_details_before_asking_for_missing_name(self):
        state = begin_escalation("Need a human. Booking id 17, email user@example.com, phone +919999999999; cancellation refund missing.", FakeLLM())
        draft = state["escalation_draft"]
        self.assertEqual(draft["category"], "cancellation")
        self.assertEqual(draft["priority"], "high")
        self.assertEqual(draft["booking_id"], 17)
        self.assertEqual(draft["customer_email"], "user@example.com")
        self.assertEqual(draft["customer_phone"], "+919999999999")
        self.assertEqual(draft["step"], "name")

    def test_skip_each_optional_field_and_create_without_contact(self):
        draft = {"category": "general", "priority": "normal", "details": "Help", "step": "name"}
        for answer in ("skip", "skip", "skip"):
            state = continue_escalation(draft, answer)
            draft = state["escalation_draft"]
        self.assertEqual(draft["step"], "consent")
        state = continue_escalation(draft, "no")
        draft = state["escalation_draft"]
        state = continue_escalation(draft, "yes")
        self.assertEqual(state["intent"], "escalate")
        self.assertFalse(state["escalation_draft"]["contact_consent"])

if __name__ == "__main__": unittest.main()
