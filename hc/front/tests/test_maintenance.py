from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td

import time_machine

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
XSS = "<script>alert(1)</script>"


@time_machine.travel(CURRENT_TIME)
class MaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/projects/{self.project.code}/maintenance/"

    def add_window(
        self, name: str, start: td, end: td, **kwargs: object
    ) -> MaintenanceWindow:
        defaults: dict[str, object] = {
            "created_by": self.alice,
            "created_via": "dashboard",
        }
        defaults.update(kwargs)
        return MaintenanceWindow.objects.create(
            project=self.project,
            name=name,
            start=CURRENT_TIME + start,
            end=CURRENT_TIME + end,
            **defaults,
        )

    def test_it_works(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<h1>Maintenance</h1>", html=True)
        self.assertContains(r, f'href="{self.url}">Maintenance</a>')

    def test_nav_link_is_on_project_pages(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(f"/projects/{self.project.code}/checks/")
        self.assertContains(r, f'href="{self.url}">Maintenance</a>')

    def test_it_shows_empty_state_with_buttons(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertContains(r, "No maintenance windows yet.")
        self.assertContains(r, "Schedule&hellip;")
        self.assertContains(r, "Start Now&hellip;")
        self.assertContains(r, 'id="add-maintenance-modal"')
        self.assertContains(r, 'id="start-now-modal"')
        self.assertNotContains(r, 'id="maintenance-active"')
        self.assertNotContains(r, 'id="maintenance-upcoming"')
        self.assertNotContains(r, 'id="maintenance-ended"')

    def test_it_shows_sections_in_order(self) -> None:
        self.profile.tz = "Europe/Riga"
        self.profile.save()

        self.add_window("Active B", td(hours=-1), td(hours=3))
        self.add_window("Active A", td(hours=-2), td(hours=2))
        self.add_window("Upcoming B", td(days=2), td(days=3))
        self.add_window("Upcoming A", td(days=1), td(days=4))
        self.add_window("Ended A", td(days=-5), td(days=-4))
        self.add_window("Ended B", td(days=-3), td(days=-2))

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertNotContains(r, "No maintenance windows yet.")
        html = r.content.decode()

        order = [
            'id="maintenance-active"',
            "Active A",
            "Active B",
            'id="maintenance-upcoming"',
            "Upcoming A",
            "Upcoming B",
            'id="maintenance-ended"',
            "Ended B",
            "Ended A",
        ]
        positions = [html.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))
        self.assertContains(r, "Ended in the last 90 days")

        # 2026-11-01 10:00 UTC is 12:00 in Riga
        self.assertContains(r, "Nov 1, 2026 12:00")
        self.assertContains(r, '<span class="mw-tz">Europe/Riga</span>')
        self.assertContains(r, "Times are in your time zone, Europe/Riga.")

    def test_it_shows_scope_and_creator(self) -> None:
        self.add_window("By Alice", td(days=1), td(days=2), tags="db prod")
        self.add_window(
            "By API", td(days=1), td(days=2), created_by=None, created_via="api"
        )
        self.add_window("By gone user", td(days=1), td(days=2), created_by=None)

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertContains(r, '<span class="label label-tag">db</span>')
        self.assertContains(r, '<span class="label label-tag">prod</span>')
        self.assertContains(r, '<td class="mw-scope">All checks</td>', count=2)
        self.assertContains(r, "Created by alice@example.org")
        self.assertContains(r, "Created via API")
        self.assertContains(r, "Created by deleted user")

    def test_it_escapes_name_and_tags(self) -> None:
        self.add_window(XSS, td(days=1), td(days=2), tags=XSS)

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertNotContains(r, XSS)
        self.assertContains(r, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_it_prunes_old_windows(self) -> None:
        self.add_window("Old", td(days=-92), td(days=-91))
        self.add_window("Recent", td(days=-89), td(days=-88))

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertNotContains(r, "Old")
        self.assertContains(r, "Recent")
        self.assertFalse(MaintenanceWindow.objects.filter(name="Old").exists())

    def test_it_shows_row_actions_to_writers(self) -> None:
        mw = self.add_window("Upcoming", td(days=1), td(days=2))

        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.url)
        self.assertContains(r, f'data-target="#edit-{mw.code}"')

    def test_it_hides_controls_from_readonly_members(self) -> None:
        mw = self.add_window("Active", td(hours=-1), td(hours=1))
        self.bobs_membership.role = "r"
        self.bobs_membership.save()

        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Active")
        self.assertNotContains(r, "Schedule&hellip;")
        self.assertNotContains(r, "Start Now&hellip;")
        self.assertNotContains(r, "add-maintenance-modal")
        self.assertNotContains(r, "start-now-modal")
        self.assertNotContains(r, f"#edit-{mw.code}")
        self.assertNotContains(r, f"#end-{mw.code}")
        self.assertNotContains(r, f"#remove-{mw.code}")
        self.assertNotContains(r, "End Now")

    def test_it_checks_membership(self) -> None:
        self.add_window("Secret window", td(hours=-1), td(hours=1))

        self.client.login(username="charlie@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(r, "Secret window", status_code=404)

    def test_it_requires_login(self) -> None:
        r = self.client.get(self.url)
        self.assertRedirects(
            r, f"/accounts/login/?next={self.url}", fetch_redirect_response=False
        )
