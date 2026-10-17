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


@time_machine.travel(CURRENT_TIME, tick=False)
class AddMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.profile.tz = "Europe/Riga"
        self.profile.save()

        self.url = f"/projects/{self.project.code}/maintenance/add/"
        self.redirect_url = f"/projects/{self.project.code}/maintenance/"

    def post(self, **kwargs: Any) -> Any:
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
        return self.client.post(self.url, data)

    def start_now(self, **kwargs: Any) -> Any:
        data = {
            "name": "Deploy",
            "scope": "tags",
            "tags": "db",
            "duration_minutes": "60",
        }
        data.update(kwargs)
        self.client.login(username="alice@example.org", password="password")
        return self.client.post(self.url, data)

    def test_it_schedules_window(self) -> None:
        r = self.post()
        self.assertRedirects(r, self.redirect_url, fetch_redirect_response=False)

        mw = MaintenanceWindow.objects.get()
        self.assertEqual(mw.project, self.project)
        self.assertEqual(mw.name, "Postgres upgrade")
        self.assertEqual(mw.start, datetime(2026, 11, 7, 20, tzinfo=UTC))
        self.assertEqual(mw.end, datetime(2026, 11, 7, 21, 30, tzinfo=UTC))
        self.assertEqual(mw.tags, "")
        self.assertEqual(mw.created_by, self.alice)
        self.assertEqual(mw.created_via, "dashboard")

        r = self.client.get(self.redirect_url)
        self.assertContains(r, "Maintenance window scheduled.")
        html = r.content.decode()
        self.assertNotIn('id="maintenance-active"', html)
        self.assertLess(
            html.index('id="maintenance-upcoming"'), html.index("Postgres upgrade</")
        )

    def test_it_starts_window_with_past_start(self) -> None:
        self.post(start_date="2026-10-30")
        mw = MaintenanceWindow.objects.get()
        self.assertEqual(mw.start, CURRENT_TIME.replace(microsecond=0))

        r = self.client.get(self.redirect_url)
        html = r.content.decode()
        self.assertLess(
            html.index('id="maintenance-active"'), html.index("Postgres upgrade</")
        )
        self.assertNotIn('id="maintenance-upcoming"', html)

    def test_it_stores_ambiguous_time_as_first_occurrence(self) -> None:
        with time_machine.travel("2026-10-20 00:00+00:00", tick=False):
            self.post(
                start_date="2026-10-25",
                start_time="03:30",
                end_date="2026-10-25",
                end_time="05:00",
            )

        mw = MaintenanceWindow.objects.get()
        self.assertEqual(mw.start, datetime(2026, 10, 25, 0, 30, tzinfo=UTC))

    def test_it_rejects_invalid_input(self) -> None:
        nonexistent = (
            "2027-03-28 03:30 does not exist in Europe/Riga because of "
            "a daylight-saving change. Choose another time."
        )
        cases = [
            ({"name": ""}, "Enter a name of 1 to 100 characters."),
            ({"start_date": "foo"}, "Enter a valid start date and time."),
            (
                {
                    "start_date": "2027-03-28",
                    "start_time": "03:30",
                    "end_date": "2027-03-28",
                },
                nonexistent,
            ),
            ({"end_time": "99:99"}, "Enter a valid end date and time."),
            ({"end_time": "21:00"}, "End must be after start."),
            (
                {"end_date": "2026-12-08"},
                "A maintenance window can be at most 30 days long.",
            ),
            ({"scope": "foo"}, "Choose a scope."),
            ({"scope": "tags", "tags": ""}, "Enter at least one tag."),
            (
                {"scope": "tags", "tags": "a" * 501},
                "Tags can be at most 500 characters.",
            ),
        ]
        for kwargs, message in cases:
            with self.subTest(message=message):
                r = self.post(**kwargs)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'data-open-modal="add"')
                self.assertContains(r, message)
                self.assertContains(r, 'aria-invalid="true"')
                self.assertFalse(MaintenanceWindow.objects.exists())

    def test_error_is_shown_in_help_block(self) -> None:
        r = self.post(end_time="21:00")
        self.assertContains(
            r,
            '<div id="mw-add-end-help" class="help-block">End must be after start.</div>',
            html=True,
        )
        # Entered values are kept
        self.assertContains(r, 'value="2026-11-07"')
        self.assertContains(r, 'value="21:00"')

    def test_it_enforces_limit(self) -> None:
        for i in range(100):
            MaintenanceWindow.objects.create(
                project=self.project,
                name=f"W{i}",
                start=CURRENT_TIME + td(days=1),
                end=CURRENT_TIME + td(days=2),
                created_via="api",
            )

        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-open-modal="add"')
        self.assertContains(
            r,
            "This project already has 100 upcoming or active maintenance windows. "
            "End or delete one before adding another.",
        )
        self.assertEqual(MaintenanceWindow.objects.count(), 100)

    def test_it_prunes_on_add(self) -> None:
        MaintenanceWindow.objects.create(
            project=self.project,
            name="Old",
            start=CURRENT_TIME - td(days=100),
            end=CURRENT_TIME - td(days=99),
            created_via="api",
        )
        self.post()
        self.assertFalse(MaintenanceWindow.objects.filter(name="Old").exists())

    def test_it_allows_duplicates(self) -> None:
        self.post()
        self.post()
        self.assertEqual(MaintenanceWindow.objects.count(), 2)

    @patch("hc.front.views.Project.update_next_nag_dates")
    def test_it_updates_next_nag_dates(self, mock: Any) -> None:
        self.post()
        mock.assert_called_once()

    def test_it_starts_now(self) -> None:
        r = self.start_now()
        self.assertRedirects(r, self.redirect_url, fetch_redirect_response=False)

        mw = MaintenanceWindow.objects.get()
        start = CURRENT_TIME.replace(microsecond=0)
        self.assertEqual(mw.start, start)
        self.assertEqual(mw.end, start + td(minutes=60))
        self.assertEqual(mw.tags, "db")
        self.assertEqual(mw.created_by, self.alice)
        self.assertEqual(mw.created_via, "dashboard")

        r = self.client.get(self.redirect_url)
        self.assertContains(r, "Maintenance window started.")

    def test_start_now_accepts_bounds(self) -> None:
        self.start_now(duration_minutes="1")
        self.start_now(duration_minutes="43200")
        lengths = sorted(mw.end - mw.start for mw in MaintenanceWindow.objects.all())
        self.assertEqual(lengths, [td(minutes=1), td(days=30)])

    def test_start_now_rejects_bad_duration(self) -> None:
        for value in ("0", "43201"):
            r = self.start_now(duration_minutes=value)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'data-open-modal="start-now"')
            self.assertContains(r, "Enter a length of 1 to 43200 minutes.")
            self.assertContains(r, f'value="{value}"')
        self.assertFalse(MaintenanceWindow.objects.exists())

    def test_it_rejects_readonly_member(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        self.client.login(username="bob@example.org", password="password")
        r = self.client.post(
            self.url, {"name": "x", "scope": "all", "duration_minutes": "60"}
        )
        self.assertEqual(r.status_code, 403)
        self.assertFalse(MaintenanceWindow.objects.exists())

    def test_it_allows_regular_member(self) -> None:
        self.client.login(username="bob@example.org", password="password")
        r = self.client.post(
            self.url, {"name": "x", "scope": "all", "duration_minutes": "60"}
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(MaintenanceWindow.objects.get().created_by, self.bob)

    def test_it_checks_membership(self) -> None:
        self.client.login(username="charlie@example.org", password="password")
        r = self.client.post(
            self.url, {"name": "x", "scope": "all", "duration_minutes": "60"}
        )
        self.assertEqual(r.status_code, 404)
        self.assertFalse(MaintenanceWindow.objects.exists())

    def test_it_requires_login(self) -> None:
        r = self.client.post(
            self.url, {"name": "x", "scope": "all", "duration_minutes": "60"}
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accounts/login/"))

    def test_it_requires_post(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 405)
