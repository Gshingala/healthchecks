from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td
from typing import Any
from unittest.mock import patch

import time_machine

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 1, 12, 0, 30, 500000, tzinfo=timezone.utc)
NOT_UPCOMING = (
    "Only upcoming maintenance windows can be deleted. "
    "Use End now to stop an active window."
)


@time_machine.travel(CURRENT_TIME, tick=False)
class RemoveMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.upcoming = self.add_window("Postgres upgrade", td(days=1), td(days=2))
        self.redirect_url = f"/projects/{self.project.code}/maintenance/"

    def add_window(
        self, name: str, start: td, end: td, project: Any = None
    ) -> MaintenanceWindow:
        return MaintenanceWindow.objects.create(
            project=project or self.project,
            name=name,
            start=CURRENT_TIME + start,
            end=CURRENT_TIME + end,
            created_by=self.alice,
            created_via="dashboard",
        )

    def url(self, mw: MaintenanceWindow) -> str:
        return f"/projects/{self.project.code}/maintenance/{mw.code}/remove/"

    def post(self, mw: MaintenanceWindow, user: str = "alice@example.org") -> Any:
        self.client.login(username=user, password="password")
        return self.client.post(self.url(mw))

    def test_it_deletes_upcoming_window(self) -> None:
        r = self.post(self.upcoming, user="bob@example.org")
        self.assertRedirects(r, self.redirect_url, fetch_redirect_response=False)
        self.assertFalse(MaintenanceWindow.objects.exists())

        r = self.client.get(self.redirect_url)
        self.assertContains(r, "Maintenance window deleted.")

    def test_it_rejects_active_and_ended_windows(self) -> None:
        active = self.add_window("Deploy", td(hours=-1), td(hours=1))
        ended = self.add_window("Old", td(days=-2), td(days=-1))
        for mw in (active, ended):
            with self.subTest(name=mw.name):
                r = self.post(mw)
                self.assertContains(r, NOT_UPCOMING, status_code=400)
                self.assertTrue(MaintenanceWindow.objects.filter(code=mw.code).exists())

    @patch("hc.front.views.Project.update_next_nag_dates")
    def test_it_updates_next_nag_dates(self, mock: Any) -> None:
        self.post(self.upcoming)
        mock.assert_called_once()

    def test_it_rejects_readonly_member(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        r = self.post(self.upcoming, user="bob@example.org")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(MaintenanceWindow.objects.exists())

    def test_it_checks_membership(self) -> None:
        r = self.post(self.upcoming, user="charlie@example.org")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(MaintenanceWindow.objects.exists())

    def test_it_rejects_window_of_another_project(self) -> None:
        foreign = self.add_window("Bob's", td(days=1), td(days=2), self.bobs_project)
        r = self.post(foreign, user="bob@example.org")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(MaintenanceWindow.objects.filter(code=foreign.code).exists())

    def test_it_requires_login(self) -> None:
        r = self.client.post(self.url(self.upcoming))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accounts/login/"))

    def test_it_requires_post(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url(self.upcoming))
        self.assertEqual(r.status_code, 405)

    def test_page_has_remove_modal_for_upcoming_window_only(self) -> None:
        active = self.add_window("Deploy", td(hours=-1), td(hours=1))
        ended = self.add_window("Old", td(days=-2), td(days=-1))
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.redirect_url)
        self.assertContains(r, f'id="remove-{self.upcoming.code}"')
        self.assertNotContains(r, f'id="end-{self.upcoming.code}"')
        self.assertNotContains(r, f'id="remove-{active.code}"')
        for suffix in ("edit", "end", "remove"):
            self.assertNotContains(r, f'id="{suffix}-{ended.code}"')
        self.assertContains(r, f'action="{self.url(self.upcoming)}"')
        self.assertContains(r, "<h4>Delete Maintenance Window?</h4>", html=True)
        self.assertContains(r, 'data-pending-text="Deleting&hellip;"')
