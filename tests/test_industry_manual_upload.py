import os
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp


def complete_form():
    form = {
        "ind_industry": "Automotive",
        "ind_hero_title": "Saudi Arabia's Automotive Market Is Changing",
        "ind_hero_body": "Vision 2030 is reshaping automotive competition.",
    }
    for number in (1, 2, 3):
        form[f"ind_dev{number}_title"] = f"Development headline {number}"
        form[f"ind_dev{number}_body"] = f"Development summary {number}"
    return form


def png_upload():
    buffer = BytesIO()
    Image.new("RGB", (900, 500), (30, 90, 150)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class IndustryManualUploadTests(unittest.TestCase):
    def setUp(self):
        webapp.app.config.update(TESTING=True)
        self.client = webapp.app.test_client()

    def test_send_dashboard_exposes_manual_upload_workflow(self):
        response = self.client.get("/send")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"1. Hero", response.data)
        self.assertIn("Transition · 572 × 606".encode(), response.data)
        self.assertIn(b'ind_upload_hero', response.data)
        self.assertNotIn(b"Generate images from content", response.data)

    @patch.object(webapp, "_stored_image_payload")
    @patch.object(webapp, "_store_generated_images")
    def test_uploaded_gpt_image_uses_existing_preview_storage(self, store, payload):
        payload.return_value = {
            "hero": {"url": "/generated/token/hero?v=1", "placeholder": False}
        }
        form = complete_form()
        form["ind_image_token"] = "token"
        form["ind_upload_hero"] = (png_upload(), "hero.png")

        response = self.client.post(
            "/api/newsletter/industry-images/upload",
            data=form,
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("partial", response.get_json()["status"])
        self.assertEqual(["dev1", "dev2", "dev3"], response.get_json()["missing"])
        stored = store.call_args.args[1]
        self.assertEqual({"hero"}, set(stored))
        self.assertFalse(stored["hero"][1])


if __name__ == "__main__":
    unittest.main()
