# Brief: maintenance windows

Source: `planning/00-requirement.md` (the change request) and `planning/decisions-log.md` (Q1–Q5, all decided 2026-10-17 by the operator accepting the recommendation). Where this brief and those two differ, they win — except for the two corrections listed under Assumptions (A1, A2), which come from reading the code.

## Problem

Healthchecks already watches checks and alerts on every status change. Each `Flip` row is claimed once by `sendalerts.process_one_flip` (`hc/api/management/commands/sendalerts.py:105-121`). `notify()` then sends it to every channel that `Flip.select_channels` keeps (`sendalerts.py:24-55`, `hc/api/models.py:1390-1408`). The only way to keep this machinery quiet is to pause each check by hand, and that has three costs. It cannot be scheduled. It has no time limit. Resuming resets the check to `new` and clears `last_ping` (`hc/api/views.py:574-590`), so a job that is broken after maintenance stays silent until it pings again. This change adds a **maintenance window**: a named, time-limited period, scoped to a project's checks or to tagged checks. During a window `sendalerts` holds back the notifications it would otherwise send, without changing statuses, pings or statistics. When the window ends, one alert goes out for anything that is still down. Teams that never create a window must see no difference.

## Users

| User | Today | After this change |
|---|---|---|
| Project owner, *Manager* and *Member* roles (`Member.Role`, `hc/accounts/models.py:602-605`) | Pause and resume checks one at a time | Create, edit, end early and delete windows on the dashboard |
| Read-only members | See checks | Also see the Maintenance page, the window history and the "Maintenance" labels. They get no controls, and any write returns 403 |
| Deploy scripts that use the project's read-write API key | Call `/api/v3/checks/…/pause` and `/resume` | Create, list, view, end and delete windows through the API |
| Holders of a read-only key (`hcr_…`) | Read checks | Can also list and view windows. Every write is refused |
| On-call people who get alerts through any of the 29 transports | Get alerts for planned restarts | Get no alerts for covered checks during a window, and one "down" alert at the end if a check is still down. The alert text is the same as today |

## Delta

**New behaviour**
- A new entity, the maintenance window. It belongs to one project and has a UUID, a name (≤100 characters), a start and an end stored in UTC, a scope (all checks, or a tag set of ≤500 characters matched with `Check.matches_tag_set`, `hc/api/models.py:416-417`), a created time, and a creator (set to null when the user is deleted).
- A new project page at `/projects/<code>/maintenance/`, next to `checks/`, `integrations/` and `badges/` (`hc/front/urls.py:42-48`).
- New REST endpoints under the shared `api_urls` (`hc/api/urls.py:49-71`), so they are reachable under v1, v2 and v3.
- `sendalerts` gains a step that decides whether each flip is covered, and an end-of-window pass.

**Changed behaviour** (only when at least one window covers a check)
- `sendalerts` sends no notification for a covered check's flip. The exception is an "up" flip whose matching "down" alert was already sent before the window started.
- The nag date calculation (`Profile.update_next_nag_date`, `hc/accounts/models.py:350-357`) and the list of down checks in the nag email (`sendreports.handle_one_nag`, `hc/api/management/commands/sendreports.py:69-90`) leave out covered checks while a window is active.
- The event log, the checks list and the details page show maintenance information.
- `Check.to_dict` (`hc/api/models.py:439-491`) gains one additive boolean key, `"maintenance"`.

**Removed:** nothing. Pause and resume stay exactly as they are (W6).

## In scope

Each REQ cites the IDs it implements in `planning/00-requirement.md`.

