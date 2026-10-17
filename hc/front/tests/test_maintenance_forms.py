from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from django.test import SimpleTestCase

from hc.front.forms import (
    MAINTENANCE_FORM_ERRORS,
    MaintenanceWindowForm,
    StartNowForm,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 12, 0, 30, 123456, tzinfo=UTC)


def _data(**kwargs: Any) -> dict[str, Any]:
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
    return data


class MaintenanceWindowFormTestCase(SimpleTestCase):
    def form(self, tz: str = "Europe/Riga", **kwargs: Any) -> MaintenanceWindowForm:
        return MaintenanceWindowForm(_data(**kwargs), tz=tz)

    def test_it_converts_local_times_to_utc(self) -> None:
        form = self.form()
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["start"], datetime(2026, 11, 7, 20, tzinfo=UTC)
        )
        self.assertEqual(
            form.cleaned_data["end"], datetime(2026, 11, 7, 21, 30, tzinfo=UTC)
        )
        self.assertEqual(form.cleaned_data["tags"], "")

    def test_it_clears_tags_for_scope_all(self) -> None:
        form = self.form(tags="db prod")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["tags"], "")

    def test_it_normalizes_tags(self) -> None:
        form = self.form(scope="tags", tags="  db  prod db ")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["tags"], "db prod")

    def test_it_rejects_missing_name(self) -> None:
        form = self.form(name="   ")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["name"], ["Enter a name of 1 to 100 characters."])

    def test_it_rejects_long_name(self) -> None:
        form = self.form(name="a" * 101)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["name"], ["Enter a name of 1 to 100 characters."])

    def test_it_rejects_bad_start(self) -> None:
        form = self.form(start_date="2026-13-01")
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["start_date"], ["Enter a valid start date and time."]
        )

    def test_it_rejects_missing_start_time(self) -> None:
        form = self.form(start_time="")
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["start_time"], ["Enter a valid start date and time."]
        )

    def test_it_rejects_bad_end(self) -> None:
        form = self.form(end_time="25:00")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["end_time"], ["Enter a valid end date and time."])

    def test_it_rejects_nonexistent_start(self) -> None:
        form = self.form(
            start_date="2027-03-28",
            start_time="03:30",
            end_date="2027-03-28",
            end_time="06:00",
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["start_date"],
            [
                "2027-03-28 03:30 does not exist in Europe/Riga because of "
                "a daylight-saving change. Choose another time."
            ],
        )

    def test_it_rejects_nonexistent_end(self) -> None:
        form = self.form(
            start_date="2027-03-28",
            start_time="01:00",
            end_date="2027-03-28",
            end_time="03:15",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("2027-03-28 03:15 does not exist", form.errors["end_date"][0])

    def test_it_uses_first_occurrence_of_ambiguous_time(self) -> None:
        form = self.form(
            start_date="2026-10-25",
            start_time="03:30",
            end_date="2026-10-25",
            end_time="05:00",
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["start"], datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        )

    def test_it_rejects_bad_scope(self) -> None:
        for scope in ("", "foo"):
            form = self.form(scope=scope)
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors["scope"], ["Choose a scope."])

    def test_it_requires_tags_for_scope_tags(self) -> None:
        form = self.form(scope="tags", tags="   ")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["tags"], ["Enter at least one tag."])

    def test_it_rejects_long_tags(self) -> None:
        form = self.form(scope="tags", tags="a" * 501)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["tags"], ["Tags can be at most 500 characters."])

    def test_apply_times_moves_past_start_to_now(self) -> None:
        form = self.form(start_date="2026-10-01", start_time="10:00")
        self.assertTrue(form.is_valid())
        start, end = form.apply_times(NOW) or (None, None)
        self.assertEqual(start, NOW.replace(microsecond=0))
        self.assertEqual(end, datetime(2026, 11, 7, 21, 30, tzinfo=UTC))

    def test_apply_times_reports_end_errors(self) -> None:
        cases = [
            ({"end_time": "21:00"}, "end_before_start"),
            # A past end with a moving start is reported as end before start
            (
                {"start_date": "2026-10-01", "end_date": "2026-10-02"},
                "end_before_start",
            ),
            ({"end_date": "2026-12-08"}, "too_long"),
        ]
        for kwargs, code in cases:
            form = self.form(**kwargs)
            self.assertTrue(form.is_valid())
            self.assertIsNone(form.apply_times(NOW))
            self.assertEqual(form.errors["end_date"], [MAINTENANCE_FORM_ERRORS[code]])

    def test_apply_times_reports_end_in_past_for_original_start(self) -> None:
        form = self.form(end_date="2026-10-02")
        self.assertTrue(form.is_valid())
        original = datetime(2026, 10, 1, tzinfo=UTC)
        self.assertIsNone(form.apply_times(NOW, original_start=original))
        self.assertEqual(
            form.errors["end_date"], [MAINTENANCE_FORM_ERRORS["end_in_past"]]
        )

    def test_apply_times_keeps_original_start(self) -> None:
        form = self.form(start_date="2026-10-01", start_time="10:00")
        self.assertTrue(form.is_valid())
        original = datetime(2026, 10, 30, tzinfo=UTC)
        start, _ = form.apply_times(NOW, original_start=original) or (None, None)
        self.assertEqual(start, original)


class StartNowFormTestCase(SimpleTestCase):
    def test_it_accepts_valid_input(self) -> None:
        form = StartNowForm(
            {"name": "Deploy", "scope": "tags", "tags": "db", "duration_minutes": "60"}
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["duration_minutes"], 60)
        self.assertEqual(form.cleaned_data["tags"], "db")

    def test_it_rejects_bad_duration(self) -> None:
        for value in ("0", "43201", "", "abc", "1.5"):
            form = StartNowForm(
                {"name": "Deploy", "scope": "all", "duration_minutes": value}
            )
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors["duration_minutes"],
                ["Enter a length of 1 to 43200 minutes."],
            )
