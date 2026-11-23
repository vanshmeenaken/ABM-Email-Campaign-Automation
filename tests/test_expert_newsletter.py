import os
import re
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp

from newsletter_expert import (
    CANVAS_WIDTH,
    EXPERT_SLOTS,
    ICON_FILES,
    IMAGE_FILES,
    SLOT_SIZES,
    expert_content,
    prepare_expert_image,
    render_expert_newsletter,
    resolved_expert_links,
    validate_expert_content,
)


def complete_form():
    return {
        "exp_section_label": "Expert's Desk",
        "exp_issue_label": "November 2026 | Issue 02",
        "exp_hero_label": "Expert Interview",
        "exp_hero_title": "India's Data Centre Busbar Opportunity",
        "exp_hero_body": "AI infrastructure is pushing power requirements higher.",
        "exp_hero_cta_text": "Read the Full Expert Interview",
        "exp_hero_cta_url": "https://example.com/interview",
        "exp_expert_name": "Manish Israni",
        "exp_expert_role": "Chief Operating Officer",
        "exp_expert_company": "Olive Intelligence Pvt. Ltd.",
        "exp_takeaway1_title": "AI redefines power distribution",
        "exp_takeaway1_body": "High-density racks require modular distribution.",
        "exp_takeaway2_title": "Approval determines access",
        "exp_takeaway2_body": "Compliance and EPC specifications shape selection.",
        "exp_takeaway3_title": "Localisation must deliver reliability",
        "exp_takeaway3_body": "Suppliers need economics and proven performance.",
        "exp_report_title": "India Data Centre Colocation Competition Benchmarking 2025",
        "exp_report_body": "Benchmark capacity, presence and competitive positioning.",
        "exp_report_cta_text": "Explore the Data Centre Benchmarking",
        "exp_report_cta_url": "https://example.com/report",
    }


def png_upload(width=900, height=700):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (29, 65, 112)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class ExpertNewsletterTests(unittest.TestCase):
    def setUp(self):
        webapp.app.config.update(TESTING=True)
        self.client = webapp.app.test_client()

    def test_required_content_and_links_are_validated(self):
        self.assertEqual([], validate_expert_content(expert_content(complete_form())))

        form = complete_form()
        form["exp_expert_name"] = ""
        form["exp_report_cta_url"] = "not-a-url"
        problems = validate_expert_content(expert_content(form))
        self.assertIn("Expert name is required.", problems)
        self.assertIn(
            "Featured intelligence link must be a complete http:// or https:// URL.",
            problems,
        )

        form = complete_form()
        form["exp_hero_cta_url"] = "https://www.kenresearch.com/"
        form["exp_report_cta_url"] = "https://kenresearch.com"
        problems = validate_expert_content(expert_content(form))
        self.assertIn(
            "Expert interview link cannot use the generic Ken Research homepage.", problems
        )
        self.assertIn(
            "Featured intelligence link cannot use the generic Ken Research homepage.",
            problems,
        )

    def test_renderer_matches_reference_sections_and_official_logo(self):
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_expert_newsletter(complete_form(), "cid", sources)

        self.assertEqual(720, CANVAS_WIDTH)
        self.assertIn('width="720"', html)
        self.assertIn("Expert&#x27;s Desk", html)
        self.assertIn("Expert Interview", html)
        self.assertIn("Meet the Expert", html)
        self.assertIn("Key Takeaways from the Conversation", html)
        self.assertIn("Featured Market Intelligence", html)
        self.assertIn("Manish Israni", html)
        self.assertIn("cid:ken-research-logo-color.png", html)
        for filename in IMAGE_FILES.values():
            self.assertIn(f"cid:{filename}", html)
        for filename in ICON_FILES.values():
            self.assertIn(f"cid:{filename}", html)
        self.assertNotIn("Manage Preferences", html)

    def test_hero_image_height_adapts_to_copy(self):
        form = complete_form()
        form["exp_hero_body"] = "Short summary."
        short_html = render_expert_newsletter(form, "cid", {"hero": "cid:expert-desk-hero.jpg"})
        form["exp_hero_body"] = "Long expert summary. " * 30
        long_html = render_expert_newsletter(form, "cid", {"hero": "cid:expert-desk-hero.jpg"})

        pattern = r'src="cid:expert-desk-hero\.jpg" width="400" height="(\d+)"'
        short_height = int(re.search(pattern, short_html).group(1))
        long_height = int(re.search(pattern, long_html).group(1))
        self.assertGreater(long_height, short_height)
        self.assertGreaterEqual(short_height, 230)
        self.assertLessEqual(long_height, 390)

    def test_links_append_utms_without_overwriting_existing_source(self):
        form = complete_form()
        form.update({
            "exp_utm_source": "expert-team",
            "exp_utm_medium": "email",
            "exp_utm_campaign": "data-centres",
            "exp_hero_cta_url": "https://example.com/interview?utm_source=editor&ref=dashboard",
        })
        links = resolved_expert_links(expert_content(form))
        self.assertIn("utm_source=editor", links["Expert interview"])
        self.assertNotIn("utm_source=expert-team", links["Expert interview"])
        self.assertIn("utm_campaign=data-centres", links["Expert interview"])
        self.assertIn("ref=dashboard", links["Expert interview"])

    def test_uploaded_images_are_normalized_to_each_slot(self):
        for slot in EXPERT_SLOTS:
            result = prepare_expert_image(slot, png_upload().getvalue())
            with Image.open(BytesIO(result)) as output:
                self.assertEqual(SLOT_SIZES[slot], output.size)
                self.assertEqual("JPEG", output.format)

    def test_dashboard_exposes_expert_builder_and_three_uploads(self):
        response = self.client.get("/send")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Expert's Desk", response.data)
        self.assertIn(b'exp_upload_hero', response.data)
        self.assertIn(b'exp_upload_portrait', response.data)
        self.assertIn(b'exp_upload_report', response.data)
        self.assertIn(b"Manish Israni", response.data)

    def test_link_review_api_returns_direct_utm_urls(self):
        response = self.client.post("/api/newsletter/expert-links", data=complete_form())
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["click_tracking"])
        self.assertEqual([], payload["errors"])
        self.assertEqual(
            "https://example.com/report?utm_source=newsletter&utm_medium=email&utm_campaign=experts_desk",
            payload["links"]["Featured intelligence"],
        )

    @patch.object(webapp, "_stored_image_payload")
    @patch.object(webapp, "_store_generated_images")
    def test_image_upload_uses_shared_storage(self, store, payload):
        payload.return_value = {
            "hero": {"url": "/generated/token/hero?v=1", "placeholder": False}
        }
        form = complete_form()
        form["exp_image_token"] = "token"
        form["exp_upload_hero"] = (png_upload(), "hero.png")
        response = self.client.post(
            "/api/newsletter/expert-images/upload",
            data=form,
            content_type="multipart/form-data",
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("partial", response.get_json()["status"])
        self.assertEqual(["portrait", "report"], response.get_json()["missing"])
        self.assertEqual({"hero"}, set(store.call_args.args[1]))

    @patch.object(webapp, "query_db")
    def test_preview_uses_all_uploaded_images(self, query_db):
        query_db.return_value = [{"slot": slot} for slot in EXPERT_SLOTS]
        form = complete_form()
        form["exp_image_token"] = "token"
        response = self.client.post("/newsletter/expert-preview", data=form)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Expert&#39;s Desk preview", response.data)
        for slot in EXPERT_SLOTS:
            self.assertIn(f"/generated/token/{slot}".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
