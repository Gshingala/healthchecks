from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td

import time_machine

from django.test import TestCase
from django.test.utils import override_settings
from django.utils.timezone import now

from hc.api.models import Check, MaintenanceWindow
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
XSS = "<script>alert(1)</script>"

# Queries issued by /projects/<code>/checks/ before maintenance windows (NFR-1.1)
CHECKS_PAGE_BASELINE_QUERIES = 10


class BasicsTestCase(TestCase):
    @override_settings(DEBUG=False, SECRET_KEY="abc")
    def test_it_redirects_to_login(self) -> None:
        r = self.client.get("/")
        self.assertRedirects(r, "/accounts/login/")

    @override_settings(DEBUG=False, SECRET_KEY="abc")
    def test_it_shows_no_warning(self) -> None:
        r = self.client.get("/accounts/login/")
        self.assertContains(r, "Log In to", status_code=200)
        self.assertNotContains(r, "do not use in production")

    @override_settings(DEBUG=True, SECRET_KEY="abc")
    def test_it_shows_debug_warning(self) -> None:
        r = self.client.get("/accounts/login/")
        self.assertContains(r, "Running in debug mode")

    @override_settings(DEBUG=False, SECRET_KEY="---")
    def test_it_shows_secret_key_warning(self) -> None:
        r = self.client.get("/accounts/login/")
        self.assertContains(r, "Log In to", status_code=200)
        self.assertContains(r, "Running with an insecure SECRET_KEY value")

    @override_settings(REGISTRATION_OPEN=False)
    def test_it_obeys_registration_open(self) -> None:
        r = self.client.get("/accounts/login/")

        self.assertNotContains(r, "Sign Up")


class ChecksPageQueryCountTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        for i in range(3):
            Check.objects.create(project=self.project, name=f"Check {i}", tags="db")
        self.url = f"/projects/{self.project.code}/checks/"

    def add_windows(self, count: int, start: td, end: td) -> None:
        for i in range(count):
            MaintenanceWindow.objects.create(
                project=self.project,
                name=f"Window {i}",
                start=now() + start,
                end=now() + end,
                created_by=self.alice,
                created_via="dashboard",
            )

    def assertQueryCount(self, count: int) -> None:
        self.client.login(username="alice@example.org", password="password")
        # Warm up: the first request refreshes last_active_date and session
        self.client.get(self.url)

        with self.assertNumQueries(count):
            r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_checks_page_uses_baseline_query_count(self) -> None:
        self.assertQueryCount(CHECKS_PAGE_BASELINE_QUERIES)

    def test_it_keeps_baseline_with_only_upcoming_window(self) -> None:
        self.add_windows(1, start=td(hours=1), end=td(hours=2))
        self.assertQueryCount(CHECKS_PAGE_BASELINE_QUERIES)

    def test_it_adds_at_most_two_queries_with_one_active_window(self) -> None:
        self.add_windows(1, start=-td(hours=1), end=td(hours=1))
        self.assertQueryCount(CHECKS_PAGE_BASELINE_QUERIES + 1)

    def test_it_adds_at_most_two_queries_with_fifty_active_windows(self) -> None:
        self.add_windows(50, start=-td(hours=1), end=td(hours=1))
        self.assertQueryCount(CHECKS_PAGE_BASELINE_QUERIES + 1)


@time_machine.travel(CURRENT_TIME)
class ChecksPageMaintenanceLabelTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.profile.tz = "Europe/Riga"
        self.profile.save()

        self.check = Check.objects.create(
            project=self.project, name="Backups", tags="db"
        )
        self.url = f"/projects/{self.project.code}/checks/"

    def add_window(self, name: str, start: td, end: td, tags: str = "") -> None:
        MaintenanceWindow.objects.create(
            project=self.project,
            name=name,
            start=CURRENT_TIME + start,
            end=CURRENT_TIME + end,
            tags=tags,
            created_by=self.alice,
            created_via="dashboard",
        )

    def get(self) -> str:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_it_shows_label_for_covered_check(self) -> None:
        # Ends 2026-11-07T21:30Z, which is 23:30 in Europe/Riga
        self.add_window("Postgres upgrade", -td(hours=1), td(hours=3, minutes=30))
        html = self.get()
        self.assertIn("label-maintenance", html)
        title = "Under maintenance until Nov 7, 23:30 Europe/Riga (Postgres upgrade)"
        self.assertIn(f'title="{title}"', html)
        self.assertIn(f'aria-label="{title}"', html)
        self.assertIn(
            '<span class="ic-maintenance" aria-hidden="true"></span> Maintenance', html
        )

    def test_it_names_the_window_with_latest_end(self) -> None:
        self.add_window("Short", -td(hours=1), td(hours=1))
        self.add_window("Long", -td(hours=1), td(hours=3, minutes=30), tags="db")
        html = self.get()
        self.assertIn("23:30 Europe/Riga (Long)", html)
        self.assertNotIn("(Short)", html)

    def test_it_shows_no_label_for_upcoming_window(self) -> None:
        self.add_window("Later", td(hours=1), td(hours=2))
        self.assertNotIn("label-maintenance", self.get())

    def test_it_shows_no_label_for_uncovered_check(self) -> None:
        self.add_window("Web only", -td(hours=1), td(hours=1), tags="web")
        self.assertNotIn("label-maintenance", self.get())

    def test_it_escapes_window_name(self) -> None:
        self.add_window(XSS, -td(hours=1), td(hours=1))
        html = self.get()
        self.assertNotIn(XSS, html)
        self.assertIn("(&lt;script&gt;alert(1)&lt;/script&gt;)", html)

    def test_status_json_is_unchanged(self) -> None:
        self.add_window("Postgres upgrade", -td(hours=1), td(hours=1))
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(f"/projects/{self.project.code}/checks/status/")
        doc = r.json()
        self.assertEqual(set(doc.keys()), {"details", "tags", "title"})
        self.assertEqual(
            set(doc["details"][0].keys()), {"code", "status", "last_ping", "started"}
        )
        self.assertNotIn("aintenance", r.content.decode())
