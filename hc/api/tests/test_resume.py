from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td

from django.utils.timezone import now

from hc.api.models import Check, Flip, MaintenanceWindow
from hc.test import BaseTestCase


class ResumeTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.check = Check.objects.create(
            project=self.project,
            status="paused",
            last_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            last_ping=datetime(2020, 1, 1, tzinfo=timezone.utc),
            alert_after=datetime(2020, 1, 1, 1, tzinfo=timezone.utc),
        )
        self.url = f"/api/v1/checks/{self.check.code}/resume"

    def test_it_works(self) -> None:
        r = self.csrf_client.post(
            self.url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "new")
        self.assertIsNone(self.check.last_start)
        self.assertIsNone(self.check.last_ping)
        self.assertIsNone(self.check.alert_after)

        flip = Flip.objects.get()
        self.assertEqual(flip.old_status, "paused")
        self.assertEqual(flip.new_status, "new")
        # should be marked as processed from the beginning, so sendalerts ignores it
        self.assertTrue(flip.processed)

    def test_it_handles_not_paused_checks(self) -> None:
        self.check.status = "up"
        self.check.save()

        r = self.csrf_client.post(
            self.url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.content.decode(), "check is not paused")

    def test_it_accepts_api_key_in_post_body(self) -> None:
        payload = {"api_key": "X" * 32}
        r = self.csrf_client.post(self.url, payload, content_type="application/json")
        self.assertEqual(r.status_code, 200)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "new")

    def test_it_handles_options(self) -> None:
        r = self.client.options(self.url)
        self.assertEqual(r.status_code, 204)
        self.assertIn("POST", r["Access-Control-Allow-Methods"])

    def test_it_only_allows_post(self) -> None:
        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 405)

    def test_it_validates_ownership(self) -> None:
        check = Check.objects.create(project=self.bobs_project, status="up")
        url = f"/api/v1/checks/{check.code}/resume"
        r = self.client.post(
            url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

        self.assertEqual(r.status_code, 403)

    def test_it_validates_uuid(self) -> None:
        url = "/api/v1/checks/not-uuid/resume"
        r = self.client.post(
            url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

        self.assertEqual(r.status_code, 404)

    def test_it_handles_missing_check(self) -> None:
        url = "/api/v1/checks/07c2f548-9850-4b27-af5d-6c9dc157ec02/resume"
        r = self.client.post(
            url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

        self.assertEqual(r.status_code, 404)

    def test_it_rejects_non_dict_post_body(self) -> None:
        r = self.csrf_client.post(self.url, "123", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json()["error"], "json validation error: value is not an object"
        )

    def add_window(self, start_offset: td = td(minutes=-5)) -> None:
        start = now() + start_offset
        MaintenanceWindow.objects.create(
            project=self.project,
            name="Deploy",
            start=start,
            end=start + td(hours=1),
            created_via="api",
        )

    def test_it_reports_maintenance(self) -> None:
        self.add_window()
        r = self.csrf_client.post(
            self.url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["maintenance"])

    def test_it_reports_upcoming_window_as_no_maintenance(self) -> None:
        self.add_window(start_offset=td(hours=1))
        r = self.csrf_client.post(
            self.url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )
        self.assertFalse(r.json()["maintenance"])
