import os
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp

from newsletter_regional import (
    CANVAS_WIDTH,
    IMAGE_FILES,
    REGIONAL_SLOTS,
    SLOT_SIZES,
    prepare_regional_image,
    regional_content,
    render_regional_newsletter,
    resolved_regional_links,
    validate_regional_content,
)


def complete_form():
    form = {
        "reg_section_label": "Regional Market Outlook",
        "reg_issue_label": "Oct 2026 | Issue 01",
        "reg_region": "India",
        "reg_hero_title": "India's Healthcare Sector Enters a New Growth Phase",
        "reg_hero_body": "Government support and digital adoption are reshaping healthcare.",
        "reg_hero_cta_text": "Read the Full Perspective",
        "reg_hero_cta_url": "https://example.com/hero",
        "reg_insights_heading": "Key Insights",
        "reg_report_label": "Final File Report",
        "reg_report_title": "India Healthcare Market Outlook, 2026-2032",
        "reg_report_body": "Detailed insights on market size and competition.",
        "reg_report_cta_text": "View Report",
        "reg_report_cta_url": "https://example.com/report",
    }
    for number in range(1, 5):
        form[f"reg_indicator{number}"] = f"Market indicator {number}"
    for number in range(1, 4):
        form[f"reg_insight{number}_title"] = f"Insight {number}"
        form[f"reg_insight{number}_body"] = f"Insight summary {number}"
        form[f"reg_insight{number}_url"] = f"https://example.com/insight-{number}"
    return form


def png_upload(width=900, height=700):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (34, 92, 148)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class RegionalNewsletterTests(unittest.TestCase):
    def setUp(self):
        webapp.app.config.update(TESTING=True)
        self.client = webapp.app.test_client()

    def test_content_validates_and_missing_fields_are_reported(self):
        content = regional_content(complete_form())
        self.assertEqual([], validate_regional_content(content))

        form = complete_form()
        form["reg_hero_title"] = ""
        form["reg_insight2_body"] = ""
        problems = validate_regional_content(regional_content(form))
        self.assertIn("Hero headline is required.", problems)
        self.assertIn("Insight 2 summary is required.", problems)

    def test_renderer_matches_regional_structure_and_real_brand_assets(self):
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_regional_newsletter(complete_form(), "cid", sources)

        self.assertEqual(600, CANVAS_WIDTH)
        self.assertIn('width="600"', html)
        self.assertIn("Regional Focus: India", html)
        self.assertIn("Key Insights", html)
        self.assertIn("Final File Report", html)
        self.assertIn("cid:regional-ken-research-logo.png", html)
        for number in range(1, 5):
            self.assertIn(f"cid:regional-indicator-{number}.png", html)
        self.assertIn("cid:mailmodo-linkedin.png", html)
        self.assertIn("cid:mailmodo-twitter.png", html)
        self.assertIn("cid:mailmodo-youtube.png", html)
        self.assertIn("cid:regional-hero.jpg", html)
        self.assertIn("cid:regional-insights.jpg", html)
        self.assertIn("cid:regional-report-cover.jpg", html)
        self.assertIn("https://example.com/hero?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign=regional_market_outlook", html)
        self.assertNotIn("Manage Preferences", html)

    def test_final_links_append_missing_utms_and_preserve_existing_values(self):
        form = complete_form()
        form.update({
            "reg_utm_source": "regional-team",
            "reg_utm_medium": "email",
            "reg_utm_campaign": "india-healthcare-october",
            "reg_hero_cta_url": "https://example.com/hero?utm_source=editor&ref=dashboard",
            "reg_brand_url": "https://example.com/brand",
        })

        links = resolved_regional_links(regional_content(form))

        self.assertIn("utm_source=editor", links["Hero button"])
        self.assertIn("ref=dashboard", links["Hero button"])
        self.assertIn("utm_medium=email", links["Hero button"])
        self.assertIn("utm_campaign=india-healthcare-october", links["Hero button"])
        self.assertNotIn("utm_source=regional-team", links["Hero button"])
        self.assertIn("utm_source=regional-team", links["Header logo"])

    def test_content_links_reject_missing_invalid_and_generic_homepage_urls(self):
        form = complete_form()
        form["reg_hero_cta_url"] = "https://www.kenresearch.com?utm_source=test"
        form["reg_insight2_url"] = "not-a-url"
        form["reg_report_cta_url"] = ""

        problems = validate_regional_content(regional_content(form))

        self.assertIn("Hero button link cannot use the generic Ken Research homepage.", problems)
        self.assertIn("Insight 2 link must be a complete http:// or https:// URL.", problems)
        self.assertIn("Report button link must be a complete http:// or https:// URL.", problems)

    def test_uploaded_images_are_normalized_to_each_regional_slot(self):
        for slot in REGIONAL_SLOTS:
            result = prepare_regional_image(slot, png_upload().getvalue())
            with Image.open(BytesIO(result)) as output:
                self.assertEqual(SLOT_SIZES[slot], output.size)
                self.assertEqual("JPEG", output.format)

    def test_dashboard_exposes_regional_builder(self):
        response = self.client.get("/send")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Regional Market Outlook", response.data)
        self.assertIn(b'reg_upload_hero', response.data)
        self.assertIn(b'reg_upload_insights', response.data)
        self.assertIn(b'reg_upload_report', response.data)
        self.assertIn(b"Final link review", response.data)
        self.assertIn(b'reg_brand_url', response.data)
        self.assertNotIn(b'name="tracker_url"', response.data)
        self.assertNotIn(b"Manage Preferences", response.data)

    def test_final_link_review_api_returns_exact_direct_urls(self):
        form = complete_form()
        response = self.client.post("/api/newsletter/regional-links", data=form)

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["click_tracking"])
        self.assertEqual([], payload["errors"])
        self.assertEqual(
            "https://example.com/report?utm_source=newsletter&utm_medium=email&utm_campaign=regional_market_outlook",
            payload["links"]["Report button"],
        )

    @patch.object(webapp, "_stored_image_payload")
    @patch.object(webapp, "_store_generated_images")
    def test_regional_upload_uses_shared_image_storage(self, store, payload):
        payload.return_value = {
            "hero": {"url": "/generated/token/hero?v=1", "placeholder": False}
        }
        form = complete_form()
        form["reg_image_token"] = "token"
        form["reg_upload_hero"] = (png_upload(), "hero.png")

        response = self.client.post(
            "/api/newsletter/regional-images/upload",
            data=form,
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("partial", response.get_json()["status"])
        self.assertEqual(["insights", "report"], response.get_json()["missing"])
        stored = store.call_args.args[1]
        self.assertEqual({"hero"}, set(stored))
        self.assertFalse(stored["hero"][1])

    @patch.object(webapp, "query_db")
    def test_preview_uses_all_stored_regional_images(self, query_db):
        query_db.return_value = [{"slot": slot} for slot in REGIONAL_SLOTS]
        form = complete_form()
        form["reg_image_token"] = "token"

        response = self.client.post("/newsletter/regional-preview", data=form)

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Regional Market Outlook preview", response.data)
        self.assertIn(b"India&#x27;s Healthcare Sector", response.data)


if __name__ == "__main__":
    unittest.main()
