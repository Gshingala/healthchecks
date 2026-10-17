from __future__ import annotations

import uuid
from datetime import datetime, timezone
from datetime import timedelta as td
from unittest.mock import patch

from time_machine import travel

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse

CURRENT_TIME = datetime(2026, 11, 7, 12, 0, 0, 500000, tzinfo=timezone.utc)


@travel(CURRENT_TIME, tick=False)
class EndMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.window = MaintenanceWindow.objects.create(
            project=self.project,
            name="Deploy",
            start=CURRENT_TIME - td(hours=1),
            end=CURRENT_TIME + td(hours=1),
            created_via="api",
        )

    def post(
        self, code: uuid.UUID | None = None, v: int = 3, api_key: str = "X" * 32
    ) -> TestHttpResponse:
        url = f"/api/v{v}/maintenance/{code or self.window.code}/end"
        return self.csrf_client.post(
            url, "", content_type="application/json", HTTP_X_API_KEY=api_key
        )

    def test_it_works(self) -> None:
        for v in (1, 2, 3):
            self.window.end = CURRENT_TIME + td(hours=1)
            self.window.save()

            r = self.post(v=v)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Access-Control-Allow-Origin"], "*")
            self.assertEqual(r.json()["state"], "ended")
            self.assertEqual(r.json()["end"], "2026-11-07T12:00:00+00:00")

            self.window.refresh_from_db()
            self.assertEqual(self.window.end, CURRENT_TIME.replace(microsecond=0))

    def test_it_accepts_api_key_in_post_body(self) -> None:
        url = f"/api/v3/maintenance/{self.window.code}/end"
        r = self.csrf_client.post(
            url, {"api_key": "X" * 32}, content_type="application/json"
        )
        self.assertEqual(r.status_code, 200)

    def test_it_rejects_upcoming_and_ended_windows(self) -> None:
        for start, end in [
            (CURRENT_TIME + td(hours=1), CURRENT_TIME + td(hours=2)),
            (CURRENT_TIME - td(hours=2), CURRENT_TIME - td(hours=1)),
        ]:
            self.window.start, self.window.end = start, end
            self.window.save()

            r = self.post()
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json(), {"error": "maintenance window is not active"})

            self.window.refresh_from_db()
            self.assertEqual((self.window.start, self.window.end), (start, end))

    def test_it_updates_next_nag_dates(self) -> None:
        with patch("hc.api.views.Project.update_next_nag_dates", autospec=True) as mock:
            r = self.post()

        self.assertEqual(r.status_code, 200)
        mock.assert_called_once()
        self.assertEqual(mock.call_args.args[0].id, self.project.id)

    def test_it_handles_invalid_json(self) -> None:
        url = f"/api/v3/maintenance/{self.window.code}/end"
        r = self.csrf_client.post(
            url, "not json", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "could not parse request body"})

    def test_it_handles_other_project(self) -> None:
        self.charlies_project.api_key = "C" * 32
        self.charlies_project.save()

        r = self.post(api_key="C" * 32)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.content, b"")

    def test_it_handles_unknown_uuid(self) -> None:
        r = self.post(code=uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_it_handles_missing_api_key(self) -> None:
        r = self.post(api_key="")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_rejects_read_only_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        for v in (1, 2, 3):
            r = self.post(v=v, api_key="R" * 32)
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "wrong api key"})

        self.window.refresh_from_db()
        self.assertEqual(self.window.end, CURRENT_TIME + td(hours=1))

    def test_it_handles_options(self) -> None:
        r = self.client.options(f"/api/v3/maintenance/{self.window.code}/end")
        self.assertEqual(r.status_code, 204)
        self.assertIn("POST", r["Access-Control-Allow-Methods"])

    def test_it_only_allows_post(self) -> None:
        url = f"/api/v3/maintenance/{self.window.code}/end"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 405)
