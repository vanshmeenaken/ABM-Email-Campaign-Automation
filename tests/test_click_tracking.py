import os
import re
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp

from newsletter_expert import render_expert_newsletter


class ClickTrackingTests(unittest.TestCase):
    def setUp(self):
        webapp.app.config.update(TESTING=True)
        self.client = webapp.app.test_client()
        self.secret = patch.dict(os.environ, {"FLASK_SECRET_KEY": "click-test-secret"})
        self.secret.start()

    def tearDown(self):
        self.secret.stop()

    def test_http_links_are_wrapped_and_unsubscribe_is_left_direct(self):
        unsubscribe_url = "https://dashboard.example.com/unsubscribe/signed"
        body = (
            '<a href="https://example.com/report?a=1&amp;b=2">Report</a>'
            f'<a href="{unsubscribe_url}">Unsubscribe</a>'
            '<a href="mailto:team@example.com">Email us</a>'
        )

        result = webapp.apply_click_tracking(
            body,
            "https://dashboard.example.com",
            "campaign-1",
            "reader@example.com",
            2,
            unsubscribe_url=unsubscribe_url,
        )

        match = re.search(r"/track/click/([^\"]+)", result)
        self.assertIsNotNone(match)
        payload = webapp.read_click_token(match.group(1))
        self.assertEqual("campaign-1", payload["campaign_id"])
        self.assertEqual("reader@example.com", payload["recipient"])
        self.assertEqual(2, payload["step"])
        self.assertEqual("https://example.com/report?a=1&b=2", payload["target_url"])
        self.assertIn(f'href="{unsubscribe_url}"', result)
        self.assertIn('href="mailto:team@example.com"', result)

    def test_sequence_tracks_even_when_older_campaign_stored_false(self):
        body = '<a href="https://example.com/report?utm_source=newsletter">Report</a>'

        stored_false = webapp.apply_sequence_click_tracking(
            body,
            {"track_clicks": False},
            "https://dashboard.example.com",
            "campaign-1",
            "reader@example.com",
            1,
        )
        tracked = webapp.apply_sequence_click_tracking(
            body,
            {},
            "https://dashboard.example.com",
            "campaign-1",
            "reader@example.com",
            1,
        )

        self.assertIn("/track/click/", stored_false)
        self.assertIn("/track/click/", tracked)

    @patch.object(webapp, "execute_db")
    def test_click_route_records_event_and_redirects(self, execute_db):
        target = "https://example.com/report"
        token = webapp.create_click_token(
            "campaign-1", "reader@example.com", 1, target
        )

        response = self.client.get(f"/track/click/{token}")

        self.assertEqual(302, response.status_code)
        self.assertEqual(target, response.headers["Location"])
        execute_db.assert_called_once()
        params = execute_db.call_args.args[1]
        self.assertEqual(("campaign-1", "reader@example.com", 1, target), params[:4])

    def test_invalid_click_token_is_rejected(self):
        response = self.client.get("/track/click/not-a-valid-token")

        self.assertEqual(400, response.status_code)

    @patch.object(webapp, "execute_db")
    def test_internal_recipient_click_is_recorded(self, execute_db):
        token = webapp.create_click_token(
            "campaign-1", "reviewer@kenresearch.com", 1, "https://example.com/report"
        )

        response = self.client.get(f"/track/click/{token}")

        self.assertEqual(302, response.status_code)
        execute_db.assert_called_once()
        self.assertEqual(
            "reviewer@kenresearch.com", execute_db.call_args.args[1][1]
        )

    @patch.object(webapp, "execute_db")
    def test_internal_recipient_open_is_recorded(self, execute_db):
        response = self.client.get(
            "/track/pixel?campaign_id=campaign-1&recipient=reviewer@kenresearch.com&step=1"
        )

        self.assertEqual(200, response.status_code)
        execute_db.assert_called_once()
        params = execute_db.call_args.args[1]
        self.assertEqual(("campaign-1", "reviewer@kenresearch.com", 1), params[:3])

    def test_expert_newsletter_tracks_every_destination_except_unsubscribe(self):
        unsubscribe_url = "https://dashboard.example.com/unsubscribe/signed"
        form = {
            "exp_brand_url": "https://www.kenresearch.com",
            "exp_hero_title": "Expert interview",
            "exp_hero_body": "Interview summary",
            "exp_hero_cta_url": "https://example.com/interview",
            "exp_expert_name": "Expert",
            "exp_expert_role": "Chief Operating Officer",
            "exp_expert_company": "Example Ltd.",
            "exp_takeaway1_title": "One", "exp_takeaway1_body": "First",
            "exp_takeaway2_title": "Two", "exp_takeaway2_body": "Second",
            "exp_takeaway3_title": "Three", "exp_takeaway3_body": "Third",
            "exp_report_title": "Featured report",
            "exp_report_body": "Report summary",
            "exp_report_cta_url": "https://example.com/report",
            "exp_contact_url": "https://www.kenresearch.com/contact-us",
            "exp_unsubscribe_url": unsubscribe_url,
        }
        body = render_expert_newsletter(form, "cid", {})
        tracked = webapp.apply_sequence_click_tracking(
            body, {}, "https://dashboard.example.com", "campaign-1",
            "reader@example.com", 1, unsubscribe_url=unsubscribe_url,
        )

        hrefs = [unescape(value) for value in re.findall(r'href="([^"]+)"', tracked)]
        tracked_hrefs = [value for value in hrefs if "/track/click/" in value]
        self.assertEqual(4, len(tracked_hrefs))
        self.assertIn(unsubscribe_url, hrefs)
        destinations = {
            webapp.read_click_token(value.rsplit("/", 1)[-1])["target_url"]
            for value in tracked_hrefs
        }
        self.assertEqual({
            "https://www.kenresearch.com?utm_source=newsletter&utm_medium=email&utm_campaign=experts_desk",
            "https://example.com/interview?utm_source=newsletter&utm_medium=email&utm_campaign=experts_desk",
            "https://example.com/report?utm_source=newsletter&utm_medium=email&utm_campaign=experts_desk",
            "https://www.kenresearch.com/contact-us?utm_source=newsletter&utm_medium=email&utm_campaign=experts_desk",
        }, destinations)

    @patch.object(webapp, "_load_progress", return_value={"total_recipients": 386})
    @patch.object(webapp, "_load_brief", return_value={"name": "Industry Intelligence"})
    @patch.object(webapp, "query_db")
    def test_metrics_api_reports_unique_recipient_clicks(
        self, query_db, _load_brief, _load_progress
    ):
        def results(sql, _params=(), one=False):
            if "FROM opens" in sql:
                return {"cnt": 232, "last_open": "2026-10-30T11:50:42"}
            if "FROM clicks" in sql:
                self.assertIn("COUNT(DISTINCT recipient) as cnt", sql)
                self.assertNotIn("COUNT(*)", sql)
                return {"cnt": 24, "last_click": "2026-10-30T11:29:44"}
            self.fail(f"Unexpected query: {sql}")

        query_db.side_effect = results

        response = self.client.get("/api/metrics/campaign-1")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(24, payload["clicks"])
        self.assertEqual(24, payload["unique_clickers"])

    def test_click_dashboard_only_labels_unique_clicks(self):
        templates = Path(webapp.__file__).with_name("templates")
        dashboard = (templates / "dashboard.html").read_text(encoding="utf-8")
        campaign_detail = (templates / "campaign_detail.html").read_text(encoding="utf-8")

        self.assertIn("Unique Clicks", dashboard)
        self.assertNotIn("Total Clicks", dashboard)
        self.assertIn("Unique clicks", campaign_detail)
        self.assertNotIn("Total clicks", campaign_detail)
        self.assertIn("Recipient Click Activity", campaign_detail)
        self.assertIn("Repeated requests for the same link are collapsed", campaign_detail)


if __name__ == "__main__":
    unittest.main()
