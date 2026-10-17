from __future__ import annotations

import logging
import signal
import time
import uuid
from argparse import ArgumentParser
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta as td
from threading import BoundedSemaphore
from types import FrameType
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection
from django.db.models import Max
from django.utils.timezone import now

from hc.api.models import Check, Flip, MaintenanceWindow
from hc.lib.statsd import statsd

logger = logging.getLogger("hc")

END_OF_WINDOW_INTERVAL = td(seconds=15)


@dataclass
class WithholdDecision:
    window_code: uuid.UUID | None
    # Up flips only: the earlier withheld, unreleased down flip
    supersede: Flip | None


def notify(flip: Flip) -> str | None:
    # This is run via ThreadPoolExecutor. The thread may already have an open
    # db connection. If notify has not run recently then the db connection may have
    # timed out. We call close_old_connections() to make sure we have a working db
    # connection. The if condition makes sure this does not run during tests.
    if not connection.in_atomic_block:
        close_old_connections()

    # Set or clear dates for followup nags
    check = flip.owner
    check.project.update_next_nag_dates()
    channels = flip.select_channels()
    if not channels:
        return None

    send_start = now()
    logs = [f"{check.code} goes {flip.new_status}"]
    for ch in channels:
        notify_start = time.time()
        error = ch.notify(flip)
        secs = time.time() - notify_start
        code8 = str(ch.code)[:8]
        if error:
            logs.append(f"  {code8} ({ch.kind}) Error in {secs:.1f}s: {error}")
            statsd.incr(f"hc.notifications.{ch.kind}.fail")
        else:
            logs.append(f"  {code8} ({ch.kind}) OK in {secs:.1f}s")
            statsd.incr(f"hc.notifications.{ch.kind}.success")

    statsd.timing("hc.sendalerts.dwellTime", send_start - flip.created)
    statsd.timing("hc.sendalerts.sendTime", now() - send_start)
    return "\n".join(logs)


def notify_withheld(flip: Flip) -> str:
    # See notify() for why close_old_connections() is called here.
    if not connection.in_atomic_block:
        close_old_connections()

    # Nag dates follow check statuses, which a maintenance window never changes
    check = flip.owner
    check.project.update_next_nag_dates()
    reason = f"alert withheld: maintenance window {flip.withheld_window}"
    return f"{check.code} goes {flip.new_status} ({reason})"


def notify_end_of_window(flip: Flip) -> str:
    # The alert itself is the regular one, only the log line tells them apart
    headline = f"{flip.owner.code} goes down (end of maintenance)"
    logs = notify(flip)
    if logs is None:
        return headline

    channel_lines = logs.split("\n")[1:]
    return "\n".join([headline, *channel_lines])


