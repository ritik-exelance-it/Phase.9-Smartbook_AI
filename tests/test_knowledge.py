import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import knowledge


class KnowledgeRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb_path = Path(self.temp_dir.name)
        (self.kb_path / "cinema_faq.md").write_text(
            "# SmartBook Help\n\n"
            "## Cancellation and refunds\n"
            "The demo can record cancellation for an eligible confirmed booking. "
            "It does not connect to a payment processor or issue money.\n\n"
            "## Making a booking\n"
            "A booking needs a movie, customer name, and a positive whole number of seats.\n\n"
            "## Privacy and permissions\n"
            "Customers may view or cancel only bookings belonging to their own application user ID.\n",
            encoding="utf-8",
        )
        self.patch_dir = patch.object(knowledge, "KNOWLEDGE_DIR", self.kb_path)
        self.patch_dir.start()

    def tearDown(self):
        self.patch_dir.stop()
        self.temp_dir.cleanup()

    def test_relevant_cancellation_question_returns_source_and_section(self):
        results = knowledge.retrieve_knowledge_results(
            "Can I cancel a booking and get a refund?"
        )
        self.assertTrue(results)
        self.assertEqual(results[0].section, "SmartBook Help > Cancellation and refunds")
        self.assertEqual(results[0].source, "cinema_faq.md")
        self.assertIn("payment processor", results[0].content)

    def test_unrelated_question_returns_no_passage(self):
        self.assertEqual(
            knowledge.retrieve_knowledge_results("What food is served at the cinema?"),
            [],
        )

    def test_formatted_retrieval_keeps_existing_string_interface(self):
        context = knowledge.retrieve_knowledge("How do refunds work?")
        self.assertIsInstance(context, str)
        self.assertIn("Source: cinema_faq.md", context)
        self.assertIn("Section: SmartBook Help > Cancellation and refunds", context)

    def test_empty_query_returns_no_results(self):
        self.assertEqual(knowledge.retrieve_knowledge_results("the and is"), [])

    def test_max_chunks_is_respected(self):
        results = knowledge.retrieve_knowledge_results(
            "booking cancellation customer movie seats", max_chunks=1
        )
        self.assertLessEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