- **REQ-1 Manage windows on the dashboard.** The owner, Managers and Members can create a one-off window with a name, start, end and scope. They can edit an upcoming window, change the end time of an active window or end it now, and delete an upcoming window. Active and ended windows cannot be deleted. A "Start now for 30 min / 1 h / 2 h / 4 h / custom" action is on the Maintenance page and on a check's details page. From the details page it is pre-scoped to that check's tags, or to the whole project when the check has no tags. Validation and limits are those in 00-requirement step 10: end after start, end not in the past, length ≤30 days, name 1–100 characters, tags ≤500 characters, and at most 100 upcoming plus active windows per project. *(M1, M7, M10, S1, D3, D6, D8)*
- **REQ-2 Withhold alerts during a window.** For a covered check, a flip whose `created` time falls in the window (start inclusive, end exclusive) produces no `Notification`. Pings, status, flips, badges, metrics and downtime statistics are unchanged. If a check's down alert was sent before the window started, its recovery ("up") alert is still sent. Overlapping windows combine: a check is covered while any window covers it. Test notifications are not affected. *(M2, M3, D1, D2, D4, D5, D9, D10)*
- **REQ-3 Alert once at the end.** When the last window covering a check ends, and the check is `down` with its down alert withheld, one down alert goes through the check's usual channels within 60 s. This holds when `sendalerts` was not running at the end time (the alert goes out when it next runs) and when several `sendalerts` processes run (never sent twice). *(M4, decisions-log Q3=A)*
- **REQ-4 Leave covered checks out of nags.** While a window is active, covered checks that are down neither start nag reminders nor appear in them. *(M9, D7)*
- **REQ-5 Show maintenance.** The event log shows `Alert not sent: maintenance window "<name>"` on each withheld status change. The checks list and the details page show a "Maintenance" label (text plus icon) on covered checks. The Maintenance page lists active, upcoming and ended windows (ended ones for 90 days), with each window's creator email visible to project members only. Before saving, the form previews which checks the scope covers right now, and warns, without blocking, when it matches none. *(M5, M6, M7, S2)*
- **REQ-6 REST API and docs.** List, create, view, end early and delete windows. Writes need the read-write key; reads also accept the read-only key. Errors use `{"error": "..."}` with status 400, 401, 403 or 404. Responses contain no creator field. `Check.to_dict` gains `"maintenance": true|false`. The new endpoints are documented in `templates/docs/api.md`, and a new user page `templates/docs/maintenance_windows.md` is linked from `configuring_notifications.md`. Both are rendered with `manage.py render_docs`. *(M8, S3, S4, decisions-log Q4=B)*

**Non-functional**
- **NFR-1 Performance.** Maintenance information adds at most 2 SQL queries in total to `/projects/<code>/checks/` and to `GET /api/v3/checks/`, however many checks the project has. `sendalerts` adds at most 1 query per flip. The 2-second idle loop (`sendalerts.py:213`) is not measurably slower when no windows exist.
- **NFR-2 Reliability.** Whether a flip is covered depends only on the window state at `flip.created`. A delayed `sendalerts` gives the same result. End-of-window alerts are delivered at least once and at most once.
- **NFR-3 Security.** Cross-project access returns 404 or 403. Read-only members get 403 on every dashboard write. Read-only keys are refused on every API write. Dashboard POSTs use the existing `@login_required` and `@require_POST` pattern with CSRF protection. Dashboard input is validated with Django forms, and API input with strict Pydantic models (`hc/api/views.py:61`). Names and tags are auto-escaped wherever they are shown.
- **NFR-4 Accessibility.** The page, form and labels meet WCAG 2.2 AA. The label does not rely on colour alone and has contrast ≥4.5:1 in light and dark themes. The time zone is shown next to every time.
- **NFR-5 Observability.** `statsd` counters count withheld alerts and end-of-window alerts (`hc.lib.statsd`). `sendalerts` writes one stdout line per withheld flip, in the existing `"<code> goes <status>"` style (`sendalerts.py:38`).

## Out of scope

- Recurring windows (decisions-log Q2=A). W1.
- Leaving maintenance time out of downtime statistics and reports. Reports keep counting it (decisions-log Q5=A). W2.
- Picking individual checks or individual integrations for a window. W3.
- Notifying anyone when a window starts or ends. W4.
- Windows that span several projects or a whole account. W5.
- Ignoring pings or freezing status during a window. That is what pause does. W6.
- A public status page. W7.
- Banner and "under maintenance" filter on the checks list (C1, C2). They stay *Could* and are not committed in this change.
- Adding maintenance details to alert message templates. The end-of-window alert is the normal "down" message.
- An OpenAPI description of the existing endpoints (see Q7).

