# Change request: maintenance windows

Operator's words: "Teams need to silence alerts during planned maintenance. Add maintenance windows."

## Problem and goal

**Who is affected.** Members of a project who are responsible for its checks: the project owner and members with the *Member* or *Manager* role (`Member.Role` in `hc/accounts/models.py:602-605`). People who receive alerts through the project's integrations (Slack, email, PagerDuty, SMS, phone calls and so on) are affected too. Read-only members are affected only because they need to see that maintenance is happening.

**What they cannot do today.** A team cannot say ahead of time "between 22:00 and 23:30 on Saturday, do not alert us about these checks". The only tool is to pause each check by hand (`hc/front/views.py:826-849`, `hc/api/views.py:547-568`) and resume it afterwards (`hc/front/views.py:854-867`, `hc/api/views.py:574-590`). Pausing has three costs:
- It must be done by hand for every check, at the moment maintenance starts. It cannot be scheduled.
- Resuming resets the check to `new` and clears `last_ping` (`hc/api/views.py:582-588`). The check then stays silent until its next ping. If the job is broken after maintenance, nobody is told until it has pinged once.
- If someone forgets to resume, the check stays silent with no time limit.

If teams do not pause, every planned restart sends alerts (and SMS or phone-call credits) to on-call people for failures they already expected.

**What changes.** A team member schedules a **maintenance window**: a named period with a start time and an end time that covers all checks in a project, or the checks carrying given tags. While a window is active, checks keep receiving pings and changing status as usual, but no alert notifications are sent for them. When the window ends, alerting resumes on its own. Any covered check that is still down at that moment raises one alert, so a real problem is not lost.

## Current behaviour

Verified in code:

- **Check status.** `Check.status` is one of `new`, `up`, `down`, `paused` (`STATUSES`, `hc/api/models.py:38`). `get_status()` also returns the display-only values `grace` and `started` (`hc/api/models.py:355-380`). The word "maintenance" does not appear anywhere in `hc/` or `templates/` (`.forge/repo-map.json` `relevant_absence`).
- **How alerts are produced.** Every status change inserts a `Flip` row (`Check.create_flip`, `hc/api/models.py:652-672`). There are two sources of "down" flips:
  - timeouts: `sendalerts.handle_going_down` (`hc/api/management/commands/sendalerts.py:123-177`);
  - `/fail` pings and recovery pings: `Check.ping` (`hc/api/models.py:535-539`).
- **How alerts are sent.** `sendalerts.process_one_flip` claims one unprocessed flip with a conditional UPDATE (`sendalerts.py:105-121`). `notify()` then calls `project.update_next_nag_dates()` and `flip.select_channels()`, and runs `Channel.notify` for each channel (`sendalerts.py:24-55`). `Flip.select_channels` already suppresses `new→up` and `paused→up` transitions, disabled channels, and channels whose transport is a no-op for the status (`hc/api/models.py:1390-1408`). The worker loop sleeps 2 s between passes (`sendalerts.py:213`).
- **Silent flips.** Pause and resume create flips with `mark_as_processed=True`, so `sendalerts` never sends them (`hc/api/views.py:557`, `:582`).
- **Nag reminders.** `Profile.update_next_nag_date` starts or clears the hourly or daily nag if any check in the user's projects is `down` (`hc/accounts/models.py:350-357`). `sendreports.handle_one_nag` emails a list of the checks that are down now (`hc/api/management/commands/sendreports.py:69-90`, `hc/accounts/models.py:281-289`).
- **Downtime statistics.** Monthly, weekly and daily reports and the details-page downtime table come from flips (`Check.downtimes_by_boundary`, `hc/api/models.py:612-650`). They do not depend on whether a notification was sent.
- **Tags.** Tags are a space-separated string on the check (`Check.tags`, `hc/api/models.py:195`). A check matches a tag set when it has every tag in it (`Check.matches_tag_set`, `hc/api/models.py:416-417`). `GET /api/v3/checks/?tag=a&tag=b` filters with the same all-tags rule (`hc/api/views.py:421-432`).
- **Permissions.**
  - Dashboard: write actions go through `_get_rw_check_for_user` and `_get_rw_project_for_user`. These allow superusers, the owner, and Member/Manager roles, and raise `PermissionDenied` for read-only members (`hc/front/views.py:112-194`).
  - API: write endpoints use `@authorize` and read endpoints use `@authorize_read`. A read-only key (`hcr_`) cannot write (`hc/api/decorators.py`, `Project.compare_api_key` `hc/accounts/models.py:581-593`).
