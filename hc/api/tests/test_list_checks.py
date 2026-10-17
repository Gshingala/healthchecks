from __future__ import annotations

from datetime import timedelta as td

from django.conf import settings
from django.utils.timezone import now

from hc.api.models import Channel, Check, MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse


class ListChecksTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.now = now().replace(microsecond=0)

        self.a1 = Check(project=self.project, name="Alice 1")
        self.a1.slug = "alice-1"
        self.a1.timeout = td(seconds=3600)
        self.a1.grace = td(seconds=900)
        self.a1.n_pings = 0
        self.a1.status = "new"
        self.a1.tags = "a1-tag a1-additional-tag"
        self.a1.desc = "This is description"
        self.a1.save()

        self.a2 = Check(project=self.project, name="Alice 2")
        self.a2.timeout = td(seconds=86400)
        self.a2.grace = td(seconds=3600)
        self.a2.last_ping = self.now
        self.a2.status = "up"
        self.a2.tags = "a2-tag"
        self.a2.save()

        self.c1 = Channel.objects.create(project=self.project)
        self.a1.channel_set.add(self.c1)

    def get(self, v: int = 1) -> TestHttpResponse:
        return self.client.get(f"/api/v{v}/checks/", HTTP_X_API_KEY="X" * 32)

    def test_it_works(self) -> None:
        # Expect 3 queries:
        # * check API key
        # * retrieve checks
        # * retrieve  channel codes
        with self.assertNumQueries(3):
            r = self.get()

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")

        doc = r.json()
        self.assertEqual(len(doc["checks"]), 2)

        by_name = {}
        for check in doc["checks"]:
            by_name[check["name"]] = check

        a1 = by_name["Alice 1"]
        self.assertEqual(a1["uuid"], str(self.a1.code))
        self.assertEqual(a1["timeout"], 3600)
        self.assertEqual(a1["grace"], 900)
        self.assertEqual(a1["ping_url"], self.a1.url())
        self.assertEqual(a1["last_ping"], None)
        self.assertEqual(a1["n_pings"], 0)
        self.assertEqual(a1["status"], "new")
        self.assertFalse(a1["started"])
        self.assertEqual(a1["channels"], str(self.c1.code))
        self.assertEqual(a1["desc"], "This is description")

        update_url = settings.SITE_ROOT + f"/api/v1/checks/{self.a1.code}"
        pause_url = update_url + "/pause"
        self.assertEqual(a1["update_url"], update_url)
        self.assertEqual(a1["pause_url"], pause_url)

        self.assertEqual(a1["next_ping"], None)
        self.assertFalse(a1["maintenance"])

        a2 = by_name["Alice 2"]
        self.assertEqual(a2["uuid"], str(self.a2.code))
        self.assertEqual(a2["timeout"], 86400)
        self.assertEqual(a2["grace"], 3600)
        self.assertEqual(a2["ping_url"], self.a2.url())
        self.assertEqual(a2["status"], "up")
        next_ping = self.now + td(seconds=86400)
        self.assertEqual(a2["last_ping"], self.now.isoformat())
        self.assertEqual(a2["next_ping"], next_ping.isoformat())

    def test_it_handles_options(self) -> None:
        r = self.client.options("/api/v1/checks/")
        self.assertEqual(r.status_code, 204)
        self.assertIn("GET", r["Access-Control-Allow-Methods"])

    def test_it_shows_only_users_checks(self) -> None:
        Check.objects.create(project=self.bobs_project, name="Bob 1")

        r = self.get()
        data = r.json()
        self.assertEqual(len(data["checks"]), 2)
        for check in data["checks"]:
            self.assertNotEqual(check["name"], "Bob 1")

    def test_it_works_with_tags_param(self) -> None:
        r = self.client.get("/api/v1/checks/?tag=a2-tag", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

        doc = r.json()
        self.assertTrue("checks" in doc)
        self.assertEqual(len(doc["checks"]), 1)

        check = doc["checks"][0]

        self.assertEqual(check["name"], "Alice 2")
        self.assertEqual(check["tags"], "a2-tag")

    def test_it_filters_with_multiple_tags_param(self) -> None:
        r = self.client.get(
            "/api/v1/checks/?tag=a1-tag&tag=a1-additional-tag", HTTP_X_API_KEY="X" * 32
        )
        self.assertEqual(r.status_code, 200)

        doc = r.json()
        self.assertTrue("checks" in doc)
        self.assertEqual(len(doc["checks"]), 1)

        check = doc["checks"][0]

        self.assertEqual(check["name"], "Alice 1")
        self.assertEqual(check["tags"], "a1-tag a1-additional-tag")

    def test_it_does_not_match_tag_partially(self) -> None:
        r = self.client.get("/api/v1/checks/?tag=tag", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

        doc = r.json()
        self.assertTrue("checks" in doc)
        self.assertEqual(len(doc["checks"]), 0)

    def test_non_existing_tags_filter_returns_empty_result(self) -> None:
        r = self.client.get(
            "/api/v1/checks/?tag=non_existing_tag_with_no_checks",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 200)

        doc = r.json()
        self.assertTrue("checks" in doc)
        self.assertEqual(len(doc["checks"]), 0)

    def test_readonly_key_works(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        # Expect a query to check the API key, and a query to retrieve checks
        with self.assertNumQueries(2):
            r = self.client.get("/api/v1/checks/", HTTP_X_API_KEY="R" * 32)

        self.assertEqual(r.status_code, 200)

        # When using readonly keys, the ping URLs should not be exposed:
        self.assertNotContains(r, str(self.a1.code))

    def test_v1_reports_status_started(self) -> None:
        self.a1.last_start = now()
        self.a1.save()
        self.a2.delete()

        r = self.get()
        self.assertEqual(r.status_code, 200)

        a1 = r.json()["checks"][0]
        self.assertEqual(a1["status"], "started")
        self.assertTrue(a1["started"])

    def test_v2_reports_started_separately(self) -> None:
        self.a1.last_start = now()
        self.a1.save()
        self.a2.delete()

        r = self.get(v=2)

        a1 = r.json()["checks"][0]
        self.assertEqual(a1["status"], "new")
        self.assertTrue(a1["started"])

    def add_window(self, tags: str = "", hours_from_now: int = 0) -> None:
        start = now() + td(hours=hours_from_now)
        MaintenanceWindow.objects.create(
            project=self.project,
            name="Deploy",
            start=start - td(minutes=5),
            end=start + td(hours=1),
            tags=tags,
            created_via="api",
        )

    def test_it_reports_maintenance(self) -> None:
        self.add_window(tags="a2-tag")
        for v in (1, 2, 3):
            r = self.get(v=v)
            self.assertEqual(r.status_code, 200)

            by_name = {c["name"]: c for c in r.json()["checks"]}
            self.assertFalse(by_name["Alice 1"]["maintenance"])
            self.assertTrue(by_name["Alice 2"]["maintenance"])

    def test_it_only_adds_maintenance_key(self) -> None:
        before = self.get(v=3).json()["checks"]
        self.add_window()
        after = self.get(v=3).json()["checks"]

        for check in before:
            self.assertFalse(check.pop("maintenance"))
        for check in after:
            self.assertTrue(check.pop("maintenance"))
        self.assertEqual(after, before)

    def test_it_reports_upcoming_window_as_no_maintenance(self) -> None:
        self.add_window(hours_from_now=2)
        with self.assertNumQueries(3):
            r = self.get(v=3)

        for check in r.json()["checks"]:
            self.assertFalse(check["maintenance"])

    def test_it_reports_maintenance_with_readonly_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()
        self.add_window()

        r = self.client.get("/api/v3/checks/", HTTP_X_API_KEY="R" * 32)
        for check in r.json()["checks"]:
            self.assertTrue(check["maintenance"])

    def test_it_uses_one_extra_query_with_one_window(self) -> None:
        self.add_window()
        with self.assertNumQueries(4):
            self.get(v=3)

    def test_it_uses_one_extra_query_with_many_windows_and_checks(self) -> None:
        Check.objects.bulk_create(
            Check(project=self.project, name=f"Bulk {i}") for i in range(498)
        )
        for i in range(50):
            self.add_window(tags=f"tag-{i}")

        with self.assertNumQueries(4):
            r = self.get(v=3)
        self.assertEqual(len(r.json()["checks"]), 500)

    def test_it_works_with_slug_param(self) -> None:
        r = self.client.get("/api/v1/checks/?slug=alice-1", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

        doc = r.json()
        self.assertEqual(len(doc["checks"]), 1)
        check = doc["checks"][0]
        self.assertEqual(check["name"], "Alice 1")
