from __future__ import annotations

import uuid
from datetime import datetime, timezone
from datetime import timedelta as td
from unittest.mock import patch

from time_machine import travel

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse

CURRENT_TIME = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


@travel(CURRENT_TIME, tick=False)
class DeleteMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.window = self._upcoming()

    def _upcoming(self) -> MaintenanceWindow:
        return MaintenanceWindow.objects.create(
            project=self.project,
            name="Postgres upgrade",
            start=CURRENT_TIME + td(hours=1),
            end=CURRENT_TIME + td(hours=2),
            created_via="api",
        )

    def delete(
        self, code: uuid.UUID | None = None, v: int = 3, api_key: str = "X" * 32
    ) -> TestHttpResponse:
        url = f"/api/v{v}/maintenance/{code or self.window.code}"
        return self.client.delete(url, HTTP_X_API_KEY=api_key)

    def test_it_works(self) -> None:
        for v in (1, 2, 3):
            window = self._upcoming()
            expected = window.to_dict()

            r = self.delete(code=window.code, v=v)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Access-Control-Allow-Origin"], "*")
            self.assertEqual(r.json(), expected)
            self.assertFalse(MaintenanceWindow.objects.filter(id=window.id).exists())

    def test_it_rejects_active_and_ended_windows(self) -> None:
        for start, end in [
            (CURRENT_TIME, CURRENT_TIME + td(hours=1)),
            (CURRENT_TIME - td(hours=2), CURRENT_TIME - td(hours=1)),
        ]:
            self.window.start, self.window.end = start, end
            self.window.save()

            r = self.delete()
            self.assertEqual(r.status_code, 409)
            self.assertEqual(
                r.json(), {"error": "only upcoming maintenance windows can be deleted"}
            )
            q = MaintenanceWindow.objects.filter(id=self.window.id)
            self.assertTrue(q.exists())

    def test_it_updates_next_nag_dates(self) -> None:
        with patch("hc.api.views.Project.update_next_nag_dates", autospec=True) as mock:
            r = self.delete()

        self.assertEqual(r.status_code, 200)
        mock.assert_called_once()
        self.assertEqual(mock.call_args.args[0].id, self.project.id)

    def test_it_handles_other_project(self) -> None:
        self.charlies_project.api_key = "C" * 32
        self.charlies_project.save()

        r = self.delete(api_key="C" * 32)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.content, b"")
        self.assertTrue(MaintenanceWindow.objects.filter(id=self.window.id).exists())

    def test_it_handles_unknown_uuid(self) -> None:
        r = self.delete(code=uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_it_handles_missing_api_key(self) -> None:
        r = self.delete(api_key="")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_wrong_api_key(self) -> None:
        r = self.delete(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "wrong api key"})

    def test_it_rejects_read_only_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        for v in (1, 2, 3):
            r = self.delete(v=v, api_key="R" * 32)
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "wrong api key"})
        self.assertTrue(MaintenanceWindow.objects.filter(id=self.window.id).exists())
