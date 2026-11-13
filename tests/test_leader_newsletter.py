import os
import re
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp

from newsletter_leader import (
    CANVAS_WIDTH,
    DEFAULT_PORTRAIT_FILE,
    IMAGE_FILES,
    LEADER_SLOTS,
    SLOT_SIZES,
    leader_content,
    prepare_leader_image,
    render_leader_newsletter,
    resolved_leader_links,
    validate_leader_content,
)


def complete_form():
    return {
        "lead_section_label": "Leader's Perspective",
        "lead_industry_label": "BFSI",
        "lead_region_label": "Southeast Asia",
        "lead_issue_label": "October 2026 | Issue 01",
        "lead_hero_kicker": "Vietnam | Digital Financial Services",
        "lead_hero_title": "Vietnam's Mobile Payments Have Scale. Where Is the Profitability?",
        "lead_hero_body": "Transaction scale does not automatically create sustainable margins.",
        "lead_hero_cta_text": "Read the Full Article",
        "lead_hero_cta_url": "https://example.com/article",
        "lead_leader_name": "Namit Goel",
        "lead_leader_role": "Co-Founder & Director, Ken Research",
        "lead_leader_quote": "Trust and advisory capability create enduring relationships.",
        "lead_reading_title": "How Are Southeast Asian Lenders Competing for SME Growth?",
        "lead_reading_body": "Digital underwriting and risk management are differentiators.",
        "lead_reading_cta_url": "https://example.com/benchmarking",
        "lead_report_title": "Vietnam Wealth Management Market Outlook to 2029",
        "lead_report_body": "Explore wealth segments and the competitive landscape.",
        "lead_report_cta_url": "https://example.com/report",
    }