- **API surface.** `/api/v1/`, `/api/v2/` and `/api/v3/` all route to the same views (`hc/urls.py` → `hc/api/urls.py:49-71`). The check JSON shape is `Check.to_dict` (`hc/api/models.py:439-491`). The REST API is documented by hand in `templates/docs/api.md`.
- **Project pages.** Project-level dashboard pages live under `/projects/<code>/`: `checks/`, `integrations/`, `badges/` (`hc/front/urls.py:42-48`), plus `settings/` (`hc/accounts/urls.py:9`).
- **Time zones.** Each user has a time zone in `Profile.tz` (`hc/accounts/models.py:103`). Each check has its own `Check.tz` (`hc/api/models.py:204`).

## Desired behaviour

Described as a user would describe it:

1. **Schedule a window.** On the project's new *Maintenance* page, I click "Schedule maintenance". I enter:
   - a name, for example "Postgres upgrade";
   - a start date and time and an end date and time, shown and entered in my profile time zone;
   - a scope: *all checks in this project*, or *checks with all of these tags*.

   Before I save, the form shows how many checks, and which ones, the window covers right now. When I save, the window is listed as *Upcoming*, or as *Active* if it has already started.
2. **Start now.** Instead of picking a start time, I can choose "Start now for 30 min / 1 h / 2 h / 4 h / custom". This creates a window that is active immediately.
3. **During the window.** Covered checks still receive pings, still go down and come back up, and the event log and downtime statistics still record this.
   - No integration is notified for a status change of a covered check that happens while the window is active.
   - The check's event log shows that change with the text "Alert not sent: maintenance window "Postgres upgrade"".
   - The checks list and the check details page show a "Maintenance" label on covered checks. The label is text plus an icon, not colour alone.
   - Covered checks that are down do not trigger or count towards nag reminder emails.
4. **Coming back up during the window.**
   - A check that went down inside the window and recovers inside it sends nothing.
   - A check that went down **before** the window started, and whose down alert was already sent, still sends its recovery ("up") alert when it recovers during the window. Otherwise the on-call person would think it is still broken.
5. **When the window ends.** Alerting resumes on its own; nobody has to resume anything.
   - Every covered check that is down when the window ends, and whose down alert was not sent because of the window, sends exactly one "down" alert through its usual integrations within 1 minute of the end time.
   - Checks that are up at the end send nothing.
6. **Changing plans.**
   - I can edit an upcoming window: name, times and scope.
   - I can extend or shorten an active window by changing its end time, or click "End now".
   - I can delete an upcoming window.
   - I cannot delete an active or ended window. Ended windows stay visible in the window list for 90 days as history: name, times, scope, and who created it.
7. **Overlapping windows.** If a check is covered by several windows, it is under maintenance while **any** of them is active. The end-of-window alert is sent only when the last covering window ends.
8. **Automation.** A deploy script can create a window, list the project's windows, end a window early and delete an upcoming window through the REST API, using the project's read-write API key. A read-only key can list windows but cannot change them.
9. **Who can do it.**
   - The owner, Managers and Members can create, edit, end and delete windows.
   - Read-only members can see the Maintenance page and the "Maintenance" labels, but the controls are not shown to them, and direct POSTs return 403.
   - Users from other projects get 404 or 403, never the data.
10. **When something goes wrong.**
    - Invalid input is rejected with a message next to the field (dashboard) or `400 {"error": "..."}` (API), and nothing is saved. Invalid input is:
      - end time not after start time;
      - end time in the past;
      - window longer than 30 days;
      - name empty or over 100 characters;
      - tags over 500 characters;
      - a time that cannot be parsed or has no time zone (API).
    - A project can hold at most 100 upcoming plus active windows. Creating the 101st returns a clear error.
    - If the tag scope matches no checks right now, the form warns but still allows saving, because checks can gain tags later. Coverage is decided when each status change happens, not when the window is created.
    - If `sendalerts` is not running when a window ends, the end-of-window alerts are sent when it next runs. They are not lost.
    - Test notifications sent with an integration's "Test" button are not affected by maintenance windows.

## Capabilities

