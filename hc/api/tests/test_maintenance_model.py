from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td

import time_machine
from django.contrib.auth.models import User

from hc.accounts.models import Project
from hc.api.models import (
    MAINTENANCE_LIMIT,
    MAINTENANCE_MAX_LENGTH,
    MAINTENANCE_RETENTION,
    Check,
    Flip,
    MaintenanceWindow,
)
from hc.test import BaseTestCase

CURRENT_TIME = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
US = td(microseconds=1)


class MaintenanceWindowModelTestCase(BaseTestCase):
    def _window(
        self,
        start: datetime,
        end: datetime,
        tags: str = "",
        project: Project | None = None,
    ) -> MaintenanceWindow:
        return MaintenanceWindow.objects.create(
            project=project or self.project,
            name="Upgrade",
            start=start,
            end=end,
            tags=tags,
            created_via="dashboard",
        )

    def test_it_computes_state(self) -> None:
        start = CURRENT_TIME
        end = CURRENT_TIME + td(hours=1)
        w = MaintenanceWindow(start=start, end=end)
        self.assertEqual(w.state(start - US), "upcoming")
        self.assertEqual(w.state(start), "active")
        self.assertEqual(w.state(end - US), "active")
        self.assertEqual(w.state(end), "ended")

    @time_machine.travel(CURRENT_TIME)
    def test_it_defaults_state_to_now(self) -> None:
        w = MaintenanceWindow(start=CURRENT_TIME, end=CURRENT_TIME + td(hours=1))
        self.assertEqual(w.state(), "active")

    def test_it_computes_scope_and_tags_set(self) -> None:
        w = MaintenanceWindow(tags="")
        self.assertEqual(w.scope, "all")
        self.assertEqual(w.tags_set(), set())

        w.tags = "db prod"
        self.assertEqual(w.scope, "tags")
        self.assertEqual(w.tags_set(), {"db", "prod"})

    def test_it_matches_tags_exactly(self) -> None:
        start = CURRENT_TIME
        w = self._window(start, start + td(hours=1), tags="db prod")
        at = start + td(minutes=1)

        superset = Check.objects.create(project=self.project, tags="prod db web")
        subset = Check.objects.create(project=self.project, tags="db")
        other_case = Check.objects.create(project=self.project, tags="DB prod")
        other_project = Check.objects.create(project=self.bobs_project, tags="prod db")

        with self.assertNumQueries(0):
            self.assertTrue(w.covers(superset, at))
            self.assertFalse(w.covers(subset, at))
            self.assertFalse(w.covers(other_case, at))
            self.assertFalse(w.covers(other_project, at))

    def test_it_covers_all_checks_with_scope_all(self) -> None:
        w = self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))
        c = Check.objects.create(project=self.project, tags="")
        self.assertFalse(w.covers(c, CURRENT_TIME - US))
        self.assertTrue(w.covers(c, CURRENT_TIME))
        self.assertFalse(w.covers(c, CURRENT_TIME + td(hours=1)))

    def test_covering_picks_latest_end(self) -> None:
        ten = CURRENT_TIME
        self._window(ten, ten + td(hours=1))
        w2 = self._window(ten + td(minutes=30), ten + td(hours=2))
        c = Check.objects.create(project=self.project)

        with self.assertNumQueries(1):
            result = MaintenanceWindow.objects.covering(c, ten + td(minutes=59))
        self.assertEqual(result, w2)

    def test_covering_breaks_ties_by_highest_id(self) -> None:
        end = CURRENT_TIME + td(hours=1)
        self._window(CURRENT_TIME, end)
        w2 = self._window(CURRENT_TIME + td(minutes=5), end)
        c = Check.objects.create(project=self.project)

        result = MaintenanceWindow.objects.covering(c, CURRENT_TIME + td(minutes=10))
        self.assertEqual(result, w2)

    def test_covering_skips_non_matching_tags(self) -> None:
        self._window(CURRENT_TIME, CURRENT_TIME + td(hours=2), tags="db")
        w = self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))
        c = Check.objects.create(project=self.project, tags="web")

        result = MaintenanceWindow.objects.covering(c, CURRENT_TIME)
        self.assertEqual(result, w)

    def test_covering_returns_none(self) -> None:
        end = CURRENT_TIME + td(hours=1)
        self._window(CURRENT_TIME, end, project=self.bobs_project)
        c = Check.objects.create(project=self.project)
        self.assertIsNone(MaintenanceWindow.objects.covering(c, CURRENT_TIME))

    def test_flag_checks_annotates_possible_coverage(self) -> None:
        self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1), tags="db")
        c1 = Check.objects.create(project=self.project)
        c2 = Check.objects.create(project=self.bobs_project)

        q = Check.objects.filter(id__in=[c1.id, c2.id]).order_by("id")
        with self.assertNumQueries(1):
            checks = list(MaintenanceWindow.objects.flag_checks(q, CURRENT_TIME))

        self.assertTrue(getattr(checks[0], "maintenance_possible"))
        self.assertFalse(getattr(checks[1], "maintenance_possible"))

    def test_set_coverage_skips_query_when_nothing_flagged(self) -> None:
        end = CURRENT_TIME + td(hours=1)
        self._window(CURRENT_TIME, end, project=self.bobs_project)
        Check.objects.create(project=self.project)
        Check.objects.create(project=self.project)

        q = MaintenanceWindow.objects.flag_checks(Check.objects.all(), CURRENT_TIME)
        checks = list(q)
        with self.assertNumQueries(0):
            MaintenanceWindow.objects.set_coverage(checks, CURRENT_TIME)

        for check in checks:
            self.assertIsNone(check.maintenance_window)

    def test_set_coverage_uses_one_query(self) -> None:
        w1 = self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))
        w2 = self._window(CURRENT_TIME, CURRENT_TIME + td(hours=2), tags="db")
        end = CURRENT_TIME + td(hours=3)
        self._window(CURRENT_TIME, end, project=self.bobs_project)
        c1 = Check.objects.create(project=self.project, tags="web")
        c2 = Check.objects.create(project=self.project, tags="db")
        c3 = Check.objects.create(project=self.charlies_project)

        q = Check.objects.filter(id__in=[c1.id, c2.id, c3.id]).order_by("id")
        checks = list(MaintenanceWindow.objects.flag_checks(q, CURRENT_TIME))
        with self.assertNumQueries(1):
            MaintenanceWindow.objects.set_coverage(checks, CURRENT_TIME)

        self.assertEqual(checks[0].maintenance_window, w1)
        self.assertEqual(checks[1].maintenance_window, w2)
        self.assertIsNone(checks[2].maintenance_window)

    def test_normalize_tags_dedupes(self) -> None:
        self.assertEqual(MaintenanceWindow.normalize_tags("b a  b c a"), "b a c")
        self.assertEqual(MaintenanceWindow.normalize_tags("   "), "")

    def test_clean_times_moves_start(self) -> None:
        at = CURRENT_TIME + td(microseconds=500)
        start, end = MaintenanceWindow.clean_times(
            CURRENT_TIME - td(hours=1),
            CURRENT_TIME + td(hours=1, microseconds=7),
            at=at,
        )
        self.assertEqual(start, CURRENT_TIME)
        self.assertEqual(start.microsecond, 0)
        self.assertEqual(end, CURRENT_TIME + td(hours=1))

    def test_clean_times_keeps_start_without_move_start(self) -> None:
        past = CURRENT_TIME - td(hours=1)
        start, _ = MaintenanceWindow.clean_times(
            past, CURRENT_TIME + td(hours=1), at=CURRENT_TIME, move_start=False
        )
        self.assertEqual(start, past)

    def _assert_invalid(self, code: str, start: datetime, end: datetime) -> None:
        with self.assertRaises(MaintenanceWindow.Invalid) as cm:
            MaintenanceWindow.clean_times(start, end, at=CURRENT_TIME)
        self.assertEqual(cm.exception.code, code)

    def test_clean_times_rejects_end_before_start(self) -> None:
        start = CURRENT_TIME + td(hours=1)
        self._assert_invalid("end_before_start", start, start)
        self._assert_invalid("end_before_start", start, start - td(seconds=1))

    def test_clean_times_rejects_end_in_past(self) -> None:
        start = CURRENT_TIME - td(hours=2)
        # move_start=False keeps the past start, so V5 passes and V6 fires
        with self.assertRaises(MaintenanceWindow.Invalid) as cm:
            MaintenanceWindow.clean_times(
                start, CURRENT_TIME, at=CURRENT_TIME, move_start=False
            )
        self.assertEqual(cm.exception.code, "end_in_past")

    def test_clean_times_checks_end_before_start_first(self) -> None:
        # end is both before start and in the past
        end = CURRENT_TIME - td(hours=1)
        self._assert_invalid("end_before_start", CURRENT_TIME, end)

    def test_clean_times_checks_end_in_past_before_length(self) -> None:
        with self.assertRaises(MaintenanceWindow.Invalid) as cm:
            MaintenanceWindow.clean_times(
                CURRENT_TIME - td(days=40),
                CURRENT_TIME - td(seconds=1),
                at=CURRENT_TIME,
                move_start=False,
            )
        self.assertEqual(cm.exception.code, "end_in_past")

    def test_clean_times_enforces_max_length(self) -> None:
        start = CURRENT_TIME + td(hours=1)
        _, end = MaintenanceWindow.clean_times(
            start, start + MAINTENANCE_MAX_LENGTH, at=CURRENT_TIME
        )
        self.assertEqual(end, start + td(days=30))

        self._assert_invalid("too_long", start, start + td(days=30, seconds=1))

    def test_assert_can_add_allows_below_limit(self) -> None:
        for i in range(MAINTENANCE_LIMIT - 1):
            self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))
        for i in range(5):
            self._window(CURRENT_TIME - td(hours=2), CURRENT_TIME - td(hours=1))

        with self.assertNumQueries(1):
            MaintenanceWindow.objects.assert_can_add(self.project, CURRENT_TIME)

    def test_assert_can_add_rejects_at_limit(self) -> None:
        for i in range(MAINTENANCE_LIMIT):
            self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))

        with self.assertRaises(MaintenanceWindow.Invalid) as cm:
            MaintenanceWindow.objects.assert_can_add(self.project, CURRENT_TIME)
        self.assertEqual(cm.exception.code, "limit")

    def test_prune_deletes_old_windows(self) -> None:
        threshold = CURRENT_TIME - MAINTENANCE_RETENTION
        self.assertEqual(MAINTENANCE_RETENTION, td(days=90))
        newer = self._window(threshold - td(hours=1), threshold + td(seconds=1))
        older = self._window(threshold - td(hours=1), threshold - td(seconds=1))
        other = self._window(
            threshold - td(hours=1),
            threshold - td(seconds=1),
            project=self.bobs_project,
        )

        with self.assertNumQueries(1):
            MaintenanceWindow.objects.prune(self.project, CURRENT_TIME)

        self.assertTrue(MaintenanceWindow.objects.filter(id=newer.id).exists())
        self.assertFalse(MaintenanceWindow.objects.filter(id=older.id).exists())
        self.assertTrue(MaintenanceWindow.objects.filter(id=other.id).exists())

    def test_it_nulls_created_by_when_user_deleted(self) -> None:
        user = User.objects.create(username="dave", email="dave@example.org")
        w = self._window(CURRENT_TIME, CURRENT_TIME + td(hours=1))
        w.created_by = user
        w.save()

        user.delete()

        w.refresh_from_db()
        self.assertIsNone(w.created_by)

    @time_machine.travel(CURRENT_TIME)
    def test_to_dict_works(self) -> None:
        w = MaintenanceWindow.objects.create(
            project=self.project,
            name="Upgrade",
            start=datetime(2026, 11, 7, 20, 0, 0, 123, tzinfo=timezone.utc),
            end=datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc),
            tags="db prod",
            created_via="api",
            created_by=self.alice,
        )

        with self.assertNumQueries(0):
            doc = w.to_dict()

        self.assertEqual(
            set(doc.keys()),
            {
                "uuid",
                "name",
                "start",
                "end",
                "scope",
                "tags",
                "state",
                "created",
                "created_via",
            },
        )
        self.assertEqual(doc["uuid"], str(w.code))
        self.assertEqual(doc["name"], "Upgrade")
        self.assertEqual(doc["start"], "2026-11-07T20:00:00+00:00")
        self.assertEqual(doc["end"], "2026-11-07T22:00:00+00:00")
        self.assertEqual(doc["created"], "2026-11-07T10:00:00+00:00")
        self.assertEqual(doc["scope"], "tags")
        self.assertEqual(doc["tags"], "db prod")
        self.assertEqual(doc["state"], "upcoming")
        self.assertEqual(doc["created_via"], "api")

    def test_str_returns_name(self) -> None:
        self.assertEqual(str(MaintenanceWindow(name="Upgrade")), "Upgrade")

    def test_it_has_no_reverse_fk_to_flip(self) -> None:
        # ADR-006: withheld_window is a plain UUID so Check.prune
        # deletes flips with a single DELETE.
        self.assertEqual(len(Flip._meta.related_objects), 0)
