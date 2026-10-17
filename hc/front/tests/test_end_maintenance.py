from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td
from typing import Any
from unittest.mock import patch

import time_machine

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 1, 12, 0, 30, 500000, tzinfo=timezone.utc)
ENDED = "This maintenance window has ended and can no longer be changed."
NOT_STARTED = "This maintenance window has not started yet. Delete it instead."


@time_machine.travel(CURRENT_TIME, tick=False)
class EndMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.active = self.add_window("Deploy", td(hours=-1), td(hours=2))
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
        return f"/projects/{self.project.code}/maintenance/{mw.code}/end/"

    def post(self, mw: MaintenanceWindow, user: str = "alice@example.org") -> Any:
        self.client.login(username=user, password="password")
        return self.client.post(self.url(mw))

    def test_it_ends_active_window(self) -> None:
        r = self.post(self.active, user="bob@example.org")
        self.assertRedirects(r, self.redirect_url, fetch_redirect_response=False)

        self.active.refresh_from_db()
        self.assertEqual(self.active.end, CURRENT_TIME.replace(microsecond=0))

        r = self.client.get(self.redirect_url)
        self.assertContains(r, "Maintenance window ended.")
        html = r.content.decode()
        self.assertNotIn('id="maintenance-active"', html)
        self.assertLess(html.index('id="maintenance-ended"'), html.index("Deploy</"))

    def test_it_rejects_upcoming_window(self) -> None:
        upcoming = self.add_window("Later", td(days=1), td(days=2))
        r = self.post(upcoming)
        self.assertContains(r, NOT_STARTED, status_code=400)
        upcoming.refresh_from_db()
        self.assertEqual(upcoming.end, CURRENT_TIME + td(days=2))

    def test_it_rejects_ended_window(self) -> None:
        ended = self.add_window("Old", td(days=-2), td(days=-1))
        r = self.post(ended)
        self.assertContains(r, ENDED, status_code=400)
        ended.refresh_from_db()
        self.assertEqual(ended.end, CURRENT_TIME - td(days=1))

    @patch("hc.front.views.Project.update_next_nag_dates")
    def test_it_updates_next_nag_dates(self, mock: Any) -> None:
        self.post(self.active)
        mock.assert_called_once()

    def test_it_rejects_readonly_member(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        r = self.post(self.active, user="bob@example.org")
        self.assertEqual(r.status_code, 403)
        self.active.refresh_from_db()
        self.assertEqual(self.active.end, CURRENT_TIME + td(hours=2))

    def test_it_checks_membership(self) -> None:
        r = self.post(self.active, user="charlie@example.org")
        self.assertEqual(r.status_code, 404)

    def test_it_rejects_window_of_another_project(self) -> None:
        foreign = self.add_window("Bob's", td(hours=-1), td(hours=1), self.bobs_project)
        r = self.post(foreign, user="bob@example.org")
        self.assertEqual(r.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.end, CURRENT_TIME + td(hours=1))

    def test_it_requires_login(self) -> None:
        r = self.client.post(self.url(self.active))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accounts/login/"))

    def test_it_requires_post(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url(self.active))
        self.assertEqual(r.status_code, 405)

    def test_page_has_end_modal_for_active_window_only(self) -> None:
        upcoming = self.add_window("Later", td(days=1), td(days=2))
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.redirect_url)
        self.assertContains(r, f'id="end-{self.active.code}"')
        self.assertNotContains(r, f'id="end-{upcoming.code}"')
        self.assertNotContains(r, f'id="remove-{self.active.code}"')
        self.assertContains(r, f'action="{self.url(self.active)}"')
        self.assertContains(r, "<h4>End &quot;Deploy&quot; Now?</h4>", html=True)
        self.assertContains(r, 'data-pending-text="Ending&hellip;"')