**Must**
- M1. Owners, Managers and Members can create a one-off maintenance window for a project. A window has a name, a start, an end, and a scope (all checks, or checks matching all given tags).
- M2. While a window is active, no notification is sent for a covered check's status change. Pings, status, event log and downtime statistics keep working as today.
- M3. Recovery alerts are still sent for checks whose down alert was sent before the window started.
- M4. When the last window covering a check ends and the check is down with its alert withheld, one down alert is sent within 1 minute.
- M5. The event log of a covered check shows which status changes were silenced and by which window.
- M6. The checks list and the check details page mark covered checks with a visible "Maintenance" label while a window is active.
- M7. A project Maintenance page lists active, upcoming and recently ended windows, with edit, end-now and delete as permitted.
- M8. REST API endpoints to list, create, view, end early, and delete windows, with existing key rules: read-write key for changes, read-only key for reading. Documented in `templates/docs/api.md`.
- M9. Covered down checks do not cause or appear in nag reminder emails while a window is active.
- M10. Input validation and limits as listed under Desired behaviour step 10.

**Should**
- S1. "Start now for N hours" quick action on the Maintenance page and on a check's details page. From the details page it is pre-scoped to that check's tags, and to the whole project when the check has no tags.
- S2. A preview of the checks a window covers, shown before saving.
- S3. The check JSON (`Check.to_dict`) gains an additive boolean `"maintenance"` that is `true` while the check is covered by an active window.
- S4. A user documentation page `templates/docs/maintenance_windows.md` explaining behaviour, with a link from `configuring_notifications.md`.

**Could**
- C1. A banner on the project's checks page while any window is active.
- C2. A filter on the checks list showing only checks under maintenance.

**Won't for now**
- W1. Recurring windows (cron or OnCalendar schedules). One-off windows plus the API cover planned maintenance; recurrence adds schedule, DST and editing complexity (open question Q2).
- W2. Excluding maintenance time from downtime statistics and uptime reports. Reports keep showing what really happened (open question Q5).
- W3. Choosing individual checks or individual integrations for a window. Tags already select groups of checks in this product. Per-integration muting is a different feature.
- W4. Notifying the team when a window starts or ends. This adds noise against the purpose of the change. The Maintenance page and the labels give visibility.
- W5. Windows spanning several projects or the whole account. A window belongs to one project, matching how checks, integrations and API keys are scoped.
- W6. Ignoring pings, or freezing status, during a window. That is what pause does, and pause stays as it is.
- W7. A public status page announcing maintenance. There is no status-page feature to attach it to.

## Compatibility

These must keep working unchanged:
- **Check status values** stay `new|up|down|paused` (plus display-only `grace|started`). No new status value is added. API clients, badges (`/b/...`), Prometheus metrics (`/projects/<code>/metrics/`) and `checks/status/` keep their current values. A check that is down during maintenance still reports `down`.
- **API JSON shapes.** The `Check.to_dict` keys (`hc/api/models.py:439-491`), the `/flips/` items (`FlipDict` `{timestamp, up}`, `hc/api/models.py:1355-1388`), and the `/channels/` and `/pings/` responses stay the same. The only addition is the optional key in S3. New endpoints are added under the shared `api_urls`, so they appear under `/api/v1/`, `/api/v2/` and `/api/v3/` like every other endpoint. Only v3 is documented.
- **Pause and resume** behave exactly as today. A paused check covered by a window stays paused.
- **Existing suppression rules** in `Flip.select_channels` (`new→up`, `paused→up`, disabled channels, `is_noop`) still apply.
- **`sendalerts`.** Each flip is still claimed exactly once by the conditional UPDATE. Running several `sendalerts` processes must not send an end-of-window alert twice. Flips of checks not covered by any window are delivered exactly as today.
- **Data migration** is additive only: new table(s), with optional new columns if the design needs them. It must work on SQLite, PostgreSQL, MySQL and MariaDB (the CI matrix in `.github/workflows/tests.yml`). `makemigrations --check` must stay clean.
- **People.** On-call staff who get alerts through any of the 29 transports must see no change in alert content. Teams that never create a window must see no change at all.
- **Release mechanics.** Add a `CHANGELOG.md` entry under the existing `## v4.5-dev - Unreleased` heading, keeping its format, because `settings.VERSION` is parsed from it (`hc/settings.py:85-89`). After editing docs Markdown, regenerate the rendered `.html-fragment` files with `manage.py render_docs`.

## Data

