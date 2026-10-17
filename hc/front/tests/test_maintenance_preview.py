from __future__ import annotations

from hc.api.models import Check
from hc.test import BaseTestCase, TestHttpResponse

XSS = "<script>alert(1)</script>"


class MaintenancePreviewTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/projects/{self.project.code}/maintenance/preview/"

    def get(self, query: str = "", user: str = "alice@example.org") -> TestHttpResponse:
        self.client.login(username=user, password="password")
        return self.client.get(self.url + query)

    def test_it_counts_matching_checks(self) -> None:
        for i in range(25):
            Check.objects.create(
                project=self.project, name=f"db-{i:02}", tags="db prod"
            )
        Check.objects.create(project=self.project, name="web", tags="web")
        Check.objects.create(project=self.charlies_project, name="other", tags="db")

        r = self.get("?scope=tags&tags=db")
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["count"], 25)
        self.assertEqual(len(doc["checks"]), 20)

        first = Check.objects.get(name="db-00")
        self.assertEqual(
            doc["checks"][0],
            {"name": "db-00", "url": f"/checks/{first.code}/details/"},
        )
        self.assertEqual(doc["checks"][19]["name"], "db-19")

    def test_it_requires_all_tags(self) -> None:
        Check.objects.create(project=self.project, name="a", tags="db prod")
        Check.objects.create(project=self.project, name="b", tags="db")

        doc = self.get("?scope=tags&tags=prod+db").json()
        self.assertEqual(doc["count"], 1)
        self.assertEqual(doc["checks"][0]["name"], "a")

    def test_it_handles_no_match(self) -> None:
        Check.objects.create(project=self.project, name="a", tags="db")
        doc = self.get("?scope=tags&tags=foo").json()
        self.assertEqual(doc, {"count": 0, "checks": []})

    def test_scope_all_matches_every_check(self) -> None:
        Check.objects.create(project=self.project, name="a", tags="db")
        Check.objects.create(project=self.project)

        for query in ("?scope=all&tags=foo", ""):
            doc = self.get(query).json()
            self.assertEqual(doc["count"], 2)

    def test_it_uses_name_then_code(self) -> None:
        check = Check.objects.create(project=self.project)
        doc = self.get().json()
        self.assertEqual(doc["checks"][0]["name"], str(check.code))

    def test_it_rejects_long_tags(self) -> None:
        r = self.get("?scope=foo&tags=" + "a" * 501)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "tags is too long"})

    def test_it_rejects_bad_scope(self) -> None:
        r = self.get("?scope=foo")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "invalid scope"})

    def test_it_returns_names_as_plain_json_text(self) -> None:
        Check.objects.create(project=self.project, name=XSS, tags=XSS)
        r = self.get("?scope=tags&tags=" + XSS)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertEqual(r.json()["checks"][0]["name"], XSS)

    def test_it_allows_readonly_member(self) -> None:
        self.bobs_membership.role = "r"
        self.bobs_membership.save()
        r = self.get(user="bob@example.org")
        self.assertEqual(r.status_code, 200)

    def test_it_checks_membership(self) -> None:
        Check.objects.create(project=self.project, name="Secret")
        r = self.get(user="charlie@example.org")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"Secret", r.content)

    def test_it_requires_login(self) -> None:
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accounts/login/"))
