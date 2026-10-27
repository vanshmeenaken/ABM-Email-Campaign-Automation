import base64
import os
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from PIL import Image

import image_gen
from newsletter_industry import (
    CANVAS_WIDTH,
    DEVELOPMENT_IMAGE_HEIGHT,
    DEVELOPMENT_IMAGE_WIDTH,
    HERO_IMAGE_HEIGHT,
    HERO_IMAGE_WIDTH,
    IMAGE_FILES,
    REPORT_HEIGHT,
    REPORT_WIDTH,
    image_specs,
    industry_content,
    render_industry_newsletter,
    validate_industry_content,
)


def complete_form():
    return {
        "ind_section_label": "Industry Intelligence",
        "ind_issue_label": "Oct 2026 | Issue 01",
        "ind_industry": "Automotive",
        "ind_hero_kicker": "Key updates across sectors",
        "ind_hero_title": "Saudi Arabia's Automotive Market Is Changing",
        "ind_hero_body": "Vision 2030 is reshaping automotive competition.",
        "ind_hero_cta_text": "Read the Full Perspective",
        "ind_hero_cta_url": "https://example.com/hero",
        "ind_list_heading": "Top Developments in Automotive",
        "ind_report_label": "Featured deep-dive report",
        "ind_report_title": "KSA Automotive Market Outlook to 2030",
        "ind_report_body": "A detailed view of demand and competition.",
        "ind_report_cta_text": "Explore the Full Market Report",
        "ind_report_cta_url": "https://example.com/report",
        **{
            f"ind_dev{number}_{field}": value
            for number in (1, 2, 3)
            for field, value in {
                "tag": f"Market Signal {number}",
                "title": f"Development headline {number}",
                "body": f"Development summary {number}",
                "url": f"https://example.com/dev-{number}",
            }.items()
        },
    }


