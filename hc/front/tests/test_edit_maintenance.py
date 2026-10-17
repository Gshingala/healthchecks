from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td
from typing import Any
from unittest.mock import patch

import time_machine

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 1, 12, 0, 30, 500000, tzinfo=timezone.utc)
UTC = timezone.utc
STARTED = "This window has already started. Only its name and end time can be changed."
ENDED = "This maintenance window has ended and can no longer be changed."


@time_machine.travel(CURRENT_TIME, tick=False)
class EditMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.profile.tz = "Europe/Riga"
        self.profile.save()

        # Upcoming: 2026-11-07 22:00 to 23:30 in Riga
        self.upcoming = self.add_window(
            "Postgres upgrade",
            datetime(2026, 11, 7, 20, tzinfo=UTC),
            datetime(2026, 11, 7, 21, 30, tzinfo=UTC),
        )
        # Active: 2026-11-01 13:00:30 to 16:00 in Riga
        self.active = self.add_window(
            "Deploy",
            datetime(2026, 11, 1, 11, 0, 30, tzinfo=UTC),
            datetime(2026, 11, 1, 14, tzinfo=UTC),
            tags="db prod",
        )
        self.ended = self.add_window(
            "Old",
            datetime(2026, 10, 30, 10, tzinfo=UTC),
            datetime(2026, 10, 30, 11, tzinfo=UTC),
        )

        self.redirect_url = f"/projects/{self.project.code}/maintenance/"

    def add_window(
        self, name: str, start: datetime, end: datetime, **kwargs: Any
    ) -> MaintenanceWindow:
        defaults: dict[str, Any] = {
            "created_by": self.alice,
            "created_via": "dashboard",
        }
        defaults.update(kwargs)
        return MaintenanceWindow.objects.create(
            project=self.project, name=name, start=start, end=end, **defaults
        )

    def url(self, mw: MaintenanceWindow) -> str:
        return f"/projects/{self.project.code}/maintenance/{mw.code}/edit/"

    def post(self, mw: MaintenanceWindow, **kwargs: Any) -> Any:
        if mw == self.active:
            data = {
                "name": "Deploy",
                "start_date": "2026-11-01",
                "start_time": "13:00",
                "end_date": "2026-11-01",
                "end_time": "16:00",
                "scope": "tags",
                "tags": "db prod",
            }
        else:
            data = {
                "name": "Postgres upgrade",
                "start_date": "2026-11-07",
                "start_time": "22:00",
                "end_date": "2026-11-07",
                "end_time": "23:30",
                "scope": "all",
                "tags": "",
            }
        data.update(kwargs)
        self.client.login(username="alice@example.org", password="password")
        return self.client.post(self.url(mw), data)

    def test_it_edits_upcoming_window(self) -> None:
        code = self.upcoming.code
        self.client.login(username="bob@example.org", password="password")
        r = self.client.post(
            self.url(self.upcoming),
            {
                "name": "Postgres 17 upgrade",
                "start_date": "2026-11-08",
                "start_time": "01:00",
                "end_date": "2026-11-08",
                "end_time": "02:00",
                "scope": "tags",
                "tags": "db  prod db",
            },
        )
        self.assertRedirects(r, self.redirect_url, fetch_redirect_response=False)

        self.upcoming.refresh_from_db()
        self.assertEqual(self.upcoming.code, code)
        self.assertEqual(self.upcoming.created_by, self.alice)
        self.assertEqual(self.upcoming.name, "Postgres 17 upgrade")
        # Bob's time zone is UTC
        self.assertEqual(self.upcoming.start, datetime(2026, 11, 8, 1, tzinfo=UTC))
        self.assertEqual(self.upcoming.end, datetime(2026, 11, 8, 2, tzinfo=UTC))
        self.assertEqual(self.upcoming.tags, "db prod")

        r = self.client.get(self.redirect_url)
        self.assertContains(r, "Maintenance window updated.")

    def test_it_moves_past_start_to_now(self) -> None:
        self.post(self.upcoming, start_date="2026-10-30")
        self.upcoming.refresh_from_db()
        self.assertEqual(self.upcoming.start, CURRENT_TIME.replace(microsecond=0))

    def test_it_edits_name_and_end_of_active_window(self) -> None:
        for end_time, expected in (("15:00", 13), ("18:00", 16)):
            with self.subTest(end_time=end_time):
                r = self.post(self.active, name="Deploy v2", end_time=end_time)
                self.assertRedirects(
                    r, self.redirect_url, fetch_redirect_response=False
                )

                self.active.refresh_from_db()
                self.assertEqual(self.active.name, "Deploy v2")
                self.assertEqual(
                    self.active.end, datetime(2026, 11, 1, expected, tzinfo=UTC)
                )
                self.assertEqual(self.active.tags, "db prod")

    def test_it_ignores_seconds_of_stored_start(self) -> None:
        r = self.post(self.active, end_time="17:00")
        self.assertEqual(r.status_code, 302)

        self.active.refresh_from_db()
        self.assertEqual(
            self.active.start, datetime(2026, 11, 1, 11, 0, 30, tzinfo=UTC)
        )
        self.assertEqual(self.active.end, datetime(2026, 11, 1, 15, tzinfo=UTC))

    def test_it_accepts_unnormalised_unchanged_tags(self) -> None:
        r = self.post(self.active, tags="db prod db", end_time="17:00")
        self.assertEqual(r.status_code, 302)

    def test_it_rejects_start_or_scope_change_of_active_window(self) -> None:
        cases = [
            {"start_time": "13:01"},
            {"start_date": "2026-11-02"},
            {"scope": "all"},
            {"tags": "db"},
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                r = self.post(self.active, name="Changed", **kwargs)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, STARTED)
                self.assertContains(r, f'data-open-modal="edit-{self.active.code}"')

                self.active.refresh_from_db()
                self.assertEqual(self.active.name, "Deploy")
                self.assertEqual(self.active.tags, "db prod")

    def test_it_rejects_invalid_input(self) -> None:
        r = self.post(self.upcoming, name="Changed", end_time="21:00")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'data-open-modal="edit-{self.upcoming.code}"')
        self.assertContains(
            r,
            f'<div id="mw-{self.upcoming.code}-end-help" class="help-block">'
            "End must be after start.</div>",
            html=True,
        )
        # Entered values are kept
        self.assertContains(r, 'value="Changed"')
        self.assertContains(r, 'value="21:00"')

        self.upcoming.refresh_from_db()
        self.assertEqual(self.upcoming.name, "Postgres upgrade")

    def test_it_rejects_past_end_of_active_window(self) -> None:
        r = self.post(self.active, end_time="13:30")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "End must be in the future.")
        self.active.refresh_from_db()
        self.assertEqual(self.active.end, datetime(2026, 11, 1, 14, tzinfo=UTC))

    def test_it_rejects_ended_window(self) -> None:
        r = self.post(self.ended, name="Changed")
        self.assertContains(r, ENDED, status_code=400)
        self.ended.refresh_from_db()
        self.assertEqual(self.ended.name, "Old")

    @patch("hc.front.views.Project.update_next_nag_dates")
    def test_it_updates_next_nag_dates(self, mock: Any) -> None:
        self.post(self.upcoming)
        mock.assert_called_once()

    def test_it_rejects_readonly_member(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        self.client.login(username="bob@example.org", password="password")
        r = self.client.post(self.url(self.upcoming), {"name": "Changed"})
        self.assertEqual(r.status_code, 403)
        self.upcoming.refresh_from_db()
        self.assertEqual(self.upcoming.name, "Postgres upgrade")

    def test_it_checks_membership(self) -> None:
        self.client.login(username="charlie@example.org", password="password")
        r = self.client.post(self.url(self.upcoming), {"name": "Changed"})
        self.assertEqual(r.status_code, 404)

    def test_it_rejects_window_of_another_project(self) -> None:
        foreign = MaintenanceWindow.objects.create(
            project=self.bobs_project,
            name="Bob's",
            start=CURRENT_TIME + td(days=1),
            end=CURRENT_TIME + td(days=2),
            created_via="api",
        )
        self.client.login(username="bob@example.org", password="password")
        r = self.client.post(self.url(foreign), {"name": "Changed"})
        self.assertEqual(r.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "Bob's")

    def test_it_requires_login(self) -> None:
        r = self.client.post(self.url(self.upcoming), {"name": "Changed"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accounts/login/"))

    def test_it_requires_post(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url(self.upcoming))
        self.assertEqual(r.status_code, 405)

    def test_page_has_edit_modals(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.redirect_url)
        self.assertContains(r, f'id="edit-{self.upcoming.code}"')
        self.assertContains(r, f'id="edit-{self.active.code}"')
        self.assertNotContains(r, f'id="edit-{self.ended.code}"')
        self.assertContains(r, f'action="{self.url(self.upcoming)}"')
        self.assertContains(r, "Edit Maintenance Window")

        # The upcoming window's current values are pre-filled in the user's tz
        self.assertContains(r, f'id="mw-{self.upcoming.code}-name"')
        self.assertContains(r, 'value="2026-11-07"')
        self.assertContains(r, 'value="23:30"')

    def test_active_edit_modal_posts_hidden_start_and_scope(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.redirect_url)
        self.assertContains(r, STARTED)
        for name, value in (
            ("start_date", "2026-11-01"),
            ("start_time", "13:00"),
            ("scope", "tags"),
            ("tags", "db prod"),
        ):
            self.assertContains(
                r, f'<input type="hidden" name="{name}" value="{value}">', html=True
            )
        self.assertContains(r, '<p class="form-control-static">', count=2)

    def test_readonly_page_has_no_edit_modals(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.redirect_url)
        self.assertNotContains(r, f'id="edit-{self.upcoming.code}"')
        self.assertNotContains(r, "Edit Maintenance Window")
