from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta as td
from uuid import UUID, uuid4

from hc.api.models import Check, Flip, MaintenanceWindow, Ping
from hc.front.views import _get_events
from hc.test import BaseTestCase

EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


class GetEventsTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check.objects.create(project=self.project, created=EPOCH)
        self.start = self.check.created
        self.end = EPOCH + td(days=10)

    def test_it_calculates_duration(self) -> None:
        Ping.objects.create(owner=self.check, n=1, created=EPOCH, kind="start")
        Ping.objects.create(owner=self.check, n=2, created=EPOCH + td(minutes=5))

        with self.assertNumQueries(2):
            pings = _get_events(self.check, 100, start=self.start, end=self.end)
        with self.assertNumQueries(0):
            assert isinstance(pings[0], Ping)
            self.assertEqual(pings[0].duration, td(minutes=5))

    def test_it_delegates_duration_calculation_to_model(self) -> None:
        Ping.objects.create(owner=self.check, n=1, created=EPOCH, kind="start")
        Ping.objects.create(owner=self.check, n=2, created=EPOCH + td(minutes=5))

        with self.assertNumQueries(2):
            pings = _get_events(self.check, 1, start=self.start, end=self.end)
        with self.assertNumQueries(1):
            assert isinstance(pings[0], Ping)
            self.assertEqual(pings[0].duration, td(minutes=5))

    def test_it_calculates_overlapping_durations(self) -> None:
        m = td(minutes=1)
        a, b = uuid4(), uuid4()
        self.check.ping_set.create(n=1, rid=a, created=EPOCH, kind="start")
        self.check.ping_set.create(n=2, rid=b, created=EPOCH + m, kind="start")
        self.check.ping_set.create(n=3, rid=a, created=EPOCH + m * 2)
        self.check.ping_set.create(n=4, rid=b, created=EPOCH + m * 6)

        with self.assertNumQueries(2):
            pings = _get_events(self.check, 100, start=self.start, end=self.end)

        with self.assertNumQueries(0):
            assert isinstance(pings[0], Ping)
            self.assertEqual(pings[0].duration, td(minutes=5))
            assert isinstance(pings[1], Ping)
            self.assertEqual(pings[1].duration, td(minutes=2))

    def test_it_disables_duration_display(self) -> None:
        # Set up a worst case scenario where each success ping has an unique rid,
        # and there are no "start" pings:
        for i in range(1, 12):
            self.check.ping_set.create(n=i, rid=uuid4(), created=EPOCH + td(minutes=i))

        # Make sure we don't run Ping.duration() per ping:
        with self.assertNumQueries(2):
            pings = _get_events(self.check, 100, start=self.start, end=self.end)

        with self.assertNumQueries(0):
            for ping in pings:
                assert isinstance(ping, Ping)
                self.assertIsNone(ping.duration)

    def add_flip(self, withheld_window: UUID | None = None) -> Flip:
        return Flip.objects.create(
            owner=self.check,
            created=EPOCH + td(minutes=1),
            old_status="up",
            new_status="down",
            withheld=EPOCH + td(minutes=1) if withheld_window else None,
            withheld_window=withheld_window,
        )

    def test_it_adds_no_query_without_withheld_flips(self) -> None:
        self.add_flip()
        with self.assertNumQueries(2):
            events = _get_events(self.check, 100, start=self.start, end=self.end)
        assert isinstance(events[0], Flip)
        self.assertIsNone(events[0].withheld_window_name)

    def test_it_sets_withheld_window_names_in_one_query(self) -> None:
        window = MaintenanceWindow.objects.create(
            project=self.project,
            name="Postgres upgrade",
            start=EPOCH,
            end=EPOCH + td(hours=1),
            created_via="dashboard",
        )
        self.add_flip(window.code)
        self.add_flip(window.code)
        self.add_flip(uuid4())

        with self.assertNumQueries(3):
            events = _get_events(self.check, 100, start=self.start, end=self.end)

        names = [e.withheld_window_name for e in events if isinstance(e, Flip)]
        self.assertEqual(
            sorted(names, key=str), [None, "Postgres upgrade", "Postgres upgrade"]
        )