class NewsletterRendererTests(unittest.TestCase):
    def test_complete_content_validates_and_builds_all_image_specs(self):
        content = industry_content(complete_form())
        self.assertEqual([], validate_industry_content(content))
        self.assertEqual({"hero", "dev1", "dev2", "dev3"}, set(image_specs(content)))

    def test_missing_required_copy_is_reported(self):
        form = complete_form()
        form["ind_hero_title"] = ""
        form["ind_dev2_body"] = ""
        problems = validate_industry_content(industry_content(form))
        self.assertIn("Hero headline is required.", problems)
        self.assertIn("Development 2 summary is required.", problems)

    def test_renderer_uses_cids_links_and_escapes_operator_copy(self):
        form = complete_form()
        form["ind_dev1_title"] = '<script>alert("x")</script>'
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_industry_newsletter(form, "cid", sources, has_report_cover=True)
        self.assertIn("cid:ken-research-logo-color.png", html)
        self.assertIn("cid:ind-hero.jpg", html)
        self.assertIn("cid:ind-report-cover.jpg", html)
        self.assertIn("https://example.com/hero", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("x")</script>', html)

    def test_quality_styling_uses_outlook_safe_buttons_and_heavy_arrows(self):
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_industry_newsletter(complete_form(), "cid", sources, has_report_cover=True)

        self.assertIn("mso-padding-alt:0", html)
        self.assertIn('cid:industry-arrow.png', html)
        self.assertEqual(3, html.count('src="cid:industry-arrow.png"'))
        self.assertIn('cid:industry-report-icon.png', html)

    def test_reference_geometry_is_encoded_explicitly(self):
        sources = {slot: f"cid:{filename}" for slot, filename in IMAGE_FILES.items()}
        html = render_industry_newsletter(complete_form(), "cid", sources, has_report_cover=True)

        self.assertEqual(600, CANVAS_WIDTH)
        self.assertIn(f'width="{CANVAS_WIDTH}"', html)
        self.assertIn(f'width="{HERO_IMAGE_WIDTH}" height="{HERO_IMAGE_HEIGHT}"', html)
        self.assertIn(
            f'width="{DEVELOPMENT_IMAGE_WIDTH}" height="{DEVELOPMENT_IMAGE_HEIGHT}"', html
        )
        self.assertIn(f'width="{REPORT_WIDTH}" height="{REPORT_HEIGHT}"', html)
        self.assertIn('width="224" height="29"', html)
        self.assertIn('width="168" height="22"', html)

    def test_report_fallback_keeps_cover_slot_when_no_upload_exists(self):
        html = render_industry_newsletter(complete_form(), "cid", {}, has_report_cover=False)
        self.assertIn('width="86" height="112"', html)
        self.assertIn("KSA Automotive Market Outlook to 2030", html)


class ImageGenerationTests(unittest.TestCase):
    def _source_png_b64(self):
        buffer = BytesIO()
        Image.new("RGB", (128, 128), (30, 90, 150)).save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_returns_flagged_placeholder(self):
        data, placeholder = image_gen.generate_slot("dev1", "Headline", "Summary", "Automotive")
        self.assertTrue(placeholder)
        with Image.open(BytesIO(data)) as output:
            self.assertEqual(image_gen.SLOT_SIZES["dev1"], output.size)
            self.assertEqual("JPEG", output.format)

    def test_hero_transition_matches_panel_and_preserves_right_side(self):
        source = Image.new("RGB", (200, 100), (20, 80, 140))
        transitioned = image_gen._fade_hero(source)

        self.assertEqual(image_gen.HERO_BG, transitioned.getpixel((0, 50)))
        self.assertEqual((20, 80, 140), transitioned.getpixel((199, 50)))
        middle = transitioned.getpixel((45, 50))
        self.assertNotEqual(image_gen.HERO_BG, middle)
        self.assertNotEqual((20, 80, 140), middle)

    def test_manual_upload_is_normalized_for_the_email_slot(self):
        source = BytesIO()
        Image.new("RGB", (900, 500), (30, 90, 150)).save(source, "PNG")

        result = image_gen.prepare_uploaded_image("dev1", source.getvalue())

        with Image.open(BytesIO(result)) as output:
            self.assertEqual(image_gen.SLOT_SIZES["dev1"], output.size)
            self.assertEqual("JPEG", output.format)

    def test_manual_upload_applies_transition_to_the_hero_only(self):
        source = BytesIO()
        Image.new("RGB", (900, 700), (30, 90, 150)).save(source, "PNG")

        result = image_gen.prepare_uploaded_image("hero", source.getvalue())

        with Image.open(BytesIO(result)) as output:
            self.assertEqual(image_gen.SLOT_SIZES["hero"], output.size)
            left = output.getpixel((0, output.height // 2))
            right = output.getpixel((output.width - 1, output.height // 2))
            self.assertTrue(all(abs(a - b) <= 5 for a, b in zip(left, image_gen.HERO_BG)))
            self.assertTrue(all(abs(a - b) <= 5 for a, b in zip(right, (30, 90, 150))))

    def test_manual_upload_rejects_invalid_files(self):
        with self.assertRaisesRegex(image_gen.ImageGenError, "valid PNG, JPEG, or WebP"):
            image_gen.prepare_uploaded_image("dev2", b"not an image")

    @patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_IMAGE_ENDPOINT": "https://example.test/image",
            "NVIDIA_IMAGE_MODEL": "black-forest-labs/flux.1-schnell",
        },
        clear=True,
    )
    @patch("image_gen.requests.post")
    def test_nvidia_image_is_resized_and_returned_as_jpeg(self, post):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"b64_image": self._source_png_b64()}
        post.return_value = response

        data, placeholder = image_gen.generate_slot("dev2", "Headline", "Summary", "Automotive")

        self.assertFalse(placeholder)
        with Image.open(BytesIO(data)) as output:
            self.assertEqual(image_gen.SLOT_SIZES["dev2"], output.size)
            self.assertEqual("JPEG", output.format)
        request_payload = post.call_args.kwargs["json"]
        self.assertEqual("base", request_payload["mode"])
        self.assertEqual(4, request_payload["steps"])
        self.assertIn("Headline", request_payload["prompt"])
        self.assertIn("No text", request_payload["prompt"])

    @patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_IMAGE_ENDPOINT": "https://ai.api.nvidia.com/v1/cosmos/nvidia/cosmos3-nano",
        },
        clear=True,
    )
    @patch("image_gen.requests.post")
    def test_cosmos_endpoint_uses_cosmos_request_contract(self, post):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"b64_image": self._source_png_b64()}
        post.return_value = response

        image_gen.generate_slot("dev1", "Headline", "Summary", "Automotive")

        request_payload = post.call_args.kwargs["json"]
        self.assertEqual("text2image", request_payload["model_mode"])
        self.assertEqual("720_1_1", request_payload["resolution"])
        self.assertNotIn("model", request_payload)

    @patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}, clear=True)
    @patch("image_gen.requests.post")
    def test_nvidia_404_has_actionable_error(self, post):
        response = Mock(ok=False, status_code=404, reason="Not Found", text="Not Found")
        response.json.side_effect = ValueError()
        post.return_value = response

        with self.assertRaisesRegex(image_gen.ImageGenError, "endpoint returned HTTP 404"):
            image_gen.generate_slot("hero", "Headline", "Summary", "Automotive")

    @patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}, clear=True)
    @patch("image_gen.requests.post")
    def test_timeout_is_not_retried(self, post):
        import requests

        post.side_effect = requests.Timeout("provider still processing")
        with self.assertRaisesRegex(image_gen.ImageGenError, "No automatic retry was made"):
            image_gen.generate_slot("dev3", "Headline", "Summary", "Automotive")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
