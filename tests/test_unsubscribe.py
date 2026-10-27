import base64
import unittest

from send_email import _mime_message
from unsubscribe import (
    InvalidUnsubscribeToken,
    create_unsubscribe_token,
    masked_email,
    normalize_email,
    read_unsubscribe_token,
)


class UnsubscribeTokenTests(unittest.TestCase):
    def test_signed_token_round_trip_normalizes_recipient(self):
        token = create_unsubscribe_token(
            "  Vansh.Meena@KenResearch.com ",
            campaign_id="camp_live",
            secret="unit-test-secret",
        )
        payload = read_unsubscribe_token(token, secret="unit-test-secret")
        self.assertEqual(payload["email"], "vansh.meena@kenresearch.com")
        self.assertEqual(payload["campaign_id"], "camp_live")
        self.assertEqual(payload["scope"], "all_newsletters")

    def test_tampered_token_is_rejected(self):
        token = create_unsubscribe_token("reader@example.com", secret="unit-test-secret")
        with self.assertRaises(InvalidUnsubscribeToken):
            read_unsubscribe_token(token + "tampered", secret="unit-test-secret")

    def test_masked_email_hides_most_of_local_part(self):
        self.assertEqual(masked_email("vansh.meena@example.com"), "va*********@example.com")
        self.assertEqual(normalize_email(" Test@Example.COM "), "test@example.com")


class MimeUnsubscribeTests(unittest.TestCase):
    def test_mime_message_contains_one_click_headers_and_inline_asset(self):
        encoded = _mime_message(
            {"email": "updates@kenresearch.com"},
            "reader@example.com",
            "Newsletter",
            '<html><img src="cid:logo.png"></html>',
            [{
                "name": "logo.png",
                "contentType": "image/png",
                "contentBytes": base64.b64encode(b"fake-png").decode("ascii"),
                "contentId": "logo.png",
                "isInline": True,
            }],
            "https://preferences.example.com/unsubscribe/signed-token",
        )
        raw = base64.b64decode(encoded).decode("utf-8", errors="replace")
        self.assertIn("List-Unsubscribe:", raw)
        self.assertIn("preferences.example.com/unsubscribe/signed-token", raw)
        self.assertIn("List-Unsubscribe-Post: List-Unsubscribe=One-Click", raw)
        self.assertIn("Content-ID: <logo.png>", raw)


if __name__ == "__main__":
    unittest.main()
