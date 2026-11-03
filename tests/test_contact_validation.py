import unittest
from contact_validation import normalize_email, normalize_phone

class ContactValidationTests(unittest.TestCase):
    def test_email_trim_and_domain_case(self):
        self.assertEqual(normalize_email(" User.Name@EXAMPLE.COM "), "User.Name@example.com")

    def test_blank_email_is_optional(self):
        self.assertIsNone(normalize_email(" "))

    def test_invalid_emails(self):
        for value in ("not-an-email", "a@b", "a b@example.com", "@example.com"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_email(value)

    def test_indian_phone_e164(self):
        self.assertEqual(normalize_phone("099999 99999"), "+919999999999")
        self.assertEqual(normalize_phone("+91 99999-99999"), "+919999999999")

    def test_blank_phone_is_optional(self):
        self.assertIsNone(normalize_phone(""))

    def test_invalid_phones(self):
        for value in ("12345", "abcdefghijk", "+999123456789"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_phone(value)

if __name__ == "__main__":
    unittest.main()
