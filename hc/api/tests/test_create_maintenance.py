from __future__ import annotations

import json
from datetime import datetime, timezone
from datetime import timedelta as td
from typing import Any
from unittest.mock import patch

from time_machine import travel

from hc.api.models import MaintenanceWindow
from hc.test import BaseTestCase, TestHttpResponse

CURRENT_TIME = datetime(2026, 11, 7, 12, 0, 0, 500000, tzinfo=timezone.utc)
NOW_SECONDS = CURRENT_TIME.replace(microsecond=0)


@travel(CURRENT_TIME, tick=False)
class CreateMaintenanceTestCase(BaseTestCase):
    def post(
        self, data: Any, v: int = 3, api_key: str | None = "X" * 32
    ) -> TestHttpResponse:
        url = f"/api/v{v}/maintenance/"
        if api_key is None:
            return self.csrf_client.post(url, data, content_type="application/json")
        return self.csrf_client.post(
            url, data, content_type="application/json", HTTP_X_API_KEY=api_key
        )

    def assert_rejected(self, data: Any, message: str, status: int = 400) -> None:
        r = self.post(data)
        self.assertEqual(r.status_code, status, data)
        self.assertEqual(r.json(), {"error": message}, data)
        self.assertFalse(MaintenanceWindow.objects.exists())

    def test_it_works(self) -> None:
        for v in (1, 2, 3):
            r = self.post({"name": "Deploy 42", "duration": 3600}, v=v)
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r["Access-Control-Allow-Origin"], "*")

            doc = r.json()
            window = MaintenanceWindow.objects.get(code=doc["uuid"])
            self.assertEqual(doc, window.to_dict())
            self.assertEqual(doc["name"], "Deploy 42")
            self.assertEqual(doc["start"], "2026-11-07T12:00:00+00:00")
            self.assertEqual(doc["end"], "2026-11-07T13:00:00+00:00")
            self.assertEqual(doc["scope"], "all")
            self.assertEqual(doc["tags"], "")
            self.assertEqual(doc["state"], "active")
            self.assertEqual(doc["created_via"], "api")

            self.assertEqual(window.project, self.project)
            self.assertEqual(window.start, NOW_SECONDS)
            self.assertEqual(window.end, NOW_SECONDS + td(seconds=3600))
            self.assertIsNone(window.created_by)

    def test_it_converts_times_to_utc(self) -> None:
        r = self.post(
            {
                "name": "Postgres upgrade",
                "start": "2026-11-07T22:00:00+02:00",
                "end": "2026-11-07T23:30:00.750+02:00",
                "tags": "db prod",
            }
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["state"], "upcoming")
        self.assertEqual(r.json()["scope"], "tags")

        window = MaintenanceWindow.objects.get()
        self.assertEqual(window.start, datetime(2026, 11, 7, 20, tzinfo=timezone.utc))
        self.assertEqual(window.end, datetime(2026, 11, 7, 21, 30, tzinfo=timezone.utc))
        self.assertEqual(window.end.microsecond, 0)
        self.assertEqual(window.tags, "db prod")

    def test_it_moves_past_start_to_now(self) -> None:
        r = self.post(
            {"name": "Late", "start": "2026-11-07T10:00:00Z", "duration": 600}
        )
        self.assertEqual(r.status_code, 201)

        window = MaintenanceWindow.objects.get()
        self.assertEqual(window.start, NOW_SECONDS)
        self.assertEqual(window.end, NOW_SECONDS + td(seconds=600))

    def test_it_counts_duration_from_future_start(self) -> None:
        r = self.post(
            {"name": "Later", "start": "2026-11-08T00:00:00Z", "duration": 60}
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["end"], "2026-11-08T00:01:00+00:00")

    def test_it_normalizes_tags(self) -> None:
        r = self.post({"name": "Tags", "duration": 60, "tags": "  db  prod db "})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(MaintenanceWindow.objects.get().tags, "db prod")

    def test_it_strips_name(self) -> None:
        r = self.post({"name": "  Deploy  ", "duration": 60})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(MaintenanceWindow.objects.get().name, "Deploy")

    def test_it_accepts_api_key_in_post_body(self) -> None:
        payload = {"name": "Deploy", "duration": 60, "api_key": "X" * 32}
        r = self.post(payload, api_key=None)
        self.assertEqual(r.status_code, 201)

    def test_it_accepts_name_of_100_chars(self) -> None:
        r = self.post({"name": "a" * 100, "duration": 60})
        self.assertEqual(r.status_code, 201)

    def test_it_accepts_duration_bounds(self) -> None:
        for duration in (60, 2592000):
            r = self.post({"name": "Bounds", "duration": duration})
            self.assertEqual(r.status_code, 201, duration)

    def test_it_requires_name(self) -> None:
        self.assert_rejected(
            {"duration": 60}, "json validation error: name is required"
        )

    def test_it_rejects_long_name(self) -> None:
        self.assert_rejected(
            {"name": "a" * 101, "duration": 60},
            "json validation error: name is too long",
        )

    def test_it_rejects_empty_name(self) -> None:
        for name in ("", "   "):
            self.assert_rejected(
                {"name": name, "duration": 60},
                "json validation error: name must not be empty",
            )

    def test_it_rejects_non_string_fields(self) -> None:
        for field, value in [
            ("name", None),
            ("name", 5),
            ("start", 5),
            ("end", True),
            ("tags", ["db"]),
        ]:
            data: dict[str, Any] = {"name": "Deploy", "duration": 60}
            if field == "end":
                del data["duration"]
            data[field] = value
            message = f"json validation error: {field} is not a string"
            self.assert_rejected(data, message)

    def test_it_rejects_bad_start(self) -> None:
        for start in ("tomorrow", "2026-11-07T22:00:00", "2026-11-07"):
            self.assert_rejected(
                {"name": "Deploy", "start": start, "duration": 60},
                "json validation error: start must be an ISO 8601 date-time "
                "with a time zone",
            )

    def test_it_rejects_bad_end(self) -> None:
        for end in ("later", "2026-11-07T23:00:00"):
            self.assert_rejected(
                {"name": "Deploy", "end": end},
                "json validation error: end must be an ISO 8601 date-time "
                "with a time zone",
            )

    def test_it_requires_exactly_one_of_end_and_duration(self) -> None:
        for data in [
            {"name": "Deploy"},
            {"name": "Deploy", "end": "2026-11-07T13:00:00Z", "duration": 60},
        ]:
            self.assert_rejected(
                data, "json validation error: provide exactly one of end or duration"
            )

    def test_it_rejects_duration_out_of_range(self) -> None:
        for duration in (59, 0, -60, 2592001):
            self.assert_rejected(
                {"name": "Deploy", "duration": duration},
                "json validation error: duration must be an integer "
                "between 60 and 2592000",
            )

    def test_it_rejects_non_integer_duration(self) -> None:
        for duration in ("3600", 1.5, True, None):
            self.assert_rejected(
                {"name": "Deploy", "duration": duration},
                "json validation error: duration is not a number",
            )

    def test_it_rejects_long_tags(self) -> None:
        self.assert_rejected(
            {"name": "Deploy", "duration": 60, "tags": "a" * 501},
            "json validation error: tags is too long",
        )

    def test_it_reports_first_failing_field(self) -> None:
        self.assert_rejected(
            {"name": "", "start": "bad", "duration": 1},
            "json validation error: name must not be empty",
        )

    def test_it_rejects_end_before_start(self) -> None:
        self.assert_rejected(
            {
                "name": "Deploy",
                "start": "2026-11-08T12:00:00Z",
                "end": "2026-11-08T11:00:00Z",
            },
            "end must be after start",
        )

    def test_it_rejects_past_end_as_end_before_start(self) -> None:
        # A start at or before now moves to now, so a past end always fails
        # the end-after-start rule first.
        self.assert_rejected(
            {"name": "Deploy", "end": "2026-11-07T11:00:00Z"},
            "end must be after start",
        )

    def test_it_maps_end_in_past_error(self) -> None:
        with patch(
            "hc.api.views.MaintenanceWindow.clean_times",
            side_effect=MaintenanceWindow.Invalid("end_in_past"),
        ):
            self.assert_rejected(
                {"name": "Deploy", "end": "2026-11-07T13:00:00Z"},
                "end must be in the future",
            )

    def test_it_rejects_too_long_window(self) -> None:
        self.assert_rejected(
            {
                "name": "Deploy",
                "start": "2026-11-08T00:00:00Z",
                "end": "2026-12-08T00:00:01Z",
            },
            "maintenance window can be at most 30 days long",
        )

    def test_it_accepts_30_day_window(self) -> None:
        r = self.post(
            {
                "name": "Deploy",
                "start": "2026-11-08T00:00:00Z",
                "end": "2026-12-08T00:00:00Z",
            }
        )
        self.assertEqual(r.status_code, 201)

    def test_it_handles_invalid_json(self) -> None:
        self.assert_rejected("this is not json", "could not parse request body")

    def test_it_handles_non_object_json(self) -> None:
        self.assert_rejected(
            json.dumps(["name"]), "json validation error: value is not an object"
        )

    def test_it_enforces_limit(self) -> None:
        windows = [
            MaintenanceWindow(
                project=self.project,
                name=f"Window {i}",
                start=CURRENT_TIME + td(hours=i - 1),
                end=CURRENT_TIME + td(hours=i),
                created_via="api",
            )
            for i in range(1, 101)
        ]
        MaintenanceWindow.objects.bulk_create(windows)

        r = self.post({"name": "One too many", "duration": 60})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(
            r.json(),
            {"error": "too many upcoming or active maintenance windows (limit 100)"},
        )
        self.assertEqual(MaintenanceWindow.objects.count(), 100)

    def test_it_does_not_count_ended_windows_toward_limit(self) -> None:
        # One ended and 99 active windows
        ended_end = CURRENT_TIME - td(hours=1)
        active_end = CURRENT_TIME + td(hours=1)
        windows = [
            MaintenanceWindow(
                project=self.project,
                name=f"Window {i}",
                start=CURRENT_TIME - td(hours=2),
                end=ended_end if i == 0 else active_end,
                created_via="api",
            )
            for i in range(100)
        ]
        MaintenanceWindow.objects.bulk_create(windows)

        r = self.post({"name": "Fits", "duration": 60})
        self.assertEqual(r.status_code, 201)

    def test_it_prunes_old_windows(self) -> None:
        old = MaintenanceWindow.objects.create(
            project=self.project,
            name="Old",
            start=CURRENT_TIME - td(days=91),
            end=CURRENT_TIME - td(days=90, seconds=1),
            created_via="api",
        )
        kept = MaintenanceWindow.objects.create(
            project=self.project,
            name="Kept",
            start=CURRENT_TIME - td(days=91),
            end=CURRENT_TIME - td(days=90) + td(seconds=1),
            created_via="api",
        )

        r = self.post({"name": "Deploy", "duration": 60})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(MaintenanceWindow.objects.filter(id=old.id).exists())
        self.assertTrue(MaintenanceWindow.objects.filter(id=kept.id).exists())

    def test_it_updates_next_nag_dates(self) -> None:
        with patch("hc.api.views.Project.update_next_nag_dates", autospec=True) as mock:
            r = self.post({"name": "Deploy", "duration": 60})

        self.assertEqual(r.status_code, 201)
        mock.assert_called_once()
        self.assertEqual(mock.call_args.args[0].id, self.project.id)

    def test_it_does_not_update_nag_dates_on_error(self) -> None:
        with patch("hc.api.views.Project.update_next_nag_dates", autospec=True) as mock:
            r = self.post({"name": "Deploy"})

        self.assertEqual(r.status_code, 400)
        mock.assert_not_called()

    def test_it_handles_missing_api_key(self) -> None:
        r = self.post({"name": "Deploy", "duration": 60}, api_key=None)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_short_api_key(self) -> None:
        r = self.post({"name": "Deploy", "duration": 60}, api_key="X")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "missing api key"})

    def test_it_handles_wrong_api_key(self) -> None:
        r = self.post({"name": "Deploy", "duration": 60}, api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "wrong api key"})

    def test_it_rejects_read_only_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        for v in (1, 2, 3):
            r = self.post({"name": "Deploy", "duration": 60}, v=v, api_key="R" * 32)
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "wrong api key"})
        self.assertFalse(MaintenanceWindow.objects.exists())