## Compatibility promises

- **Status values** stay `new|up|down|paused`, plus the display-only `grace|started` (`hc/api/models.py:38`, `:355-380`). Badges (`/b/…`), Prometheus metrics, `checks/status/` and API clients see `down` for a check that is down during maintenance.
- **JSON shapes.** The `Check.to_dict` keys, the `/flips/` items (`FlipDict {timestamp, up}`, `hc/api/models.py:1355-1358`), `/channels/` and `/pings/` are unchanged, apart from the one additive `"maintenance"` key.
- **URLs.** All existing URLs and URL names (`hc-…`) are unchanged. New routes are added only.
- **`sendalerts`.** Each flip is still claimed exactly once by the conditional UPDATE (`sendalerts.py:110-112`). Flips of uncovered checks are delivered exactly as today. The existing rules in `Flip.select_channels` (`new→up`, `paused→up`, disabled channels, `is_noop`) still apply.
- **Pause and resume** are untouched. A paused check that a window covers stays paused.
- **Data.** Migrations are additive only and pass on SQLite, PostgreSQL, MySQL and MariaDB (`.github/workflows/tests.yml`). `makemigrations --check --dry-run` stays at "No changes detected".
- **Release mechanics.** A line is added under `## v4.5-dev - Unreleased` in `CHANGELOG.md`, keeping its format, because `settings.VERSION` is parsed from that heading (`hc/settings.py:85-89`). Every edited `.md` doc is re-rendered to its `.html-fragment` pair.
- **Baselines.** `manage.py test` passes: 1769 tests OK today, plus the new ones. `mypy --strict hc` shows no errors beyond the 1 that exists today (`hc/settings.py:451`, missing `hc/local_settings.py`, `.forge/repo-map.json` `commands_verified.typecheck`).

## Success measures

1. **No alerts inside a window.** A covered check creates no `Notification` row for flips created inside a window. An uncovered check in the same project still does. *(REQ-2; tested with `time-machine` at exactly the start and end instants.)*
2. **Nothing broken is lost.** Every covered check that is down at window end, with its alert withheld, gets exactly one down `Notification` per enabled channel within 60 s of the end, including when two `sendalerts` processes run. *(REQ-3)*
3. **No change for everyone else.** With zero windows in the database, the full existing suite passes unchanged and the checks list query count is unchanged. *(Compatibility, NFR-1)*
4. **Teams use windows instead of pause.** In the 30 days after release, projects that create windows make fewer pause flips (`new_status="paused"`) than in the 30 days before.

## Decisions

Decided in the decisions log (2026-10-17): Q1=B, scope is all checks or checks matching all given tags. Q2=A, one-off windows only. Q3=A, one down alert at window end. Q4=B, dashboard and REST API. Q5=A, downtime keeps counting.

Recommended in this brief. The outcomes go to the decisions log.
- **Q6 Retention of ended windows: prune inline, per project, when that project's windows are listed or created.** Rejected: a new management command, because self-hosted installs would have to schedule another job. Rejected: keeping windows forever, because 00-requirement promises 90 days.
- **Q7 OpenAPI contract: only the new maintenance-window endpoints.** `templates/docs/api.md` stays the public documentation. Rejected: describing the whole existing API, because it is a large job outside this change.

## Assumptions

