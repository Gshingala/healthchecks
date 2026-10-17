from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from datetime import timedelta as td

from time_machine import travel

from hc.accounts.models import Project
from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse

CURRENT_TIME = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
logger = logging.getLogger(__name__)


@travel(CURRENT_TIME, tick=False)
class ListMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.ended = self._window("Ended", -3, -2)
        self.active = self._window("Active", -1, 1)
        self.upcoming = self._window("Upcoming", 2, 3)

    def _window(
        self,
        name: str,
        start_hours: int,
        end_hours: int,
        project: Project | None = None,
    ) -> MaintenanceWindow:
        return MaintenanceWindow.objects.create(
            project=project or self.project,
            name=name,
            start=CURRENT_TIME + td(hours=start_hours),
            end=CURRENT_TIME + td(hours=end_hours),
            created_via="api",
        )

    def get(
        self, v: int = 3, qs: str = "", api_key: str = "X" * 32
    ) -> TestHttpResponse:
        url = f"/api/v{v}/maintenance/{qs}"
        return self.client.get(url, HTTP_X_API_KEY=api_key)

    def names(self, r: TestHttpResponse) -> list[str]:
        return [w["name"] for w in r.json()["windows"]]

    def test_it_works(self) -> None:
        self._window("Charlie's", -1, 1, project=self.charlies_project)
        for v in (1, 2, 3):
            r = self.get(v=v)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Access-Control-Allow-Origin"], "*")
            self.assertEqual(self.names(r), ["Upcoming", "Active", "Ended"])

    def test_it_returns_window_json(self) -> None:
        r = self.get()
        self.assertEqual(r.json()["windows"][0], self.upcoming.to_dict())

    def test_it_sorts_equal_starts_by_id_descending(self) -> None:
        later = self._window("Same start", 2, 4)
        r = self.get()
        self.assertEqual(self.names(r)[:2], [later.name, "Upcoming"])

    def test_it_accepts_read_only_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        for v in (1, 2, 3):
            r = self.get(v=v, api_key="R" * 32)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(r.json()["windows"]), 3)

    def test_it_filters_by_state(self) -> None:
        for state, name in [
            ("active", "Active"),
            ("upcoming", "Upcoming"),
            ("ended", "Ended"),
        ]:
            r = self.get(qs=f"?state={state}")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.names(r), [name])

    def test_it_treats_end_equal_now_as_ended(self) -> None:
        self.active.end = CURRENT_TIME
        self.active.save()

        r = self.get(qs="?state=ended")
        self.assertEqual(self.names(r), ["Active", "Ended"])

    def test_it_rejects_bad_state(self) -> None:
        r = self.get(qs="?state=foo")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json(), {"error": "invalid state, expected active, upcoming or ended"}
        )

    def test_it_prunes_old_windows(self) -> None:
        old = MaintenanceWindow.objects.create(
            project=self.project,
            name="Old",
            start=CURRENT_TIME - td(days=91),
            end=CURRENT_TIME - td(days=90, seconds=1),
            created_via="api",
        )
        kept = MaintenanceWindow.objects.create(
            project=self.project,
            name="Kept",
            start=CURRENT_TIME - td(days=91),
            end=CURRENT_TIME - td(days=90) + td(seconds=1),
            created_via="api",
        )

        r = self.get()
        self.assertNotIn("Old", self.names(r))
        self.assertIn("Kept", self.names(r))
        self.assertFalse(MaintenanceWindow.objects.filter(id=old.id).exists())
        self.assertTrue(MaintenanceWindow.objects.filter(id=kept.id).exists())

    def test_it_does_not_prune_on_bad_state(self) -> None:
        old = self._window("Old", -24 * 92, -24 * 91)
        self.get(qs="?state=foo")
        self.assertTrue(MaintenanceWindow.objects.filter(id=old.id).exists())

    def test_it_handles_missing_api_key(self) -> None:
        r = self.client.get("/api/v3/maintenance/")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_short_api_key(self) -> None:
        r = self.get(api_key="X")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_wrong_api_key(self) -> None:
        r = self.get(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "wrong api key"})

    def test_it_handles_options(self) -> None:
        r = self.client.options("/api/v3/maintenance/")
        self.assertEqual(r.status_code, 204)
        self.assertIn("GET", r["Access-Control-Allow-Methods"])
        self.assertIn("POST", r["Access-Control-Allow-Methods"])

    def test_it_rejects_put(self) -> None:
        r = self.client.put("/api/v3/maintenance/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 405)

    def test_time_budget(self) -> None:
        # NFR-1.4 is a soft budget: the duration is logged, not asserted.
        MaintenanceWindow.objects.all().delete()
        windows = []
        for i in range(1100):
            if i < 100:
                start, end = CURRENT_TIME + td(hours=i), CURRENT_TIME + td(hours=i + 1)
            else:
                start = CURRENT_TIME - td(days=30, hours=i)
                end = start + td(hours=1)
            windows.append(
                MaintenanceWindow(
                    project=self.project,
                    name=f"Window {i}",
                    start=start,
                    end=end,
                    created_via="api",
                )
            )
        MaintenanceWindow.objects.bulk_create(windows)

        started = time.perf_counter()
        r = self.get()
        elapsed = time.perf_counter() - started
        logger.info("Listing 1100 maintenance windows took %.3f s", elapsed)

        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["windows"]), 1100)
