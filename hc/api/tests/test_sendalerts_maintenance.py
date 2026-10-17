from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from datetime import timedelta as td
from io import StringIO
from typing import Any
from unittest.mock import Mock, call, patch

import time_machine
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.utils.timezone import now

from hc.api.management.commands.sendalerts import Command, notify
from hc.api.models import Channel, Check, Flip, MaintenanceWindow, Notification
from hc.test import BaseTestCase


class SyncExecutor:
    """Runs submitted work in the calling thread, inside the test transaction."""

    def __init__(self, run: bool = True) -> None:
        self.run = run
        self.submitted: list[Callable[..., Any]] = []

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        self.submitted.append(fn)
        future: Future[Any] = Future()
        if self.run:
            future.set_result(fn(*args))
        else:
            future.set_result(None)
        return future


@patch("hc.api.management.commands.sendalerts.statsd")
class SendAlertsMaintenanceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check(project=self.project, status="down", tags="foo")
        self.check.last_ping = now() - td(hours=3)
        self.check.save()

        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.email_verified = True
        self.channel.save()
        self.channel.checks.add(self.check)

        self.t0 = now() - td(hours=2)

    def add_window(self, start: datetime, end: datetime, tags: str = "") -> Any:
        return MaintenanceWindow.objects.create(
            project=self.project,
            name="Planned work",
            start=start,
            end=end,
            tags=tags,
            created_via="api",
        )

    def add_flip(
        self, created: datetime, new_status: str = "down", check: Check | None = None
    ) -> Flip:
        flip = Flip(owner=check or self.check, created=created)
        flip.old_status = "up" if new_status == "down" else "down"
        flip.new_status = new_status
        flip.save()
        return flip

    def process(self, run: bool = True) -> tuple[Command, StringIO]:
        cmd = Command()
        cmd.stdout = StringIO()  # type: ignore[assignment]
        cmd.executor = SyncExecutor(run=run)  # type: ignore[assignment]
        self.assertTrue(cmd.process_one_flip())
        return cmd, cmd.stdout  # type: ignore[return-value]

    def test_it_withholds_covered_down_flip(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=4))
        flip = self.add_flip(self.t0 + td(minutes=10))
        aa, last_ping = self.check.alert_after, self.check.last_ping

        _, stdout = self.process()

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        flip.refresh_from_db()
        self.assertIsNotNone(flip.processed)
        self.assertEqual(flip.withheld, flip.processed)
        self.assertEqual(flip.withheld_window, w.code)
        self.assertIsNone(flip.withheld_outcome)
        expected = f"{self.check.code} goes down (alert withheld: maintenance window"
        expected += f" {w.code})"
        self.assertIn(expected, stdout.getvalue())
        self.assertNotIn("Planned work", stdout.getvalue())
        statsd.incr.assert_has_calls(
            [call("hc.sendalerts.processFlip"), call("hc.sendalerts.withheld")]
        )

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "down")
        self.assertEqual(self.check.alert_after, aa)
        self.assertEqual(self.check.last_ping, last_ping)

    def test_it_sets_next_nag_dates_for_withheld_flip(self, statsd: Mock) -> None:
        self.profile.nag_period = td(hours=1)
        self.profile.save()
        # Covered checks do not count as down for nags (REQ-4.1), so give the
        # recompute an uncovered down sibling to find
        Check.objects.create(project=self.project, status="down", tags="bar")
        self.add_window(self.t0, self.t0 + td(hours=4), tags="foo")
        self.add_flip(self.t0 + td(minutes=10))

        _, stdout = self.process()

        self.assertIn("alert withheld", stdout.getvalue())

        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.next_nag_date)

    def test_it_delivers_flip_of_uncovered_sibling(self, statsd: Mock) -> None:
        sibling = Check.objects.create(project=self.project, status="down", tags="bar")
        self.channel.checks.add(sibling)
        self.add_window(self.t0, self.t0 + td(hours=4), tags="foo")
        flip = self.add_flip(self.t0 + td(minutes=10), check=sibling)

        self.process()

        self.assertEqual(Notification.objects.filter(channel=self.channel).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        flip.refresh_from_db()
        self.assertIsNone(flip.withheld)
        self.assertIsNone(flip.withheld_window)
        self.assertNotIn(call("hc.sendalerts.withheld"), statsd.incr.mock_calls)

    def test_it_withholds_flip_created_at_window_start(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_flip(self.t0)

        self.process()

        flip.refresh_from_db()
        self.assertIsNotNone(flip.withheld)
        self.assertEqual(Notification.objects.count(), 0)

    def test_it_delivers_flip_created_at_window_end(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_flip(self.t0 + td(hours=1))

        self.process()

        flip.refresh_from_db()
        self.assertIsNone(flip.withheld)
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_references_window_with_latest_end(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(hours=1))
        w2 = self.add_window(self.t0 + td(minutes=30), self.t0 + td(hours=2))
        flip = self.add_flip(self.t0 + td(minutes=59))

        self.process()

        flip.refresh_from_db()
        self.assertEqual(flip.withheld_window, w2.code)

    def test_it_withholds_up_flip_after_withheld_down(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(minutes=30))
        down = self.add_flip(self.t0 + td(minutes=10))
        self.process()

        # The up flip is created after the window has ended
        up = self.add_flip(self.t0 + td(hours=1), new_status="up")
        _, stdout = self.process()

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        up.refresh_from_db()
        self.assertIsNotNone(up.processed)
        self.assertEqual(up.withheld, up.processed)
        self.assertEqual(up.withheld_window, w.code)
        self.assertEqual(up.withheld_outcome, "superseded")
        down.refresh_from_db()
        self.assertEqual(down.withheld_outcome, "superseded")
        expected = f"{self.check.code} goes up (alert withheld: maintenance window"
        expected += f" {w.code})"
        self.assertIn(expected, stdout.getvalue())

    def test_it_delivers_up_flip_after_delivered_down(self, statsd: Mock) -> None:
        down = self.add_flip(self.t0 - td(minutes=10))
        self.process()
        down.refresh_from_db()
        self.assertIsNone(down.withheld)
        self.assertEqual(Notification.objects.count(), 1)

        self.add_window(self.t0, self.t0 + td(hours=1))
        up = self.add_flip(self.t0 + td(minutes=10), new_status="up")
        self.process()

        up.refresh_from_db()
        self.assertIsNone(up.withheld)
        self.assertEqual(Notification.objects.count(), 2)

    def test_it_delivers_up_flip_after_released_down(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(minutes=30))
        down = self.add_flip(self.t0 + td(minutes=10))
        self.process()

        up = self.add_flip(self.t0 + td(hours=1), new_status="up")
        # Simulate a concurrent release of the down flip
        Flip.objects.filter(id=down.id).update(withheld_outcome="released")
        self.process()

        up.refresh_from_db()
        self.assertIsNone(up.withheld)
        self.assertIsNone(up.withheld_outcome)
        self.assertEqual(Notification.objects.count(), 1)
        down.refresh_from_db()
        self.assertEqual(down.withheld_outcome, "released")

    def test_supersede_returns_false_when_down_flip_is_released(
        self, statsd: Mock
    ) -> None:
        down = self.add_flip(self.t0)
        stale = Flip.objects.get(id=down.id)
        # Another process releases the flip after we have read it
        Flip.objects.filter(id=down.id).update(
            withheld=now(), withheld_outcome="released"
        )

        self.assertFalse(Command().supersede(stale))

    def test_supersede_returns_true_when_already_superseded(self, statsd: Mock) -> None:
        down = self.add_flip(self.t0)
        stale = Flip.objects.get(id=down.id)
        Flip.objects.filter(id=down.id).update(
            withheld=now(), withheld_outcome="superseded"
        )

        self.assertTrue(Command().supersede(stale))

    def test_supersede_returns_false_when_down_flip_is_gone(self, statsd: Mock) -> None:
        down = self.add_flip(self.t0)
        stale = Flip.objects.get(id=down.id)
        Flip.objects.filter(id=down.id).delete()

        self.assertFalse(Command().supersede(stale))

    def test_it_uses_windows_as_stored_at_processing_time(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=4))
        flip = self.add_flip(now() - td(minutes=10))
        # The window is ended 5 minutes after the flip was created
        w.end = flip.created + td(minutes=5)
        w.save()

        self.process()

        flip.refresh_from_db()
        self.assertEqual(flip.withheld_window, w.code)
        self.assertEqual(Notification.objects.count(), 0)

    def test_it_fails_open(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(hours=4))
        flip = self.add_flip(self.t0 + td(minutes=10))

        with patch(
            "hc.api.models.MaintenanceWindowManager.covering",
            side_effect=Exception("boom"),
        ):
            with self.assertLogs("hc", level="ERROR") as logs:
                self.process()

        expected = f"Exception while deciding whether to withhold flip {flip.id}"
        self.assertIn(expected, logs.output[0])
        flip.refresh_from_db()
        self.assertIsNotNone(flip.processed)
        self.assertIsNone(flip.withheld)
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_fails_open_when_supersede_raises(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(minutes=30))
        self.add_flip(self.t0 + td(minutes=10))
        self.process()
        up = self.add_flip(self.t0 + td(hours=1), new_status="up")

        with patch.object(Command, "supersede", side_effect=Exception("boom")):
            with self.assertLogs("hc", level="ERROR"):
                self.process()

        up.refresh_from_db()
        self.assertIsNone(up.withheld)
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_keeps_query_count_with_no_windows(self, statsd: Mock) -> None:
        self.add_flip(self.t0 + td(minutes=10))

        # Same total as before the maintenance feature: the decision query
        # is paid for by selecting the flip's owner in the same query.
        with self.assertNumQueries(14):
            self.process()

    def test_it_adds_one_decision_query(self, statsd: Mock) -> None:
        self.add_window(self.t0, self.t0 + td(hours=4))
        self.add_flip(self.t0 + td(minutes=10))

        # select flip + owner, select windows, claim with mark
        with self.assertNumQueries(3):
            self.process(run=False)

    def test_it_does_not_evaluate_pause_and_resume_flips(self, statsd: Mock) -> None:
        self.add_window(now() - td(hours=1), now() + td(hours=1))
        url = f"/api/v3/checks/{self.check.code}"
        for action in ("pause", "resume"):
            r = self.csrf_client.post(
                f"{url}/{action}",
                "",
                content_type="application/json",
                HTTP_X_API_KEY="X" * 32,
            )
            self.assertEqual(r.status_code, 200)
        self.assertEqual(Flip.objects.filter(processed=None).count(), 0)

        with patch.object(Command, "decide_withhold") as decide:
            cmd = Command()
            cmd.executor = SyncExecutor()  # type: ignore[assignment]
            self.assertFalse(cmd.process_one_flip())

        decide.assert_not_called()

    def test_it_sends_test_notification_for_covered_project(self, statsd: Mock) -> None:
        self.add_window(now() - td(hours=1), now() + td(hours=1))
        self.client.login(username="alice@example.org", password="password")

        r = self.client.post(f"/integrations/{self.channel.code}/test/", follow=True)

        self.assertContains(r, "Test notification sent!")
        n = Notification.objects.get()
        self.assertIsNone(n.owner)
        self.assertEqual(len(mail.outbox), 1)

    def test_it_does_not_change_status_flips_or_downtimes(self, statsd: Mock) -> None:
        # The ongoing downtime's duration is measured up to the current time
        self.enterContext(time_machine.travel(now(), tick=False))
        self.add_window(self.t0, self.t0 + td(hours=4))
        self.add_flip(self.t0 + td(minutes=10))
        downtimes_before = self.check.downtimes(1, "UTC")
        url = f"/api/v3/checks/{self.check.code}/flips/"
        flips_before = self.client.get(url, HTTP_X_API_KEY="X" * 32).json()

        self.process()

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "down")
        flips_after = self.client.get(url, HTTP_X_API_KEY="X" * 32).json()
        self.assertEqual(flips_after, flips_before)
        self.assertEqual(self.check.downtimes(1, "UTC"), downtimes_before)


@patch("hc.api.management.commands.sendalerts.statsd")
class EndOfWindowTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check(project=self.project, status="down", tags="foo")
        self.check.last_ping = now() - td(hours=3)
        self.check.save()

        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.email_verified = True
        self.channel.save()
        self.channel.checks.add(self.check)

        self.t0 = now() - td(hours=2)

    def add_window(self, start: datetime, end: datetime, tags: str = "") -> Any:
        return MaintenanceWindow.objects.create(
            project=self.project,
            name="Planned work",
            start=start,
            end=end,
            tags=tags,
            created_via="api",
        )

    def add_withheld_flip(self, created: datetime, window: Any) -> Flip:
        flip = Flip(owner=self.check, created=created)
        flip.old_status, flip.new_status = "up", "down"
        flip.processed = flip.withheld = created
        flip.withheld_window = window.code
        flip.save()
        return flip

    def add_webhook(self) -> Channel:
        definition = {
            "method_down": "POST",
            "url_down": "http://example.org/$CODE",
            "body_down": "$NAME is $STATUS",
            "headers_down": {},
            "method_up": "",
            "url_up": "",
            "body_up": "",
            "headers_up": {},
        }
        channel = Channel(project=self.project, kind="webhook")
        channel.value = json.dumps(definition)
        channel.save()
        channel.checks.add(self.check)
        return channel

    def new_command(self) -> Command:
        cmd = Command()
        cmd.stdout = StringIO()  # type: ignore[assignment]
        cmd.executor = SyncExecutor()  # type: ignore[assignment]
        return cmd

    def run_pass(self) -> tuple[int, str]:
        cmd = self.new_command()
        num_released = cmd.handle_end_of_window()
        return num_released, cmd.stdout.getvalue()

    def outcome(self, flip: Flip) -> str | None:
        flip.refresh_from_db()
        return flip.withheld_outcome

    @patch("hc.api.transports.curl.request", autospec=True)
    def test_it_releases_after_end(self, request: Mock, statsd: Mock) -> None:
        request.return_value.status_code = 200
        webhook = self.add_webhook()
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)

        num_released, stdout = self.run_pass()

        self.assertEqual(num_released, 1)
        self.assertEqual(self.outcome(flip), "released")
        for channel in (self.channel, webhook):
            n = Notification.objects.get(channel=channel)
            self.assertEqual(n.check_status, "down")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(request.call_count, 1)

        lines = stdout.splitlines()
        self.assertEqual(lines[0], f"{self.check.code} goes down (end of maintenance)")
        self.assertEqual(len(lines), 3)
        self.assertIn("OK in", lines[1])
        self.assertIn("OK in", lines[2])
        calls = statsd.incr.mock_calls
        self.assertEqual(calls.count(call("hc.sendalerts.endOfWindow")), 1)

    @patch("hc.api.transports.curl.request", autospec=True)
    def test_released_alert_matches_normal_alert(
        self, request: Mock, statsd: Mock
    ) -> None:
        self.enterContext(time_machine.travel(now(), tick=False))
        request.return_value.status_code = 200
        self.add_webhook()
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)

        self.run_pass()
        # Send the same flip again, the way process_one_flip delivers flips
        notify(Flip.objects.select_related("owner").get(id=flip.id))

        released, normal = mail.outbox
        q = Notification.objects.filter(channel=self.channel).order_by("id")
        codes = q.values_list("code", flat=True)
        released_code, normal_code = (str(code) for code in codes)
        self.assertEqual(released.subject, normal.subject)
        self.assertEqual(released.body.replace(released_code, normal_code), normal.body)
        assert isinstance(released, EmailMultiAlternatives)
        assert isinstance(normal, EmailMultiAlternatives)
        released_html, _ = released.alternatives[0]
        normal_html, _ = normal.alternatives[0]
        assert isinstance(released_html, str)
        self.assertEqual(released_html.replace(released_code, normal_code), normal_html)
        self.assertNotIn("maintenance", released.body.lower())
        self.assertNotIn("maintenance", released_html.lower())

        released_call, normal_call = request.call_args_list
        self.assertEqual(released_call, normal_call)

    def test_it_sends_nothing_when_check_recovered_in_window(
        self, statsd: Mock
    ) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        down = self.add_withheld_flip(self.t0 + td(minutes=10), w)
        Flip.objects.filter(id=down.id).update(withheld_outcome="superseded")
        up = Flip(owner=self.check, created=self.t0 + td(minutes=20))
        up.old_status, up.new_status = "down", "up"
        up.processed = up.withheld = up.created
        up.withheld_window = w.code
        up.withheld_outcome = "superseded"
        up.save()
        self.check.status = "up"
        self.check.save()

        num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_it_waits_for_overlapping_window(self, statsd: Mock) -> None:
        day = now().replace(hour=0, minute=0, second=0, microsecond=0) - td(days=1)
        self.add_window(day + td(hours=10), day + td(hours=11))
        w2 = self.add_window(day + td(hours=10, minutes=30), day + td(hours=12))
        flip = self.add_withheld_flip(day + td(hours=10, minutes=10), w2)

        with time_machine.travel(day + td(hours=11, seconds=30), tick=False):
            self.run_pass()
        self.assertIsNone(self.outcome(flip))
        self.assertEqual(Notification.objects.count(), 0)

        with time_machine.travel(day + td(hours=12, seconds=30), tick=False):
            self.run_pass()
        self.assertEqual(self.outcome(flip), "released")
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_releases_after_end_now(self, statsd: Mock) -> None:
        self.enterContext(time_machine.travel(now(), tick=False))
        w = self.add_window(now() - td(hours=1), now() + td(hours=1))
        flip = self.add_withheld_flip(now() - td(minutes=10), w)

        self.run_pass()
        self.assertIsNone(self.outcome(flip))

        # The user clicks "End now"
        w.end = now()
        w.save()
        self.run_pass()
        self.assertEqual(self.outcome(flip), "released")
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_releases_after_tag_removal(self, statsd: Mock) -> None:
        w = self.add_window(now() - td(hours=1), now() + td(hours=1), tags="foo")
        flip = self.add_withheld_flip(now() - td(minutes=10), w)

        self.run_pass()
        self.assertIsNone(self.outcome(flip))

        self.check.tags = "bar"
        self.check.save()
        self.run_pass()
        self.assertEqual(self.outcome(flip), "released")
        self.assertEqual(Notification.objects.count(), 1)

    def test_it_releases_after_project_transfer(self, statsd: Mock) -> None:
        w = self.add_window(now() - td(hours=1), now() + td(hours=1))
        flip = self.add_withheld_flip(now() - td(minutes=10), w)

        self.check.project = self.bobs_project
        self.check.save()
        self.run_pass()

        self.assertEqual(self.outcome(flip), "released")

    def test_it_waits_for_extended_end(self, statsd: Mock) -> None:
        start = now()
        w = self.add_window(start - td(hours=1), start + td(hours=1))
        flip = self.add_withheld_flip(start - td(minutes=10), w)
        w.end = start + td(hours=2)
        w.save()

        with time_machine.travel(start + td(hours=1, seconds=30), tick=False):
            self.run_pass()
        self.assertIsNone(self.outcome(flip))

        with time_machine.travel(start + td(hours=2, seconds=30), tick=False):
            self.run_pass()
        self.assertEqual(self.outcome(flip), "released")

    def test_it_releases_after_restart(self, statsd: Mock) -> None:
        # sendalerts was stopped for 2 hours, the window ended meanwhile
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)

        cmd = self.new_command()
        self.assertIsNone(cmd.next_end_of_window_pass)
        cmd.maybe_handle_end_of_window()
        cmd.maybe_handle_end_of_window()

        self.assertEqual(self.outcome(flip), "released")
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_it_skips_flip_released_by_other_process(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)
        set_coverage = MaintenanceWindow.objects.set_coverage

        # Another process claims the release after this one has loaded the flip
        def claim_first(checks: Any, at: datetime) -> None:
            Flip.objects.filter(id=flip.id).update(withheld_outcome="released")
            set_coverage(checks, at)

        with patch(
            "hc.api.models.MaintenanceWindowManager.set_coverage",
            side_effect=claim_first,
        ):
            num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn(call("hc.sendalerts.endOfWindow"), statsd.incr.mock_calls)

    def test_it_skips_flip_already_released(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)
        Flip.objects.filter(id=flip.id).update(withheld_outcome="released")

        num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_it_supersedes_when_check_paused(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)
        self.check.status = "paused"
        self.check.save()

        num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)
        self.assertEqual(self.outcome(flip), "superseded")
        self.assertEqual(Notification.objects.count(), 0)

    def test_it_supersedes_when_later_flip_exists(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)
        # A later flip that sendalerts has not processed yet
        up = Flip(owner=self.check, created=now() - td(minutes=1))
        up.old_status, up.new_status = "down", "up"
        up.save()

        self.run_pass()

        self.assertEqual(self.outcome(flip), "superseded")
        self.assertEqual(Notification.objects.count(), 0)

    def test_it_sends_nothing_for_deleted_check(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        self.add_withheld_flip(self.t0 + td(minutes=10), w)
        self.check.delete()

        num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_it_delivers_up_flip_after_release(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        self.add_withheld_flip(self.t0 + td(minutes=10), w)
        self.run_pass()

        self.check.status = "up"
        self.check.save()
        up = Flip(owner=self.check, created=now())
        up.old_status, up.new_status = "down", "up"
        up.save()
        cmd = self.new_command()
        self.assertTrue(cmd.process_one_flip())

        up.refresh_from_db()
        self.assertIsNone(up.withheld)
        statuses = Notification.objects.order_by("id").values_list(
            "check_status", flat=True
        )
        self.assertEqual(list(statuses), ["down", "up"])

    def test_idle_pass_uses_one_query(self, statsd: Mock) -> None:
        with self.assertNumQueries(1):
            num_released, _ = self.run_pass()

        self.assertEqual(num_released, 0)

    def test_pass_interval(self, statsd: Mock) -> None:
        start = now()
        cmd = self.new_command()
        with patch.object(Command, "handle_end_of_window", return_value=0) as pass_:
            for offset in (0, 1, 14, 15, 29, 30):
                with time_machine.travel(start + td(seconds=offset), tick=False):
                    cmd.maybe_handle_end_of_window()

        self.assertEqual(pass_.call_count, 3)

    def test_it_sets_nag_dates_after_window_end(self, statsd: Mock) -> None:
        self.enterContext(time_machine.travel(now(), tick=False))
        self.profile.nag_period = td(hours=1)
        self.profile.save()
        w = self.add_window(self.t0, self.t0 + td(hours=1))

        self.run_pass()
        w.refresh_from_db()
        self.assertEqual(w.end_handled, now())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.next_nag_date, now() + td(hours=1))

        # The second pass does not recompute nag dates again
        self.profile.next_nag_date = None
        self.profile.save()
        with time_machine.travel(now() + td(minutes=1), tick=False):
            self.run_pass()
        w.refresh_from_db()
        self.assertEqual(w.end_handled, now())
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.next_nag_date)

    def test_it_logs_exception_in_pass(self, statsd: Mock) -> None:
        w = self.add_window(self.t0, self.t0 + td(hours=1))
        flip = self.add_withheld_flip(self.t0 + td(minutes=10), w)

        cmd = self.new_command()
        with patch(
            "hc.api.models.MaintenanceWindowManager.set_coverage",
            side_effect=Exception("boom"),
        ):
            with self.assertLogs("hc", level="ERROR") as logs:
                cmd.maybe_handle_end_of_window()

        self.assertIn("Exception in end-of-window pass", logs.output[0])
        self.assertIsNone(self.outcome(flip))
        self.assertEqual(Notification.objects.count(), 0)