- **A1 (correction to 00-requirement).** The change request says ended windows are deleted by the existing `manage.py pruneobjects`. That command only deletes ping bodies of deleted checks from S3 (`hc/api/management/commands/pruneobjects.py:14-43`). No existing job prunes database rows by age. Database cleanup today runs inline: `Check.prune()` runs every 100 pings and deletes old pings, notifications, and flips older than 93 days (`hc/api/models.py:571-603`). Also, the most recent age-based deletion was reverted on 2026-10-16 (commit `9b9e6f96`, `hc/logs/management/commands/sendlogs.py`). This brief therefore follows the inline pattern (Q6).
- **A2 (consequence of A1).** "Alert withheld" marks are pruned along with their flips by `Check.prune()` after 93 days, which is longer than the 90 days windows are kept. A mark whose window has already been deleted keeps working: the event log then shows `Alert not sent: maintenance window` without the name.
- **A3.** No OpenAPI spec exists (`.forge/repo-map.json` `api_spec: null`), and `api.md` is hand-written. The new contract covers only the new endpoints (Q7).
- **A4.** `"maintenance"` is added to `Check.to_dict` for every API version (v1, v2, v3). `to_dict` takes a `v` argument (`hc/api/models.py:439`) only for keys that differ between versions. An additive boolean has no reason to differ, and only v3 is documented.
- **A5.** Flapping notices (`hc/accounts/management/commands/sendflappingnotices.py:24-50`, more than 200 flips in 24 h) are account emails about noisy checks, not alerts. They are not affected, and flips during maintenance still count towards them.
- **A6.** Monthly and weekly reports (`sendreports`) are not alerts. They are unchanged and still list checks that are down during maintenance (consistent with Q5=A). Only nags change (REQ-4).
- **A7.** Overlap with pause is intended. Pause stops monitoring a single check with no time limit. A window silences notifications for a scope, for at most 30 days. Neither replaces the other.
- **A8.** Teams that want a window narrower than the whole project already tag their checks, or are willing to.
- **A9.** At least one `sendalerts` process is deployed. Without one, no alerts are sent today either.
- **A10.** Window names are not secret. Every member of the project can see them, including read-only members.

## Risks

- **R1 Regressing alert delivery for everyone (live system).** `sendalerts.notify` and `Flip.select_channels` are on the path of every alert for every user (`.forge/repo-map.json` hotspots). A bug in the coverage check, or an exception it raises, silences or duplicates real alerts for projects that have no windows. Mitigation to require: when no windows exist, the coverage check is a no-op, and the existing `sendalerts` and `select_channels` tests pass unchanged.
- **R2 Lost or duplicated end-of-window alerts.** The end-of-window pass is a second producer of alerts, alongside timeout flips (`handle_going_down`) and ping flips (`Check.ping`, `hc/api/models.py:535-539`). It must follow the repository's existing pattern of claiming work with a conditional UPDATE. Otherwise two workers both send, or a crash between the claim and the send drops the alert.
- **R3 Edge-case semantics around time.** Possible errors: a flip created exactly at the start or end instant, a window shortened or ended early, an upcoming window edited so it starts in the past, overlapping windows, and DST shifts when converting times entered in `Profile.tz`. Each one is a place where alerts could be wrongly withheld or wrongly sent.
- **R4 Nag change hits all users.** `update_next_nag_date` runs for every flip (`sendalerts.py:33` → `hc/accounts/models.py:350-357`). Changing its "any check down" query risks slowing it down, or nags stopping for users who have no windows.
- **R5 Query count on the checks list.** Showing per-check maintenance labels naively adds N queries to `/projects/<code>/checks/` and `GET /api/v3/checks/`. That breaks NFR-1 for large projects.
- **R6 Silent forever by mistake.** Without the 30-day and 100-window limits enforced on both the dashboard and the API, a typo in the end date silences a project for a very long time. A04 applies here.
- **R7 Conventions and upstream drift.** The change touches upstream hotspots: `hc/api/models.py` (1586 lines), `hc/front/views.py` (1434 lines) and `sendalerts.py`. `CONTRIBUTING.md` says the upstream maintainer accepts no AI-generated contributions, so this fork carries the change on its own and will hit merge conflicts. Other conventions to keep: the `CHANGELOG.md` format (it is load-bearing), the `.html-fragment` regeneration, and `test_it_<behaviour>` test names in `BaseTestCase` subclasses.
- **R8 Untested database engines.** Only SQLite is run locally (`.forge/repo-map.json` `unverified`). Timestamp comparisons and conditional UPDATEs that pass on SQLite can still behave differently on MySQL or MariaDB in CI.
