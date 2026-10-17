from __future__ import annotations

import uuid
from datetime import datetime, timezone
from datetime import timedelta as td

from time_machine import travel

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse

CURRENT_TIME = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

WINDOW_KEYS = {
    "uuid",
    "name",
    "start",
    "end",
    "scope",
    "tags",
    "state",
    "created",
    "created_via",
}


@travel(CURRENT_TIME, tick=False)
class GetMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.window = MaintenanceWindow.objects.create(
            project=self.project,
            name="Postgres upgrade",
            start=CURRENT_TIME + td(hours=1),
            end=CURRENT_TIME + td(hours=2),
            tags="db prod",
            created_via="dashboard",
            created_by=self.alice,
        )

    def get(
        self, code: uuid.UUID | None = None, v: int = 3, api_key: str = "X" * 32
    ) -> TestHttpResponse:
        url = f"/api/v{v}/maintenance/{code or self.window.code}"
        return self.client.get(url, HTTP_X_API_KEY=api_key)

    def test_it_works(self) -> None:
        for v in (1, 2, 3):
            r = self.get(v=v)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Access-Control-Allow-Origin"], "*")
            self.assertEqual(r.json(), self.window.to_dict())

    def test_it_matches_window_json_keys(self) -> None:
        doc = self.get().json()
        self.assertEqual(set(doc.keys()), WINDOW_KEYS)
        self.assertEqual(doc["uuid"], str(self.window.code))
        self.assertEqual(doc["start"], "2026-11-07T13:00:00+00:00")
        self.assertEqual(doc["scope"], "tags")
        self.assertEqual(doc["state"], "upcoming")
        self.assertEqual(doc["created_via"], "dashboard")

    def test_it_accepts_read_only_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        for v in (1, 2, 3):
            r = self.get(v=v, api_key="R" * 32)
            self.assertEqual(r.status_code, 200)

    def test_it_handles_other_project(self) -> None:
        self.charlies_project.api_key = "C" * 32
        self.charlies_project.save()

        r = self.get(api_key="C" * 32)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.content, b"")

    def test_it_handles_unknown_uuid(self) -> None:
        r = self.get(code=uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_it_handles_missing_api_key(self) -> None:
        r = self.client.get(f"/api/v3/maintenance/{self.window.code}")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_wrong_api_key(self) -> None:
        r = self.get(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "wrong api key"})

    def test_it_handles_options(self) -> None:
        r = self.client.options(f"/api/v3/maintenance/{self.window.code}")
        self.assertEqual(r.status_code, 204)
        self.assertIn("GET", r["Access-Control-Allow-Methods"])
        self.assertIn("DELETE", r["Access-Control-Allow-Methods"])

    def test_it_rejects_put_and_post(self) -> None:
        url = f"/api/v3/maintenance/{self.window.code}"
        r = self.client.put(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 405)
        r = self.csrf_client.post(
            url, "", content_type="application/json", HTTP_X_API_KEY="X" * 32
        )
        self.assertEqual(r.status_code, 405)
