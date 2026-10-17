from __future__ import annotations

from unittest.mock import Mock, patch

from django.test import TestCase


class ServeDocTestCase(TestCase):
    def test_it_serves_introduction(self) -> None:
        r = self.client.get("/docs/")
        self.assertEqual(r.status_code, 200)

        self.assertContains(r, "<strong>keeps silent</strong>")

    def test_it_serves_subpage(self) -> None:
        r = self.client.get("/docs/reliability_tips/")
        self.assertEqual(r.status_code, 200)

        self.assertContains(r, "Pinging Reliability Tips")

    def test_it_serves_maintenance_windows(self) -> None:
        r = self.client.get("/docs/maintenance_windows/")
        self.assertEqual(r.status_code, 200)

        self.assertContains(r, "<h1>Maintenance Windows</h1>", html=True)

    def test_it_lists_maintenance_windows_in_navigation(self) -> None:
        r = self.client.get("/docs/")
        self.assertContains(r, 'href="/docs/maintenance_windows/"')

    def test_api_docs_cover_maintenance_windows(self) -> None:
        r = self.client.get("/docs/api/")
        self.assertEqual(r.status_code, 200)

        for anchor in (
            "list-maintenance",
            "create-maintenance",
            "get-maintenance",
            "end-maintenance",
            "delete-maintenance",
        ):
            self.assertContains(r, f'id="{anchor}"')
        self.assertContains(r, "/api/v3/maintenance/")
        self.assertContains(r, '<span class="nt">"maintenance"</span>')

    def test_notifications_docs_link_to_maintenance_windows(self) -> None:
        r = self.client.get("/docs/configuring_notifications/")
        self.assertContains(r, 'href="../maintenance_windows/"')

    def test_it_handles_bad_url(self) -> None:
        r = self.client.get("/docs/does_not_exist/")
        self.assertEqual(r.status_code, 404)

    @patch("hc.front.views.settings.BASE_DIR")
    def test_it_rejects_bad_characters(self, mock_base_dir: Mock) -> None:
        self.client.get("/docs/NAUGHTY/")
        # URL dispatcher's slug filter lets the uppercase letters through,
        # but the view should still reject them, before any filesystem
        # operations
        self.assertEqual(len(mock_base_dir.mock_calls), 0)
