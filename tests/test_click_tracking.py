import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ["SKIP_BACKGROUND_WORKERS"] = "1"
os.environ.setdefault("DATABASE_URL", "postgresql://unused")

with patch("psycopg2.connect"):
    import app as webapp


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


if __name__ == "__main__":
    unittest.main()