class Command(BaseCommand):
    help = "Sends UP/DOWN email alerts"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.seats = BoundedSemaphore(10)
        self.shutdown = False
        # None makes the first loop iteration run the pass right away
        self.next_end_of_window_pass: datetime | None = None

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--num-workers",
            type=int,
            default=1,
            help="The number of concurrent worker processes to use",
        )

        parser.add_argument(
            "--pool",
            action="store_true",
            help="Use DB connection pool (PostgreSQL-only)",
        )

    def on_notify_done(self, future: Future[str | None]) -> None:
        self.seats.release()

        try:
            if logs := future.result():
                self.stdout.write(logs)
        except Exception as exc:
            logger.error("Exception in notify", exc_info=exc)
            raise

    def decide_withhold(self, flip: Flip) -> WithholdDecision | None:
        """Decide whether to withhold the flip's notifications.

        Return None if the flip should be delivered as usual.

        """

        if flip.new_status == "down":
            window = MaintenanceWindow.objects.covering(flip.owner, flip.created)
            if window is None:
                return None
            return WithholdDecision(window_code=window.code, supersede=None)

        if flip.new_status == "up" and flip.old_status == "down":
            # The up flip pairs with the down flip immediately before it.
            # If that one was withheld, withhold this one too, regardless
            # of whether a window still covers the check.
            q = Flip.objects.filter(owner_id=flip.owner_id, created__lt=flip.created)
            previous = q.order_by("-created").first()
            if previous is None or previous.new_status != "down":
                return None
            if not previous.is_withheld_unreleased():
                return None
            return WithholdDecision(
                window_code=previous.withheld_window, supersede=previous
            )

        return None

    def supersede(self, down_flip: Flip) -> bool:
        """Mark a withheld down flip as superseded by its up flip.

        Return False if the down flip has been released (or deleted) meanwhile,
        in which case the up flip must be delivered.

        """

        if down_flip.withheld_outcome == "superseded":
            return True

        q = Flip.objects.filter(id=down_flip.id, withheld_outcome=None)
        if q.update(withheld_outcome="superseded") == 1:
            return True

        # Another process set the outcome first, find out which one
        outcome = (
            Flip.objects.filter(id=down_flip.id)
            .values_list("withheld_outcome", flat=True)
            .first()
        )
        return outcome == "superseded"

    def process_one_flip(self) -> bool:
        """Find unprocessed flip, send notifications.

        Return True if the main loop should continue right away.

        Return False if the main loop should  wait a bit before continuing.
        (because either all workers are currently busy or there are currently no
        unprocessed flips in the database).

        """

        if not self.seats.acquire(timeout=1):
            return False  # Workers busy, main thread should wait a bit

        flip = Flip.objects.filter(processed=None).select_related("owner").first()
        if flip is None:
            self.seats.release()
            return False  # No work found, main thread should wait a bit

        try:
            decision = self.decide_withhold(flip)
            # Settle the down flip before claiming the up flip, so a
            # concurrent release cannot leave both alerts unsent.
            if decision and decision.supersede:
                if not self.supersede(decision.supersede):
                    decision = None
        except Exception:
            # Fail open: a missed alert is worse than an unwanted one
            logger.exception(
                "Exception while deciding whether to withhold flip %d", flip.id
            )
            decision = None

        # Mark the flip as processed:
        q = Flip.objects.filter(id=flip.id, processed=None)
        if decision is None:
            num_updated = q.update(processed=now())
        else:
            flip.processed = flip.withheld = now()
            flip.withheld_window = decision.window_code
            flip.withheld_outcome = "superseded" if decision.supersede else None
            num_updated = q.update(
                processed=flip.processed,
                withheld=flip.withheld,
                withheld_window=flip.withheld_window,
                withheld_outcome=flip.withheld_outcome,
            )

        if num_updated != 1:
            self.seats.release()
            # Nothing got updated: another sendalerts process got there first.
            return True

        statsd.incr("hc.sendalerts.processFlip")
        if decision is None:
            f = self.executor.submit(notify, flip)
        else:
            statsd.incr("hc.sendalerts.withheld")
            f = self.executor.submit(notify_withheld, flip)
        f.add_done_callback(self.on_notify_done)
        return True

    def handle_going_down(self) -> bool:
        """Process a single check going down.

        1. Find a check with alert_after in the past, and status other than "down".
        2. Calculate its current status.
        3. If calculation throws an exception, push alert_after forward and re-raise.
        4. If the current status is not "down", update alert_after and return.
        5. Update the check's status in the database to "down".
        6. If exactly 1 row gets updated, create a Flip object.

        """

        q = Check.objects.filter(alert_after__lt=now()).exclude(status="down")
        # Sort by alert_after, to avoid unnecessary sorting by id:
        check = q.order_by("alert_after").first()
        if check is None:
            return False

        old_status = check.status
        q = Check.objects.filter(id=check.id, status=old_status)

        try:
            status = check.get_status()
        except Exception:
            # Make sure we don't trip on this check again for an hour:
            # Otherwise sendalerts may end up in a crash loop.
            q.update(alert_after=now() + td(hours=1))
            # Then re-raise the exception:
            raise

        if status != "down":
            # It is not down yet. Update alert_after
            q.update(alert_after=check.going_down_after())
            return True

        flip_time = check.going_down_after()
        # In theory, going_down_after() can return None, but:
        # get_status() just reported status "down", so "going_down_after()"
        # must be able to calculate precisely when the check's state flipped.
        assert flip_time

        # Atomically update status
        num_updated = q.update(alert_after=None, status="down")
        if num_updated != 1:
            # Nothing got updated: another worker process got there first.
            return True

        flip = Flip(owner=check)
        flip.created = flip_time
        flip.old_status = old_status
        flip.new_status = "down"
        flip.reason = "timeout"
        flip.save()

        return True

    def handle_ended_windows(self, at: datetime) -> None:
        """Recompute nag dates once for each window that has ended."""

        q = MaintenanceWindow.objects.filter(end__lte=at, end_handled=None)
        for window in q.select_related("project"):
            claim = MaintenanceWindow.objects.filter(id=window.id, end_handled=None)
            if claim.update(end_handled=at) == 1:
                window.project.update_next_nag_dates()

    def handle_end_of_window(self) -> int:
        """Release withheld down flips of checks no window covers any more.

        1. Return right away if there are no pending flips or ended windows.
        2. Recompute nag dates for projects whose windows have ended.
        3. For each pending flip, leave it pending if its check is covered,
           mark it superseded if the check is not down any more or has
           flipped again, otherwise claim the release and notify.

        Return the number of released flips.

        """

        at = now()
        pending = Flip.objects.filter(withheld__isnull=False, withheld_outcome=None)
        ended = MaintenanceWindow.objects.filter(end__lte=at, end_handled=None)
        gate = pending.values_list("id").union(ended.values_list("id"))
        if not gate[:1]:
            return 0

        self.handle_ended_windows(at)

        flips = list(pending)
        if not flips:
            return 0

        check_ids = {flip.owner_id for flip in flips}
        q = Check.objects.filter(id__in=check_ids).select_related("project")
        checks = {c.id: c for c in MaintenanceWindow.objects.flag_checks(q, at)}
        MaintenanceWindow.objects.set_coverage(list(checks.values()), at)
        q_flips = Flip.objects.filter(owner_id__in=check_ids)
        rows = q_flips.values("owner_id").annotate(latest=Max("created"))
        latest = {row["owner_id"]: row["latest"] for row in rows}

        num_released = 0
        for flip in flips:
            if flip.owner_id not in checks:
                # The check was deleted after its flips were loaded
                continue
            check = flip.owner = checks[flip.owner_id]
            if check.maintenance_window is not None:
                continue

            claim = Flip.objects.filter(id=flip.id, withheld_outcome=None)
            if latest[check.id] > flip.created or check.status != "down":
                claim.update(withheld_outcome="superseded")
                continue

            if not self.seats.acquire(timeout=1):
                break  # Workers busy, retry in the next pass

            if claim.update(withheld_outcome="released") != 1:
                # Another sendalerts process got there first
                self.seats.release()
                continue

            num_released += 1
            statsd.incr("hc.sendalerts.endOfWindow")
            f: Future[str | None] = self.executor.submit(notify_end_of_window, flip)
            f.add_done_callback(self.on_notify_done)

        return num_released

    def maybe_handle_end_of_window(self) -> None:
        """Run the end-of-window pass if END_OF_WINDOW_INTERVAL has passed."""

        if self.next_end_of_window_pass and now() < self.next_end_of_window_pass:
            return

        self.next_end_of_window_pass = now() + END_OF_WINDOW_INTERVAL
        try:
            self.handle_end_of_window()
        except Exception:
            logger.exception("Exception in end-of-window pass")

    def on_signal(self, signum: int, frame: FrameType | None) -> None:
        desc = signal.strsignal(signum)
        self.stdout.write(f"{desc}, finishing...\n")
        self.shutdown = True

    def handle(self, num_workers: int, pool: bool, **options: Any) -> str:
        db = settings.DATABASES["default"]
        if "OPTIONS" in db and "application_name" in db["OPTIONS"]:
            db["OPTIONS"]["application_name"] = "sendalerts"

        if pool:
            self.stdout.write(
                "WARNING: The --pool argument is not supported any more and will be ignored.\n"
            )

        self.seats = BoundedSemaphore(num_workers)
        self.executor = ThreadPoolExecutor(max_workers=num_workers)

        signal.signal(signal.SIGTERM, self.on_signal)
        signal.signal(signal.SIGINT, self.on_signal)

        self.stdout.write("sendalerts is now running\n")
        while not self.shutdown:
            # Create flips for any checks going down
            while self.handle_going_down() and not self.shutdown:
                pass

            # Submit unprocessed flips to the self.executor. Keep running
            # the end-of-window pass meanwhile, so a steady stream of flips
            # does not delay it.
            while self.process_one_flip() and not self.shutdown:
                self.maybe_handle_end_of_window()

            self.maybe_handle_end_of_window()

            # Either all workers are busy or there are no unprocessed flips.
            # Wait a bit:
            if not self.shutdown:
                time.sleep(2)

        self.executor.shutdown(wait=True)
        return "Done."
