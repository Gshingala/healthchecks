from __future__ import annotations

from datetime import timedelta as td

from django.utils.timezone import now

from hc.accounts.models import Project
from hc.api.models import Check, Flip, MaintenanceWindow, Ping
from hc.test import BaseTestCase


class StatusSingleTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check(project=self.project, name="Alice Was Here")
        self.check.save()

        self.url = f"/checks/{self.check.code}/status/"

    def test_it_works(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "new")
        self.assertIn("never received a ping", doc["status_text"])
        self.assertIn("not received any pings yet", doc["events"])

    def test_status_text_shows_elapsed_run_time(self) -> None:
        Ping.objects.create(owner=self.check, n=1, kind="start")
        self.check.status = "new"
        self.check.n_pings = 1
        self.check.last_start = now() - td(minutes=1)
        self.check.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "new")
        self.assertIn("This check is ready for pings.", doc["status_text"])
        self.assertIn("Currently running, started 1 min", doc["status_text"])

    def test_it_returns_403_for_anon_requests(self) -> None:
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 403)

    def test_it_returns_events(self) -> None:
        p = Ping.objects.create(owner=self.check, ua="test-user-agent", n=1)
        self.check.status = "up"
        self.check.last_ping = p.created
        self.check.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "up")
        self.assertEqual(doc["updated"], str(p.created.timestamp()))
        self.assertIn("test-user-agent", doc["events"])

    def test_it_omits_events(self) -> None:
        p = Ping.objects.create(owner=self.check, ua="test-user-agent", n=1)
        self.check.status = "up"
        self.check.last_ping = p.created
        self.check.save()

        timestamp = str(p.created.timestamp())
        url = self.url + f"?u={timestamp}"

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(url)
        doc = r.json()

        self.assertNotIn("events", doc)

    def test_it_allows_cross_team_access(self) -> None:
        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_it_handles_manual_resume(self) -> None:
        self.check.status = "paused"
        self.check.manual_resume = True
        self.check.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "paused")
        self.assertIn("will ignore pings until resumed", doc["status_text"])
        self.assertIn("resume-btn", doc["status_text"])

    def test_resume_requires_rw_access(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()

        self.check.status = "paused"
        self.check.manual_resume = True
        self.check.save()

        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "paused")
        self.assertIn("will ignore pings until resumed", doc["status_text"])
        self.assertNotIn("resume-btn", doc["status_text"])

    def test_it_shows_ignored_nonzero_exitstatus(self) -> None:
        p = Ping(owner=self.check)
        p.n = 1
        p.kind = "ign"
        p.exitstatus = 123
        p.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertIn("Ignored", doc["events"])

    def test_it_handles_log_event(self) -> None:
        p = Ping.objects.create(owner=self.check, kind="log", n=1)
        self.check.status = "up"
        self.check.last_ping = p.created
        self.check.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        doc = r.json()

        self.assertEqual(doc["status"], "up")
        self.assertEqual(doc["updated"], str(p.created.timestamp()))
        self.assertIn("label-log", doc["events"])

    def add_withheld_flip(
        self, project: Project | None = None, name: str = "Postgres upgrade"
    ) -> Flip:
        window = MaintenanceWindow.objects.create(
            project=project or self.project,
            name=name,
            start=now() - td(hours=2),
            end=now() + td(hours=1),
            created_via="dashboard",
        )
        return Flip.objects.create(
            owner=self.check,
            created=now(),
            old_status="up",
            new_status="down",
            withheld=now(),
            withheld_window=window.code,
        )

    def test_it_shows_withheld_window_name(self) -> None:
        self.add_withheld_flip()
        self.client.login(username="alice@example.org", password="password")
        html = self.client.get(self.url).json()["events"]
        self.assertIn('Alert not sent: maintenance window "Postgres upgrade"', html)

    def test_it_omits_name_of_deleted_window(self) -> None:
        self.add_withheld_flip()
        MaintenanceWindow.objects.filter(project=self.project).delete()
        self.client.login(username="alice@example.org", password="password")
        html = self.client.get(self.url).json()["events"]
        self.assertIn("Alert not sent: maintenance window</span>", html)

    def test_it_omits_name_of_window_from_another_project(self) -> None:
        self.add_withheld_flip(project=self.bobs_project)
        self.client.login(username="alice@example.org", password="password")
        html = self.client.get(self.url).json()["events"]
        self.assertIn("Alert not sent: maintenance window</span>", html)
        self.assertNotIn("Postgres upgrade", html)

    def test_it_escapes_withheld_window_name(self) -> None:
        self.add_withheld_flip(name="<script>alert(1)</script>")
        self.client.login(username="alice@example.org", password="password")
        html = self.client.get(self.url).json()["events"]
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