**Added**
- *Maintenance window*, owned by a project and deleted when the project is deleted. It stores:
  - a public identifier (UUID), used in URLs and the API;
  - name, up to 100 characters;
  - start and end, stored in UTC;
  - scope: all checks, or a tag set of up to 500 characters;
  - created time;
  - the user who created it.
- A per-status-change record of "alert withheld by window X", needed for M4 and M5. How this is stored (a field on `Flip` or a separate table) is the Architect's decision.

**Altered.** Nothing existing is renamed or removed. `Check.to_dict` gains one additive key (S3).

**Personal data.** "Created by" links to a user account and is shown to project members as the user's email. It is personal data. When the user account is deleted, the window keeps working and shows "deleted user": the link is set to null, not cascaded. Window names are free text that users type. They are treated as untrusted and are not expected to contain personal data.

**Retention.** Windows that ended more than 90 days ago are deleted by the existing pruning job (`manage.py pruneobjects`). The "alert withheld" marks live as long as the flips or log events they describe, and are pruned with them.

## Quality expectations

**Security (OWASP Top 10)**
- A01 Broken access control. Every dashboard view and API endpoint checks that the window belongs to the requesting project or user. Tests must show:
  - a user from another project gets 404 or 403;
  - a read-only member gets 403 on every write;
  - a read-only API key gets 401 or 403 on every write.
- CSRF protection on every dashboard POST, following the existing `@require_POST` and `@login_required` pattern.
- A03 Injection. All input is validated server-side: API with strict Pydantic models, as in `hc/api/views.py:61`; dashboard with Django forms. Window names and tags are auto-escaped in HTML and in alert or email templates.
- A04 Insecure design. The 30-day maximum length and the 100-window limit stop a window from silencing a project indefinitely or by mistake.
- API errors use the existing `{"error": msg}` format and never leak data from other projects.

**Privacy.** Creator emails are shown only to members of the same project. They do not appear in API responses; the API returns no creator field.

**Accessibility.** WCAG 2.2 AA for the Maintenance page, the window form and the labels:
- every input has a programmatic label, and validation errors are announced next to the field;
- everything works by keyboard alone, and modals trap and restore focus;
- the "Maintenance" label uses text and an icon, with contrast of at least 4.5:1, in both light and dark themes;
- time zone shown next to every time.

**Performance**
- The checks list (`/projects/<code>/checks/`) and `GET /api/v3/checks/` add at most 2 SQL queries in total for maintenance information, however many checks the project has. No per-check queries.
- `sendalerts` adds at most 1 query per processed flip to decide coverage.
- The end-of-window pass is cheap enough that the loop's 2-second idle cycle (`sendalerts.py:213`) is not measurably longer when no windows exist.

**Reliability**
- Whether a status change is covered is decided from the window state at the time of the flip's `created` timestamp. It does not depend on when `sendalerts` processes the flip, so a delayed worker gives the same result.
- End-of-window alerts are delivered at least once and at most once, also with several `sendalerts` processes running.

**Observability**
- `statsd` counters are incremented for withheld alerts and for end-of-window alerts (`hc.lib.statsd`).
- `sendalerts` writes one stdout log line per withheld flip, in the existing `"<code> goes <status>"` style.

**Tests.** New behaviour is covered by `BaseTestCase`-style tests (`hc/test.py`) with `time-machine`. Window boundaries are tested at exactly the start and end instants: start is inclusive, end is exclusive. The full suite (`manage.py test`) and `mypy --strict hc` must stay at their current results.

## Industry practice