def png_upload(width=900, height=700):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (31, 72, 124)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class LeaderNewsletterTests(unittest.TestCase):
    def setUp(self):
        webapp.app.config.update(TESTING=True)
        self.client = webapp.app.test_client()

    def test_document_content_validates_and_required_fields_are_enforced(self):
        content = leader_content(complete_form())
        self.assertEqual([], validate_leader_content(content))

        form = complete_form()
        form["lead_leader_quote"] = ""
        form["lead_reading_cta_url"] = ""
        problems = validate_leader_content(leader_content(form))
        self.assertIn("Leader quote is required.", problems)
        self.assertIn(
            "Further reading link must be a complete http:// or https:// URL.", problems
        )

    def test_renderer_matches_reference_sections_and_official_assets(self):
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_leader_newsletter(complete_form(), "cid", sources)

        self.assertEqual(600, CANVAS_WIDTH)
        self.assertIn('width="600"', html)
        self.assertIn("Leader&#x27;s Perspective", html)
        self.assertIn("From the Leader", html)
        self.assertIn("Further Reading", html)
        self.assertIn("Featured Market Intelligence", html)
        self.assertIn("Namit Goel", html)
        self.assertIn("cid:ken-research-logo-color.png", html)
        self.assertIn("cid:mailmodo-linkedin.png", html)
        self.assertIn("cid:mailmodo-twitter.png", html)
        self.assertIn("cid:mailmodo-youtube.png", html)
        for filename in IMAGE_FILES.values():
            self.assertIn(f"cid:{filename}", html)
        self.assertNotIn("Manage Preferences", html)

    def test_default_supplied_portrait_is_used_when_not_replaced(self):
        sources = {
            "hero": "cid:leader-perspective-hero.jpg",
            "reading": "cid:leader-perspective-reading.jpg",
            "report": "cid:leader-perspective-report.jpg",
        }
        html = render_leader_newsletter(complete_form(), "cid", sources)

        self.assertIn(f"cid:{DEFAULT_PORTRAIT_FILE}", html)
        asset_path = Path(webapp.NEWSLETTER_ASSETS_DIR) / DEFAULT_PORTRAIT_FILE
        self.assertTrue(asset_path.is_file())
        with Image.open(asset_path) as portrait:
            self.assertEqual(SLOT_SIZES["portrait"], portrait.size)

    def test_sections_expand_with_variable_copy_without_fixed_text_heights(self):
        form = complete_form()
        form["lead_hero_body"] = "Short summary."
        short_html = render_leader_newsletter(
            form, "cid", {"hero": "cid:leader-perspective-hero.jpg"}
        )
        form["lead_hero_body"] = "Longer editorial summary. " * 30
        form["lead_leader_quote"] = "Longer leadership perspective. " * 20
        long_html = render_leader_newsletter(
            form, "cid", {"hero": "cid:leader-perspective-hero.jpg"}
        )

        self.assertIn("Short summary.", short_html)
        self.assertIn("Longer editorial summary.", long_html)
        self.assertIn("Longer leadership perspective.", long_html)
        self.assertIn(
            'class="lead-img" src="cid:leader-perspective-hero.jpg"', long_html
        )
        self.assertNotIn("background-size:cover", long_html)
        self.assertNotIn("lead-hero-image", long_html)
        short_height = int(
            re.search(
                r'src="cid:leader-perspective-hero\.jpg" width="270" height="(\d+)"',
                short_html,
            ).group(1)
        )
        long_height = int(
            re.search(
                r'src="cid:leader-perspective-hero\.jpg" width="270" height="(\d+)"',
                long_html,
            ).group(1)
        )
        self.assertGreater(long_height, short_height)
        self.assertGreaterEqual(short_height, 190)
        self.assertLessEqual(long_height, 360)
        self.assertIn("padding:19px 18px 0 22px", short_html)

    def test_links_append_utms_without_overwriting_existing_values(self):
        form = complete_form()
        form.update({
            "lead_utm_source": "leader-team",
            "lead_utm_medium": "email",
            "lead_utm_campaign": "bfsi-october",
            "lead_hero_cta_url": "https://example.com/article?utm_source=editor&ref=dashboard",
        })

        links = resolved_leader_links(leader_content(form))

        self.assertIn("utm_source=editor", links["Hero article"])
        self.assertNotIn("utm_source=leader-team", links["Hero article"])
        self.assertIn("utm_campaign=bfsi-october", links["Hero article"])
        self.assertIn("ref=dashboard", links["Hero article"])

    def test_uploaded_images_are_normalized_to_each_slot(self):
        for slot in LEADER_SLOTS:
            result = prepare_leader_image(slot, png_upload().getvalue())
            with Image.open(BytesIO(result)) as output:
                self.assertEqual(SLOT_SIZES[slot], output.size)
                self.assertEqual("JPEG", output.format)

    def test_dashboard_exposes_manual_leader_builder(self):
        response = self.client.get("/send")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Leader's Perspective", response.data)
        self.assertIn(b'lead_upload_hero', response.data)
        self.assertIn(b'lead_upload_portrait', response.data)
        self.assertIn(b'lead_upload_reading', response.data)
        self.assertIn(b'lead_upload_report', response.data)
        self.assertIn(b"Namit Goel", response.data)
        self.assertIn(b"Final link review", response.data)

    def test_link_review_api_returns_direct_urls(self):
        response = self.client.post("/api/newsletter/leader-links", data=complete_form())

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["click_tracking"])
        self.assertEqual([], payload["errors"])
        self.assertEqual(
            "https://example.com/report?utm_source=newsletter&utm_medium=email&utm_campaign=leaders_perspective",
            payload["links"]["Featured intelligence"],
        )

    @patch.object(webapp, "_stored_image_payload")
    @patch.object(webapp, "_store_generated_images")
    def test_image_upload_uses_shared_storage(self, store, payload):
        payload.return_value = {
            "hero": {"url": "/generated/token/hero?v=1", "placeholder": False}
        }
        form = complete_form()
        form["lead_image_token"] = "token"
        form["lead_upload_hero"] = (png_upload(), "hero.png")

        response = self.client.post(
            "/api/newsletter/leader-images/upload",
            data=form,
            content_type="multipart/form-data",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("partial", response.get_json()["status"])
        self.assertEqual(["reading", "report"], response.get_json()["missing"])
        self.assertEqual({"hero"}, set(store.call_args.args[1]))

    @patch.object(webapp, "query_db")
    def test_preview_uses_uploaded_images_and_default_portrait(self, query_db):
        query_db.return_value = [
            {"slot": "hero"}, {"slot": "reading"}, {"slot": "report"}
        ]
        form = complete_form()
        form["lead_image_token"] = "token"

        response = self.client.post("/newsletter/leader-preview", data=form)

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Leader&#39;s Perspective preview", response.data)
        self.assertIn(b"leaders-namit-goel.jpg", response.data)


if __name__ == "__main__":
    unittest.main()