- **Datadog Downtimes.** Scoped by monitor name or by monitor tags; a monitor must match all selected tags. Monitors created later are included automatically if they match. A preview of affected monitors is shown. Monitors keep evaluating and changing state while notifications are silenced. Recurrence is optional. ([docs.datadoghq.com/monitors/downtimes](https://docs.datadoghq.com/monitors/downtimes/), [API](https://docs.datadoghq.com/api/latest/downtimes/schedule-a-downtime/), [examples](https://docs.datadoghq.com/monitors/downtimes/examples/))
- **PagerDuty Maintenance Windows.** No new incidents trigger during the window, and incidents already open keep notifying. A started window cannot be deleted, only ended early. The community reports that dropped events are invisible, which users dislike. ([support.pagerduty.com/docs/maintenance-windows](https://support.pagerduty.com/docs/maintenance-windows), [Pulumi provider docs](https://www.pulumi.com/registry/packages/pagerduty/api-docs/maintenancewindow/))
- **SigNoz planned maintenance.** One-off or recurring windows. If no specific alert is selected, all alerts are silenced. ([signoz.io/docs/alerts-management/planned-maintenance](https://signoz.io/docs/alerts-management/planned-maintenance))
- **incident.io maintenance windows.** Alerts during the window can be held, or attached and escalated, instead of dropped. ([incident.io changelog](https://incident.io/changelog/maintenance-windows), [docs](https://docs.incident.io/alerts/maintenance-silencing))
- **Cronjob Guardian** (cron monitoring). Windows silence alerts but execution tracking continues. ([guide](https://www.mintlify.com/iLLeniumStudios/cronjob-guardian/guides/maintenance-windows))

**Adopted here**
- Tag-based scoping with all-tags matching. It is the same rule as `Check.matches_tag_set`, and new checks are covered automatically.
- Silence notifications only; monitoring keeps running.
- Preview of covered checks.
- Started windows can be ended but not deleted.
- Silenced events stay visible in the event log.
- Alerts already in progress complete: recovery alerts for checks already alerted are still sent.
- One alert at the end for anything still broken. This is the "hold, then escalate" pattern from incident.io, and it avoids PagerDuty's lost-event weakness.

**Not adopted now:** recurrence (W1), per-integration muting (W3).

The Cronitor-specific search returned no Cronitor documentation, so Cronitor is not cited.

## Success measures

1. **No alerts inside a window.** For a check covered by an active window, no `Notification` row is created for status changes that happen inside the window. Checks outside the scope in the same project still get theirs. This is checkable in tests and, in production, by comparing `api_notification.created` with window intervals.
2. **Nothing broken is lost.** Every covered check that is down at window end, with its alert withheld, gets exactly one down `Notification` per enabled integration within 60 seconds of the end time. There are no duplicates when two `sendalerts` processes run.
3. **Teams switch from pause to windows.** Within 30 days of release, projects that create maintenance windows make fewer pause and resume calls (pause-type flips, `new_status="paused"`) than in the 30 days before.

## Decisions

**Settled from the request or by sensible default**
- D1. A window silences **notifications only**. Pings, status changes, event log, downtime statistics, badges and metrics carry on unchanged. Reason: the request says "silence alerts", not "stop monitoring" (Datadog and Cronjob Guardian behave the same way).
- D2. No new check status value. "Maintenance" is a separate label and an additive API field. Reason: status values are relied on by API clients, badges and metrics.
- D3. A window belongs to one project. The owner, Managers and Members can manage it; read-only members and read-only keys can view it. Reason: this matches pause/resume and existing role rules.
- D4. Start is inclusive and end is exclusive. Times are stored in UTC and shown in the viewing user's `Profile.tz`.
- D5. Overlapping windows combine: a check is covered while any window covers it.
- D6. Limits: end is required; the maximum length is 30 days; at most 100 upcoming plus active windows per project. Reason: a forgotten window must expire on its own.
- D7. Covered down checks are left out of nag reminders while a window is active (M9). Reason: nags are alerts too.
- D8. Started windows can be ended early or extended, but not deleted. Ended windows are kept 90 days, then pruned.
- D9. Recovery alerts for checks already alerted before the window are still sent (M3).
- D10. Test notifications are not affected.

**Open questions, written as if the recommendation were accepted**
- Q1. What can a window cover? **Recommended: all checks in the project, or checks matching all given tags.**
- Q2. One-off windows only, or recurring too? **Recommended: one-off only in this release.**
- Q3. What happens at window end for a check that is still down? **Recommended: send one down alert.**
- Q4. Dashboard only, or dashboard and REST API? **Recommended: both.**
- Q5. Do maintenance outages count in downtime statistics and reports? **Recommended: yes, keep counting.**

The outcome of each question is recorded in the decisions log.

## Assumptions

- Teams that use maintenance windows already tag their checks, or are willing to, when they want a window narrower than the whole project.
- One `sendalerts` process or more is always deployed. Self-hosted installs without it get no alerts today either.
- 30 days is long enough for any single planned maintenance.
- A window name is not secret. It may be shown to every member of the project, including read-only members.
- Alert message templates for the 29 transports do not need to mention maintenance. The end-of-window alert uses the normal "down" message.
