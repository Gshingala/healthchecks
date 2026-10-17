# PRD: maintenance windows

Inputs: `planning/00-requirement.md` (change request, capability IDs M*, S*, C*, W*, D*), `planning/decisions-log.md` (Q1–Q7, all decided 2026-10-17), `planning/01-brief.md` (capabilities REQ-1…REQ-6, NFR-1…NFR-5, assumptions A1–A10, risks R1–R8), `.forge/repo-map.json`.

**Numbering.** Each functional requirement here is `REQ-<brief capability>.<n>`. For example, REQ-2.4 is the fourth requirement under brief REQ-2. Non-functional requirements follow the same rule (`NFR-1.2`). Categories the brief does not cover start at NFR-6. IDs are never reused.

**Vocabulary.** These words are used with exactly these meanings throughout.

| Term | Meaning |
|---|---|
| maintenance window (window) | The new entity. A named one-off period `[start, end)` that belongs to one project. |
| scope | What a window covers: *all checks* in the project, or *checks with all of these tags*. |
| covers (check C at instant t) | C belongs to the window's project, `start ≤ t < end`, and either the scope is *all checks* or `C.matches_tag_set(window tags)` is true (`hc/api/models.py:416-417`). The project and tags used are C's values when `sendalerts` evaluates the flip. |
| covered (check C now) | At least one window covers C at the current instant. |
| flip | An existing `Flip` row (`hc/api/models.py:1361`) that records one status change. |
| withheld flip | A flip that `sendalerts` processed without sending notifications, because of rule REQ-2.1 or REQ-2.6. It carries a *withheld mark*. |
| released | A withheld **down** flip whose single down alert was later sent by the end-of-window pass (REQ-3). |
| end-of-window pass | The new `sendalerts` step that sends the alerts for withheld down flips that are released. |
| upcoming / active / ended | Window states, derived from time: `now < start`, `start ≤ now < end`, `end ≤ now`. |
| writer | Project owner, a member with role *Member* (`w`) or *Manager* (`m`), or a superuser (`hc/accounts/models.py:601-605`, `hc/front/views.py:112-194`). |
| read-only member | A member with role *Read-only* (`r`). |
| read-write key / read-only key | `Project.api_key` / `Project.api_key_readonly` (`hcr_…`), as checked by `@authorize` and `@authorize_read` (`hc/api/decorators.py:33-93`). |

---

## Goals and success criteria

**Goals**

| # | Goal | Serves |
|---|---|---|
| G1 | A writer can silence alerts for a scope of a project's checks for a bounded period that is set in advance or starts now. Nothing has to be done when the period ends. | M1, M2, S1 |
| G2 | Monitoring keeps running during a window. Pings, statuses, flips, the event log, badges, metrics and downtime statistics behave as they do today. | M2, D1, D2, Q5=A |
| G3 | A real failure is not lost. Anything still down when the last covering window ends raises one down alert. | M4, Q3=A |
| G4 | A project with no windows sees no difference in behaviour, output or query count. | Compatibility |

**Success criteria.** Each one is checked by running something.

| # | Criterion | How checked |
|---|---|---|
| SC-1 | A covered check's flips with `start ≤ created < end` create 0 `Notification` rows. In the same test, an uncovered check in the same project creates 1 per enabled channel. | Test with `time-machine` at exactly `start` and at `end` (REQ-2.1, REQ-2.2, REQ-2.3) |
| SC-2 | Every covered check that is down at window end with its down flip withheld gets exactly 1 down `Notification` per channel that `Flip.select_channels` returns, within 60 s of `end`. This holds with 2 `sendalerts` processes running. | Tests for REQ-3.1 and REQ-3.6 |
| SC-3 | With 0 windows in the database, the existing suite passes (1769 tests OK today, `.forge/repo-map.json` `commands_verified.test`) and the query count of `/projects/<code>/checks/` and `GET /api/v3/checks/` grows by at most 2. | `manage.py test`, `assertNumQueries` (NFR-1.1) |
| SC-4 | `mypy --strict hc` reports no errors other than the 1 that exists today (`hc/settings.py:451`). `makemigrations --check --dry-run` prints "No changes detected". | CI commands (NFR-9.1, NFR-9.2) |
| SC-5 | Within 30 days after release, projects that have created ≥1 window make fewer `Flip(new_status="paused")` than they did in the 30 days before. | SQL on production data. Product outcome, not a release gate. |

---

## Users and permissions

"Non-member" means a logged-in user with no `Member` row in the project, who is not its owner and not a superuser. Dashboard denials follow the existing helpers: `_get_project_for_user` gives 404 to non-members, and `_get_rw_project_for_user` raises `PermissionDenied` (403) for read-only members (`hc/front/views.py:172-194`). API denials follow the existing views: a missing or malformed key gives 401, a read-only key on a write gives 401 `wrong api key` (`hc/api/decorators.py:58-60`), and a window in another project gives 403 (the same pattern as `hc/api/views.py:548-550`).

| Action | Writer | Read-only member | Non-member | Anonymous | Read-write key | Read-only key | Key of another project |
|---|---|---|---|---|---|---|---|
| View Maintenance page | ✔ | ✔ | 404 | redirect to login | — | — | — |
| Preview covered checks | ✔ | ✔ | 404 | redirect to login | — | — | — |
| Create window (scheduled or start-now) | ✔ | 403 | 404 | redirect to login | ✔ | 401 | — |
| Edit window | ✔ | 403 | 404 | redirect to login | — (no API edit) | — | — |
| End window now | ✔ | 403 | 404 | redirect to login | ✔ | 401 | 403 |
| Delete upcoming window | ✔ | 403 | 404 | redirect to login | ✔ | 401 | 403 |
| List windows | ✔ (page) | ✔ (page) | 404 | redirect to login | ✔ | ✔ | — (sees only its own project) |
| View one window | ✔ (page) | ✔ (page) | 404 | redirect to login | ✔ | ✔ | 403 |
| See creator email | ✔ | ✔ | ✘ | ✘ | ✘ (never in API) | ✘ | ✘ |
| See "Maintenance" label | ✔ | ✔ | ✘ | ✘ | `"maintenance"` key | `"maintenance"` key | ✘ |

---

## Functional requirements

Priorities: **Must** means the release is blocked without it. **Should** may be cut, and the cut must be recorded. **Could** is not committed.

### Epic E1 — Manage windows on the dashboard (brief REQ-1; M1, M7, M10, S1, D3, D6, D8)

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-1.1 | Must | **Given** a member of any role in project P, **when** they open any page of P, **then** the project navigation shows a "Maintenance" link to `/projects/<P>/maintenance/`, next to Checks, Integrations and Badges. GET on that URL returns 200. |
| REQ-1.2 | Must | **Given** a writer whose `Profile.tz` is `Europe/Riga`, **when** they submit name "Postgres upgrade", start `2026-11-07 22:00`, end `2026-11-07 23:30`, scope *all checks*, at a time before the start, **then** one window is stored with start `2026-11-07T20:00:00Z`, end `2026-11-07T21:30:00Z`, empty tags, `created_by` = that user and `created_via` = `dashboard`. The response redirects (302) to the Maintenance page, where the window is listed under *Upcoming*. |
| REQ-1.3 | Must | **Given** a writer, **when** they submit a valid window whose start is at or before the current instant, **then** the stored start is the current server instant, truncated to the second, and the window is listed under *Active*. **DECISION:** a start in the past is moved forward to now and never applied retroactively. Reason: flips already processed cannot be withheld after the fact, so coverage before "now" would show something that did not happen. |
| REQ-1.4 | Must | **Given** a writer, **when** they submit any input listed under *Validation and errors* as rejected, **then** no window is created or changed, the form is shown again with HTTP 200, the message from that table appears next to the field it names, and the values entered are kept. |
| REQ-1.5 | Must | **Given** project P already has 100 windows that are upcoming or active, **when** a writer submits a valid new window, **then** nothing is saved and the form shows "This project already has 100 upcoming or active maintenance windows. End or delete one before adding another." Ended windows do not count towards the limit. |
| REQ-1.6 | Should | **Given** a writer on the Maintenance page, **when** they choose "Start now" with 30 min, 1 h, 2 h, 4 h, or a custom length (whole minutes, 1 to 43 200), a name and a scope, **then** a window is created with start = now and end = now + the length, and it is listed under *Active*. |
| REQ-1.7 | Should | **Given** a writer on the details page of check C, **when** they open "Start maintenance", **then** the form is pre-filled with scope *checks with all of these tags* = `C.tags` when `C.tags` is not empty, or with scope *all checks* when it is empty, and with name `Maintenance: <C name or code>` truncated to 100 characters. Submitting it behaves as REQ-1.6. |
| REQ-1.8 | Must | **Given** an upcoming window W, **when** a writer submits an edit that changes any of name, start, end and scope, and the values pass validation, **then** W is updated, its UUID and `created_by` are unchanged, and the page redirects (302) to the Maintenance page. REQ-1.3 applies to the new start. |
| REQ-1.9 | Must | **Given** an active window W, **when** a writer submits a new name and/or a new end that passes validation, **then** W is updated. The new end may be earlier or later than the old one. |
| REQ-1.10 | Must | **Given** an active window W, **when** a writer submits a change to its start or scope, **then** nothing is saved and the form shows "This window has already started. Only its name and end time can be changed." This also applies when the form was loaded while W was upcoming. |
| REQ-1.11 | Must | **Given** an active window W, **when** a writer clicks "End now" and confirms, **then** W.end is set to the current instant and W moves to *Ended*. |
| REQ-1.12 | Must | **Given** an upcoming window W, **when** a writer clicks "Delete" and confirms, **then** W no longer exists and the page shows "Maintenance window deleted." |
| REQ-1.13 | Must | **Given** an active or ended window W, **when** a writer POSTs to its delete URL, **then** W is not deleted, the response is 400, and the page shows "Only upcoming maintenance windows can be deleted. Use End now to stop an active window." The Delete control is shown only for upcoming windows. |
| REQ-1.14 | Must | **Given** an ended window W, **when** a writer POSTs an edit or "End now" for it, **then** nothing changes and the response is 400 with the message "This maintenance window has ended and can no longer be changed." |
| REQ-1.15 | Must | **Given** a read-only member of P, **when** they view the Maintenance page or a check's details page, **then** no Schedule, Start now, Edit, End now or Delete control is rendered. **When** they POST to any window write URL, **then** the response is 403 and nothing changes. |
| REQ-1.16 | Must | **Given** a non-member of P, **when** they GET or POST any `/projects/<P>/maintenance/…` URL, **then** the response is 404 and contains no window data. |
| REQ-1.17 | Must | **Given** window W belongs to project Q, **when** a writer of P requests `/projects/<P>/maintenance/<W>/…`, **then** the response is 404, even when the same user is also a member of Q. |
| REQ-1.18 | Must | **Given** a writer whose `Profile.tz` has a DST change, **when** they enter a local time that does not exist (inside the spring-forward gap), **then** the form shows "<time> does not exist in <tz> because of a daylight-saving change. Choose another time." **When** they enter an ambiguous local time (inside the fall-back hour), **then** the first occurrence is used (`fold=0`). **DECISION:** use the first occurrence and do not reject. Reason: it matches what most users mean, and the saved time is shown afterwards with its UTC offset. |
| REQ-1.19 | Must | **Given** a writer submits the create form twice with identical values, **when** both requests succeed, **then** two windows exist. **DECISION:** windows have no uniqueness rule, and names may repeat. Reason: overlapping windows are allowed (REQ-2.7), so a duplicate does no harm. The submit button is disabled after the first click, which prevents most accidental repeats. |
| REQ-1.20 | Must | **Given** a writer creates, edits, ends or deletes a window, **when** the request succeeds, **then** `Profile.update_next_nag_date` is recomputed for every member and the owner of P before the response returns, so that REQ-4.1 holds at once. |

### Epic E2 — Withhold alerts during a window (brief REQ-2; M2, M3, D1, D2, D4, D5, D9, D10)

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-2.1 | Must | **Given** check C is covered at instant `flip.created` by window W, and C has ≥1 enabled channel, **when** `sendalerts` processes a **down** flip of C, **then** 0 `Notification` rows are created, the flip gets `processed` set as today, the flip gets a withheld mark that references W, and C's `status`, `last_ping`, `alert_after` and pings are exactly what they would be with no window. |
| REQ-2.2 | Must | **Given** window W has `start = S` and `end = E`, **when** a covered check's down flip has `created == S`, **then** it is withheld. **When** its `created == E`, **then** it is delivered as today. Start is inclusive and end is exclusive. |
| REQ-2.3 | Must | **Given** a project with a window of scope `tags = "db prod"`, check A with tags `prod db web` and check B with tags `db`, **when** both go down inside the window, **then** A's flip is withheld and B's flip is delivered as today. Tag matching is exact and case-sensitive, as in `Check.matches_tag_set`. |
| REQ-2.4 | Must | **Given** a window of scope *all checks* in P, **when** a check of another project P2 goes down inside the window, **then** P2's flip is delivered as today. |
| REQ-2.5 | Must | **Given** check C went down before window W started and the down notification was delivered, **when** C goes up while W covers it, **then** the up flip is delivered through `Flip.select_channels` as today (M3). |
| REQ-2.6 | Must | **Given** check C's most recent down flip before an up flip U is withheld and **not released**, **when** `sendalerts` processes U, **then** U is withheld (0 notifications, withheld mark set), whether or not a window covers C at `U.created`. **DECISION:** an up flip is withheld also after the window ends when its down flip was never alerted. Reason: an "up" alert with no earlier "down" alert confuses on-call people, and this case happens when a check recovers after the window ends but before the end-of-window pass runs. |
| REQ-2.7 | Must | **Given** windows W1 `[10:00, 11:00)` and W2 `[10:30, 12:00)` both cover check C, **when** C goes down at 10:59 or at 11:30, **then** the flip is withheld. Its withheld mark references the covering window with the latest `end`, which is W2. |
| REQ-2.8 | Must | **Given** check C is covered and down, **when** a client reads `/b/…` badges, `/projects/<code>/metrics/…`, `GET /api/v3/checks/<C>` `status`, `GET /api/v3/checks/<C>/flips/`, or the details-page downtime table, **then** each shows the same values it would show with no window: `down`, a flip item `{timestamp, up: 0}`, and downtime counted (Q5=A). |
| REQ-2.9 | Must | **Given** a window covers every check in P, **when** a writer clicks an integration's "Test" button, **then** the test notification is sent as today. Its `Notification.owner` is null, so coverage never applies (`hc/api/models.py:1340-1342`). |
| REQ-2.10 | Must | **Given** check C has no covering window at `flip.created` and its preceding down flip (if any) is not withheld-and-unreleased, **when** `sendalerts` processes a flip of C, **then** delivery is identical to today, including the existing `Flip.select_channels` exclusions (`new→up`, `paused→up`, disabled channels, `is_noop`, `hc/api/models.py:1390-1408`). |
| REQ-2.11 | Must | **Given** a down flip F of a covered check was created at `t` while window W had end `E > t`, **when** `sendalerts` first processes F at `t + 10 min`, after W was ended with End now at `t + 5 min`, **then** F is still withheld, because coverage uses W's interval as stored at processing time evaluated at `F.created` (NFR-2.1). |
| REQ-2.12 | Must | **Given** check C is paused and covered, **when** it is resumed or pinged during the window, **then** pause and resume behave exactly as today, because their flips are created with `mark_as_processed=True` (`hc/api/views.py:557`, `:582`) and `sendalerts` never evaluates them. |
| REQ-2.13 | Must | **Given** `sendalerts` withholds a flip, **when** it finishes processing it, **then** it writes one stdout line `<check code> goes <status> (alert withheld: maintenance window <window code>)` and increments the statsd counter `hc.sendalerts.withheld` by 1. |

### Epic E3 — Alert once at the end (brief REQ-3; M4, Q3=A)

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-3.1 | Must | **Given** check C's most recent flip is a withheld, unreleased **down** flip F, `C.status == "down"`, and no window covers C now, **when** the end-of-window pass runs, **then** F is marked released and, for each channel returned by `Flip.select_channels` for F, exactly 1 `Notification` with `check_status="down"` is created and the transport is called once. The pass runs at least every 30 s while `sendalerts` runs, so the alert goes out within 60 s of the last covering window's `end`. |
| REQ-3.2 | Must | **Given** check C went down and came back up inside a window, so its latest flip is a withheld up flip, **when** the window ends, **then** 0 notifications are created for C. |
| REQ-3.3 | Must | **Given** W1 `[10:00, 11:00)` and W2 `[10:30, 12:00)` cover check C, which is down with a withheld down flip, **when** the time reaches 11:00, **then** no alert is sent. **When** it reaches 12:00, **then** the alert of REQ-3.1 is sent within 60 s. |
| REQ-3.4 | Must | **Given** an active window W covers check C, which is down and withheld, **when** a writer clicks End now (or calls the API end), **then** the alert of REQ-3.1 is sent within 60 s of that instant. |
| REQ-3.5 | Must | **Given** no `sendalerts` process runs at window end, **when** a `sendalerts` process starts N minutes later, **then** the alert of REQ-3.1 is sent within 60 s of that start, exactly once. |
| REQ-3.6 | Must | **Given** 2 `sendalerts` processes run against the same database, **when** check C becomes eligible under REQ-3.1, **then** the total number of down `Notification` rows for C per channel is exactly 1. The release is claimed with a conditional UPDATE whose row count is checked, following the claim of `process_one_flip` (`sendalerts.py:110-115`). |
| REQ-3.7 | Must | **Given** an active window with scope `tags = "db"` covers check C, which is down and withheld, **when** a writer removes the tag `db` from C before the window ends, **then** C is no longer covered and the alert of REQ-3.1 is sent within 60 s of the tag change. **DECISION:** eligibility for release is "not covered now", not "a window just ended". Reason: tag edits, project transfers and End now then all go through one rule, and no withheld alert is left behind. |
| REQ-3.8 | Must | **Given** a window with an unreleased withheld down flip of check C, **when** a writer extends the window's end before it is reached, **then** no alert is sent at the old end, and REQ-3.1 applies at the new end. |
| REQ-3.9 | Must | **Given** check C has an unreleased withheld down flip, **when** at the end-of-window pass C is `paused`, or C has been deleted, **then** no notification is sent for it. |
| REQ-3.10 | Must | **Given** F was released for check C, **when** C later goes up outside any window, **then** the up flip is delivered as today (REQ-2.10 applies, because the preceding down flip is released). |
| REQ-3.11 | Must | **Given** an end-of-window alert for check C, **when** any of the 29 transports renders it, **then** the content is identical to the down alert the transport sends today for C. No maintenance wording is added. |
| REQ-3.12 | Must | **Given** the end-of-window pass sends an alert, **when** it finishes, **then** it writes one stdout line `<check code> goes down (end of maintenance)` followed by the per-channel lines already written by `notify` (`sendalerts.py:38-48`), and increments the statsd counter `hc.sendalerts.endOfWindow` by 1 per check. |
| REQ-3.13 | Must | **Given** 0 windows and 0 withheld flips exist, **when** the end-of-window pass runs, **then** it issues at most 1 SQL query and sends nothing (NFR-1.3, R1). |

### Epic E4 — Leave covered checks out of nags (brief REQ-4; M9, D7)

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-4.1 | Must | **Given** a user's only down checks are all covered now, **when** `Profile.update_next_nag_date` runs (`hc/accounts/models.py:350-357`), **then** `next_nag_date` is cleared if it was set, and is not set if it was empty. |
| REQ-4.2 | Must | **Given** a user has down check A (covered) and down check B (not covered), **when** their nag email is sent (`sendreports.handle_one_nag` → `Profile.send_report(nag=True)`, `hc/accounts/models.py:281-289`), **then** the email lists B, does not list A, and `num_down` is 1. |
| REQ-4.3 | Must | **Given** a user's `next_nag_date` has passed and every one of their down checks is covered, **when** `handle_one_nag` runs, **then** no email is sent and `next_nag_date` becomes null. This is the existing behaviour for "no down checks" (`sendreports.py:87-89`). |
| REQ-4.4 | Must | **Given** a window in P ends (by time or by End now) while ≥1 check of P is still down and no longer covered, **when** 60 s have passed since the end, **then** every member and the owner of P who has a nag period has `next_nag_date = (instant of recompute) + nag_period`, unless it was already set. |
| REQ-4.5 | Must | **Given** 0 windows exist, **when** `update_next_nag_date` and `send_report(nag=True)` run, **then** their results are identical to today's for the same data. |

### Epic E5 — Show maintenance (brief REQ-5; M5, M6, M7, S2)

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-5.1 | Must | **Given** check C has a withheld flip referencing window "Postgres upgrade", **when** a member views C's log page (`hc-log`) or the events on C's details page, **then** the row for that flip shows the text `Alert not sent: maintenance window "Postgres upgrade"`. |
| REQ-5.2 | Must | **Given** the window referenced by a withheld flip has been deleted or pruned, **when** the log is shown, **then** the row shows `Alert not sent: maintenance window` with no name (A2). |
| REQ-5.3 | Must | **Given** check C is covered now, **when** a member loads `/projects/<P>/checks/` or C's details page, **then** C shows a "Maintenance" label made of the visible text "Maintenance" and an icon. Its accessible name and `title` are `Under maintenance until <end in viewer's tz> (<window name>)`, using the covering window with the latest end. **Given** C is not covered now, including when it is only covered by an upcoming window, **then** no label is shown. **DECISION:** the label is computed when the page loads and is not updated by the `checks/status/` polling. Reason: the compatibility promise keeps that endpoint's JSON unchanged. |
| REQ-5.4 | Must | **Given** P has windows in all three states, **when** a member opens the Maintenance page, **then** it shows three sections in this order: *Active* (sorted by end, earliest first), *Upcoming* (sorted by start, earliest first), and *Ended in the last 90 days* (sorted by end, latest first). Each row shows the name, start, end, the time zone label, the scope ("All checks" or each tag as a tag pill), and "Created by <email>". |
| REQ-5.5 | Must | **Given** a window's `created_by` is null, **when** it is listed, **then** the row shows "Created by deleted user" if `created_via = dashboard`, or "Created via API" if `created_via = api`. |
| REQ-5.6 | Must | **Given** P has no windows, **when** a member opens the Maintenance page, **then** it shows "No maintenance windows yet." Writers also see the Schedule and Start now controls. |
| REQ-5.7 | Should | **Given** the window form is open, **when** the user changes the scope or tags, **then** within 1 s the form shows "Covers N checks right now" and lists up to 20 check names, followed by "and M more" when N > 20, using `GET /projects/<P>/maintenance/preview/`. |
| REQ-5.8 | Should | **Given** the scope matches 0 checks, **when** the preview is shown, **then** the form shows the warning "No checks have all of these tags right now. The window will still apply to checks that get these tags later." Saving is still allowed. |
| REQ-5.9 | Must | **Given** a window name or tag contains `<script>alert(1)</script>`, **when** it is shown on any page, email or log, **then** it appears as escaped text and no script runs. |
| REQ-5.10 | Must | **Given** any window time on the dashboard, **when** it is shown, **then** it is in the viewer's `Profile.tz`, with the time-zone name next to it (for example `22:00 Europe/Riga`). |
| REQ-5.11 | Must | **Given** P has windows that ended more than 90 days ago, **when** the Maintenance page or `GET /api/v3/maintenance/` is requested, or a window is created, for P, **then** those windows are deleted before the response is built (Q6=A). Withheld marks that referenced them keep existing, and their window reference becomes null. |

### Epic E6 — REST API and docs (brief REQ-6; M8, S3, S4, Q4=B, Q7=A)

All endpoints are added to `api_urls` (`hc/api/urls.py:49-71`), so they exist under `/api/v1/`, `/api/v2/` and `/api/v3/` and behave the same under each. Only v3 is documented. Each endpoint has `@csrf_exempt` and `@cors` with the methods listed under *External interfaces*.

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-6.1 | Must | **Given** P has windows, **when** a client calls `GET /api/v3/maintenance/` with P's read-write or read-only key, **then** the response is 200 `{"windows": [<Window JSON>…]}`, holding every window of P (after pruning, REQ-5.11), sorted by `start`, latest first. |
| REQ-6.2 | Must | **Given** P has windows in all states, **when** the client adds `?state=active`, `?state=upcoming` or `?state=ended`, **then** only windows in that state are returned. **When** `state` has any other value, **then** the response is 400 `{"error": "invalid state, expected active, upcoming or ended"}`. |
| REQ-6.3 | Must | **Given** a read-write key, **when** a client POSTs `{"name": "Deploy 42", "duration": 3600}` to `/api/v3/maintenance/`, **then** the response is 201 with the Window JSON, where `start` = now (seconds precision), `end` = start + 3600 s, `scope` = `"all"`, `created_via` = `api` and `created_by` = null. |
| REQ-6.4 | Must | **Given** a read-write key, **when** a client POSTs `start` and `end` as ISO 8601 strings with a UTC offset (for example `"2026-11-07T22:00:00+02:00"`), **then** the window is stored in UTC with microseconds dropped. REQ-1.3 applies to a start in the past. |
| REQ-6.5 | Must | **Given** any create body that breaks a rule under *Validation and errors*, **when** it is POSTed, **then** the response is 400 `{"error": "<message from the table>"}` and nothing is saved. |
| REQ-6.6 | Must | **Given** P has 100 upcoming plus active windows, **when** a client POSTs a valid window, **then** the response is 403 `{"error": "too many upcoming or active maintenance windows (limit 100)"}`. **DECISION:** use 403, matching the existing check-limit response of `create_check` (`hc/api/views.py:448-449`). |
| REQ-6.7 | Must | **Given** window W in P, **when** a client calls `GET /api/v3/maintenance/<W>` with either of P's keys, **then** the response is 200 with W's Window JSON. |
| REQ-6.8 | Must | **Given** an active window W in P, **when** a client POSTs to `/api/v3/maintenance/<W>/end` with P's read-write key, **then** W.end = now, and the response is 200 with the Window JSON, where `state` = `"ended"`. |
| REQ-6.9 | Must | **Given** W is upcoming or ended, **when** a client POSTs to `/api/v3/maintenance/<W>/end`, **then** the response is 409 `{"error": "maintenance window is not active"}` and W is unchanged. **DECISION:** use 409 for state conflicts, following `resume` on a check that is not paused (`hc/api/views.py:579-580`), but with the JSON error body. This adds 409 to the 400/401/403/404 codes listed in brief REQ-6. |
| REQ-6.10 | Must | **Given** an upcoming window W in P, **when** a client sends `DELETE /api/v3/maintenance/<W>` with P's read-write key, **then** W is deleted and the response is 200 with W's Window JSON as it was before deletion (the same pattern as `delete_check`, `hc/api/views.py:521-529`). |
| REQ-6.11 | Must | **Given** W is active or ended, **when** a client sends `DELETE /api/v3/maintenance/<W>`, **then** the response is 409 `{"error": "only upcoming maintenance windows can be deleted"}` and W still exists. |
| REQ-6.12 | Must | **Given** any of the new endpoints, **when** the `X-Api-Key` header (or, for POST, `api_key` in the body) is missing or not 32 characters, **then** the response is 401 `{"error": "missing api key"}`. **When** the key matches no project, **then** it is 401 `{"error": "wrong api key"}`. **When** a read-only key is used on POST or DELETE, **then** it is 401 `{"error": "wrong api key"}`. These are the existing `@authorize` and `@authorize_read` responses. |
| REQ-6.13 | Must | **Given** window W belongs to project Q, **when** a client uses P's key on `/api/v3/maintenance/<W>` (GET, DELETE) or `/end` (POST), **then** the response is 403 and the body contains no W data. **Given** a UUID that matches no window, **then** the response is 404. |
| REQ-6.14 | Must | **Given** any Window JSON response, **when** it is serialised, **then** it contains no creator user, email or user ID. It does contain `created_via`. |
| REQ-6.15 | Should | **Given** check C, **when** a client gets C through `GET /api/vN/checks/`, `GET /api/vN/checks/<uuid>`, `GET /api/vN/checks/<unique_key>`, or the response of create, update, pause, resume or delete, for N in {1, 2, 3}, **then** the check JSON has the key `"maintenance"`. It is `true` when C is covered now and `false` otherwise. All other keys are unchanged (A4). |
| REQ-6.16 | Should | **Given** the docs sources, **when** `manage.py render_docs` is run, **then** `templates/docs/api.md` has a section for each of the 5 new endpoint operations, with Request Parameters, Response Codes, Example Request and Example Response in the style of the existing sections (for example `## Pause Monitoring of a Check`). The `"maintenance"` key appears in the check examples. The new page `templates/docs/maintenance_windows.md` and its `.html-fragment` exist, and `configuring_notifications.md` links to it. |
| REQ-6.17 | Should | **Given** the new endpoints, **when** the OpenAPI contract is produced (Q7=A), **then** it describes only the 5 new operations and the Window JSON schema, and every field and status code in it matches *External interfaces*. |
| REQ-6.18 | Must | **Given** a JSON body that is not an object, or cannot be parsed, **when** it is POSTed to `/api/v3/maintenance/`, **then** the response is 400 with the existing messages `could not parse request body` or `json validation error: value is not an object` (`hc/api/decorators.py:40-45`). |

### Epic E7 — Release and compatibility (brief "Compatibility promises")

| ID | Pri | Requirement (Given / When / Then) |
|---|---|---|
| REQ-7.1 | Must | **Given** the change is merged, **when** `CHANGELOG.md` is read, **then** under `## v4.5-dev - Unreleased` there is one line in the existing bullet format describing maintenance windows, and `settings.VERSION` still parses as `4.5-dev` (`hc/settings.py:85-89`). |
| REQ-7.2 | Must | **Given** the new migrations, **when** `manage.py migrate` runs on SQLite, PostgreSQL, MySQL and MariaDB (the `.github/workflows/tests.yml` matrix), **then** it succeeds. The migrations only add tables, nullable columns or columns with defaults, and indexes. No existing column is renamed, removed or changed. |
| REQ-7.3 | Must | **Given** every existing URL name `hc-…` and API route, **when** they are resolved after the change, **then** they resolve to the same views with the same responses for the same inputs. The only exception is the additive `"maintenance"` key (REQ-6.15). |

---

## Validation and errors

Each rejected input is shown on the dashboard next to the field it names (in the Field column), and returned by the API as `400 {"error": "<API message>"}`. Checks run in the order listed, and only the first failure is reported. Limits use the server instant `now` at validation time.

| # | Field | Rule | Dashboard message | API message |
|---|---|---|---|---|
| V1 | name | Required. 1–100 characters after trimming leading and trailing whitespace. | "Enter a name of 1 to 100 characters." | `json validation error: name is required` / `json validation error: name is too long` / `json validation error: name must not be empty` |
| V2 | start | Dashboard: a valid date plus a valid time in `Profile.tz`. API: optional, an ISO 8601 string **with** an offset or `Z`. Omitted means now. | "Enter a valid start date and time." | `json validation error: start must be an ISO 8601 date-time with a time zone` |
| V3 | start | Not a nonexistent local time (dashboard only, REQ-1.18). | "<time> does not exist in <tz> because of a daylight-saving change. Choose another time." | — |
| V4 | end / duration | Dashboard: end is required, with the same format as V2. API: exactly one of `end` (format as V2) or `duration` (integer seconds, 60–2 592 000). | "Enter a valid end date and time." | `json validation error: provide exactly one of end or duration` / `json validation error: duration must be an integer between 60 and 2592000` |
| V5 | end | `end > start`, using the start after REQ-1.3. | "End must be after start." | `end must be after start` |
| V6 | end | `end > now`. | "End must be in the future." | `end must be in the future` |
| V7 | end | `end − start ≤ 30 days` (2 592 000 s). On an edit of an active window, the original start is used. | "A maintenance window can be at most 30 days long." | `maintenance window can be at most 30 days long` |
| V8 | scope | Dashboard: `all` or `tags`. API: implied by `tags`, where omitted or `""` means all checks. | "Choose a scope." | — |
| V9 | tags | When the scope is `tags`: a string of ≤500 characters containing ≥1 non-space token. It is stored normalised: split on whitespace, duplicates removed, joined with single spaces, in first-seen order. | "Enter at least one tag." / "Tags can be at most 500 characters." | `json validation error: tags is too long` |
| V10 | (window) | At create: upcoming plus active windows of the project < 100. | REQ-1.5 message | REQ-6.6 (403) |
| V11 | API types | `name`, `start`, `end` and `tags` are strings, and `duration` is an integer. Strict Pydantic, so `"3600"` is rejected for `duration`. Unknown keys are ignored, consistent with `Spec` (`hc/api/views.py:61`). | — | `json validation error: <field> is not a string` / `… is not a number` (existing `format_first_error` templates) |

---

## Window lifecycle

The state is derived from `start`, `end` and `now`. It is never stored. "Deleted" and "pruned" mean the row no longer exists.

| From | To | Trigger | Who may trigger |
|---|---|---|---|
| (none) | upcoming | create with start > now | writer, read-write key |
| (none) | active | create with start ≤ now, or start now | writer, read-write key |
| upcoming | upcoming | edit name, start, end or scope | writer (dashboard only) |
| upcoming | active | the time reaches `start` | system |
| upcoming | deleted | Delete | writer, read-write key |
| active | active | edit name, or edit end to a later time or an earlier time still > now | writer (dashboard only) |
| active | ended | the time reaches `end`, or End now | system / writer, read-write key |
| ended | pruned | `end < now − 90 days` and the project's windows are listed or a window is created (REQ-5.11) | system |

Forbidden: deleting an active or ended window (REQ-1.13, REQ-6.11). Any change to an ended window (REQ-1.14, REQ-6.9). Changing the start or scope of an active window (REQ-1.10). Moving an ended window back to active by editing its end.

**Withheld mark lifecycle (down flips only):** `withheld` → `released` (end-of-window pass, REQ-3.1). A down flip stays `withheld` with no release when it is overtaken by a later flip (REQ-3.2), or when its check is paused or deleted (REQ-3.9). Up flips have only the `withheld` state.

---

## Data model

### New entity: MaintenanceWindow

| Field | Type | Required | Allowed values / format | Unique | Notes |
|---|---|---|---|---|---|
| id | auto integer PK | yes | — | yes | Internal only. |
| code | UUID | yes | UUID4, generated at create, not editable | yes | Used in URLs and the API (`uuid` in JSON). |
| project | FK → `accounts.Project` | yes | — | no | `on_delete=CASCADE`: deleting the project deletes its windows. |
| name | string | yes | 1–100 characters, trimmed (V1) | no | Free text. Untrusted and always escaped. |
| start | datetime (UTC, tz-aware) | yes | Seconds precision | no | Inclusive. |
| end | datetime (UTC, tz-aware) | yes | `end > start`, `end − start ≤ 30 d` | no | Exclusive. |
| tags | string | no (default `""`) | ≤500 characters, normalised (V9). `""` means all checks. | no | Matched with `Check.matches_tag_set`. |
| created | datetime (UTC) | yes | default now | no | |
| created_by | FK → `auth.User` | no | — | no | `on_delete=SET_NULL`. Null for API-created windows and after the user is deleted. Personal data, shown only to project members. |
| created_via | string(9) | yes | `dashboard` \| `api` | no | **DECISION:** added so that "deleted user" and "via API" can be told apart when `created_by` is null (REQ-5.5). |

Indexes needed by the queries behind NFR-1: `(project, end)`, for "windows of P not yet ended" and pruning. Exact definitions are the Architect's choice.

### New logical record: withheld mark (per flip)

The change request leaves the physical storage to the Architect: columns on `Flip`, or a new table with a 1:1 link to `Flip`. Either way, it must hold:

| Attribute | Type | Required | Notes |
|---|---|---|---|
| flip | ref → `api.Flip` | yes, at most 1 mark per flip | Deleted with its flip. Flips are pruned by `Check.prune()` after 93 days (`hc/api/models.py:596-603`), and when their check is deleted (CASCADE). |
| withheld | boolean / presence | yes | True when `sendalerts` sent no notification because of REQ-2.1 or REQ-2.6. Default for all existing rows: not withheld. |
| window | ref → MaintenanceWindow | no | `on_delete=SET_NULL`, so it outlives window pruning (REQ-5.2). Null for up flips withheld under REQ-2.6 outside any window. |
| released | datetime (UTC) | no | Down flips only. Set exactly once by the claim of REQ-3.6. |

### Existing entities touched

| Entity | Change |
|---|---|
| `api.Flip` (`hc/api/models.py:1361-1388`) | Possibly gains the withheld mark columns (Architect). `FlipDict` and `Flip.to_dict` are unchanged. |
| `api.Check` (`hc/api/models.py:190+`) | No schema change. `to_dict` gains the computed key `"maintenance": bool` (REQ-6.15). |
| `api.Notification` | No change. End-of-window alerts are ordinary rows with `check_status="down"`. |
| `accounts.Project` | No schema change. Gets a reverse relation to its windows. |
| `accounts.Profile` | No schema change. The logic of `update_next_nag_date` and `send_report(nag=True)` changes (E4). |
| `auth.User` | No schema change. Deleting a user nulls `created_by`. |

### Relationships

| Relationship | Cardinality | On delete |
|---|---|---|
| Project → MaintenanceWindow | 1 : 0..N | Project deleted → its windows deleted |
| User → MaintenanceWindow (`created_by`) | 1 : 0..N | User deleted → `created_by = NULL` |
| MaintenanceWindow ↔ Check | N : M, **computed, not stored** (project and tag rule) | — |
| Flip → withheld mark | 1 : 0..1 | Flip deleted → mark deleted |
| MaintenanceWindow → withheld mark | 1 : 0..N | Window deleted or pruned → `window = NULL` |

---

## External interfaces

Window times in JSON use `isoformat()` with microseconds dropped and a `+00:00` offset, like `Check.to_dict` (`hc/api/models.py:114`).

**Window JSON**

```json
{
  "uuid": "6e2f4c1a-…",
  "name": "Postgres upgrade",
  "start": "2026-11-07T20:00:00+00:00",
  "end": "2026-11-07T21:30:00+00:00",
  "scope": "tags",
  "tags": "db prod",
  "state": "upcoming",
  "created": "2026-11-01T09:12:44+00:00",
  "created_via": "dashboard"
}
```
`scope` is `"all"` when `tags` is `""`, and `"tags"` otherwise. `state` is one of `upcoming|active|ended`, computed at response time.

### REST API (new, under `/api/v1|v2|v3/`)

| Method + path | Auth | Input | Success | Errors |
|---|---|---|---|---|
| `GET maintenance/` | `@authorize_read` | Query `state` (optional: `active`, `upcoming`, `ended`) | 200 `{"windows": [Window…]}` | 400 invalid state · 401 |
| `POST maintenance/` | `@authorize` | JSON `name` (str, required), `start` (str, optional), `end` (str) **xor** `duration` (int), `tags` (str, optional), `api_key` (optional) | 201 Window | 400 (V1–V11) · 401 · 403 limit |
| `GET maintenance/<uuid:code>` | `@authorize_read` | — | 200 Window | 401 · 403 other project · 404 |
| `DELETE maintenance/<uuid:code>` | `@authorize` | — | 200 Window (pre-delete) | 401 · 403 · 404 · 409 not upcoming |
| `POST maintenance/<uuid:code>/end` | `@authorize` | Body optional (`api_key` only) | 200 Window (`state: "ended"`) | 401 · 403 · 404 · 409 not active |

CORS: `maintenance/` has `GET, POST`, `maintenance/<code>` has `GET, DELETE`, and `…/end` has `POST`. An `OPTIONS` request returns 204 and other methods return 405 (`hc/api/decorators.py:96-118`). URL names: `hc-api-maintenance`, `hc-api-maintenance-single`, `hc-api-maintenance-end`.

### REST API (modified)

| Endpoint | Change |
|---|---|
| Every response that contains check JSON (`checks/`, `checks/<uuid>`, `checks/<sha1>`, create, update, pause, resume, delete) | Adds the key `"maintenance": true\|false` (REQ-6.15). Nothing else changes. |

### Dashboard routes (new)

All routes are under `/projects/<uuid:code>/maintenance/`, use `@login_required`, and are protected by CSRF on POST. Writes use `@require_POST` and `_get_rw_project_for_user`. Reads use `_get_project_for_user`. A window code is looked up within the project, and returns 404 when it is not found (REQ-1.17).

| Method + path | Name | Input | Output |
|---|---|---|---|
| GET `` (the list) | `hc-maintenance` | — | 200 HTML Maintenance page (REQ-5.4) |
| POST `add/` | `hc-add-maintenance` | form: `name`, `start_date`, `start_time`, `end_date`, `end_time`, `scope` (`all`\|`tags`), `tags`, **or** for start now: `name`, `duration_minutes` (1–43 200), `scope`, `tags` | 302 to `hc-maintenance` · 200 form with errors · 403 · 404 |
| POST `<uuid:mw_code>/edit/` | `hc-edit-maintenance` | the same fields as scheduled create | 302 · 200 with errors · 400 ended · 403 · 404 |
| POST `<uuid:mw_code>/end/` | `hc-end-maintenance` | — | 302 · 400 not active · 403 · 404 |
| POST `<uuid:mw_code>/remove/` | `hc-remove-maintenance` | — | 302 · 400 not upcoming · 403 · 404 |
| GET `preview/?scope=…&tags=…` | `hc-maintenance-preview` | `scope` (`all`\|`tags`), `tags` (≤500 characters) | 200 JSON `{"count": int, "checks": [{"name": str, "url": str}] (≤20)}` · 400 `{"error": "tags is too long"}` · 404 |

**DECISION:** "Start maintenance" on the details page posts to `hc-add-maintenance`, with the fields pre-filled as in REQ-1.7. No route is added under `/checks/<code>/`. Reason: one create path means one set of validation and permission checks.

### Dashboard pages (modified)

| Page | Change |
|---|---|
| Project navigation (all `/projects/<code>/…` pages) | "Maintenance" link (REQ-1.1) |
| `/projects/<code>/checks/` | "Maintenance" label per covered check (REQ-5.3) |
| `/checks/<code>/details/` | Label (REQ-5.3), "Start maintenance" control for writers (REQ-1.7), withheld text in events (REQ-5.1) |
| `/checks/<code>/log/` and `log_events/` | Withheld text on flip rows (REQ-5.1, REQ-5.2) |
| `/docs/maintenance_windows/` (new), `/docs/api/`, `/docs/configuring_notifications/` | REQ-6.16 |

### Management commands (modified)

| Command | Change |
|---|---|
| `sendalerts` | The flip processing decides whether to withhold (E2). The end-of-window pass runs at least every 30 s (E3). New stdout lines (REQ-2.13, REQ-3.12). New statsd counters `hc.sendalerts.withheld` and `hc.sendalerts.endOfWindow`. No new arguments. |
| `sendreports` | Nags leave out covered checks (E4). No new arguments. |
| `render_docs` | No change. It is run to regenerate the fragments. |

No new management command is added (Q6=A). No events or webhooks are added (W4).

---

## Non-functional requirements

| ID | Category | Requirement | How verified |
|---|---|---|---|
| NFR-1.1 | Performance | With 0, 1 and 50 windows and 500 checks in a project, `/projects/<code>/checks/` and `GET /api/v3/checks/` use ≤ (baseline + 2) SQL queries, where the baseline is the count with no feature code. | `assertNumQueries` tests |
| NFR-1.2 | Performance | Processing one flip in `sendalerts` adds ≤1 SQL query to decide withhold or deliver, plus ≤1 write to store the mark when the flip is withheld. | `assertNumQueries` around `process_one_flip` + `notify` |
| NFR-1.3 | Performance | When 0 unreleased withheld flips exist, the end-of-window pass costs ≤1 SQL query per run, and it runs at most once every 10 s, so it adds ≤0.1 query/s to the 2 s idle loop (`sendalerts.py:213`). | Unit test with a mocked clock |
| NFR-1.4 | Performance | `GET /projects/<code>/maintenance/` and `GET /api/v3/maintenance/` return in <200 ms server time with 100 active+upcoming and 1 000 ended windows in the project, on SQLite in the CI runner. | Timed test (soft gate, logged) |
| NFR-1.5 | Performance | `Profile.update_next_nag_date` adds ≤1 SQL query compared with today. | `assertNumQueries` |
| NFR-2.1 | Reliability | Withhold or deliver depends only on windows as stored when `sendalerts` evaluates the flip, tested at `flip.created`. Processing the same flip 0 s or 1 h after creation gives the same result, given no window edits in between that move `end` before `flip.created`. Such edits are impossible, because a new end must be > now (V6). | REQ-2.11 test |
| NFR-2.2 | Reliability | End-of-window alerts are sent at least once and at most once per (released flip, channel), with 1 or 2 `sendalerts` processes. A crash after the claim and before the transport call loses at most that one alert. That is the same guarantee as flip processing today (`processed` is set before `notify`, `sendalerts.py:110-120`). | REQ-3.6 test |
| NFR-2.3 | Reliability | An exception raised while evaluating coverage for a flip is logged with `logger.exception` and the flip is **delivered** as today. Coverage logic fails open, so a fault never silences alerts for projects without windows (R1). | Test that injects an exception |
| NFR-3.1 | Security | Every new dashboard view and API endpoint has a test for each denial in *Users and permissions*. | Test suite |
| NFR-3.2 | Security | Dashboard input goes through Django forms, and API input through a Pydantic model with `model_validate(strict=True)`. No raw SQL. | Code review, V-table tests |
| NFR-3.3 | Security | Names and tags are rendered only through auto-escaping templates. The test of REQ-5.9 covers the page, the log, the preview JSON (consumed as text) and the nag email. | Test |
| NFR-4.1 | Accessibility | The Maintenance page, the forms, the modals and the labels meet WCAG 2.2 AA. Every input has a `<label>`. Errors are linked with `aria-describedby`. Modals trap focus and return it to the opener. Everything can be done by keyboard alone. | Manual audit checklist at the gate. axe-core has 0 serious or critical issues. |
| NFR-4.2 | Accessibility | The "Maintenance" label has contrast ≥4.5:1 against its background in the light and dark themes, and has a text label (not colour only). | Contrast measurement of CSS values |
| NFR-5.1 | Observability | Statsd counters `hc.sendalerts.withheld` (+1 per withheld flip) and `hc.sendalerts.endOfWindow` (+1 per released check). | Test with mocked `statsd` |
| NFR-5.2 | Observability | One stdout line per withheld flip and per released check, in the formats of REQ-2.13 and REQ-3.12. | Test capturing stdout |
| NFR-6.1 | Capacity | ≤100 upcoming+active windows per project (V10). No limit on ended windows within the 90 days. | REQ-1.5, REQ-6.6 |
| NFR-6.2 | Capacity | Window length ≤30 days (V7). | V7 tests |
| NFR-7.1 | Availability | Not applicable as a new target. The feature inherits the availability of the web app and `sendalerts`. Its only availability promise is REQ-3.5 (alerts sent once `sendalerts` comes back). | — |
| NFR-8.1 | Privacy | Creator email is shown only to members of the window's project, and never in the API (REQ-6.14). | Tests |
| NFR-8.2 | Retention | Ended windows are deleted 90 days after `end` by inline pruning (REQ-5.11). Withheld marks live as long as their flip (≤93 days after the flip is pruned by `Check.prune`). | Test with `time-machine` at 90 d ± 1 s |
| NFR-8.3 | Privacy | Deleting a user sets `created_by` to null and leaves the window working (REQ-5.5). | Test |
| NFR-9.1 | Maintainability | `mypy --strict hc` adds 0 errors. All new modules start with `from __future__ import annotations` and are fully annotated. | CI |
| NFR-9.2 | Maintainability | `makemigrations --check --dry-run` prints "No changes detected" after the new migrations. The full suite passes on the 4 CI databases. | CI |
| NFR-9.3 | Maintainability | New tests are `BaseTestCase` subclasses in `test_<feature>.py` files, with `test_it_<behaviour>` methods and `time-machine` for time (`hc/test.py`). | Review |
| NFR-10.1 | Usability | From the details page, a writer can start a 1-hour window scoped to that check's tags in ≤3 interactions: open, pick "1 h", confirm. | Manual check at the gate |
| NFR-11.1 | Compatibility | Works in the browsers and widths the existing dashboard supports. No new JS dependency. jQuery and Bootstrap 3 are already vendored (`static/`). The page is usable at 360 px width without horizontal scrolling. | Manual check at 360 px and 1280 px |
| NFR-11.2 | Compatibility | API v1, v2 and v3 behave the same for the new endpoints (REQ-6 intro). Existing JSON shapes are unchanged except for REQ-6.15. | Tests that run each new endpoint on all 3 prefixes |
| NFR-12.1 | Auditability | For every withheld flip, the event log shows which window withheld it (REQ-5.1). For every window, the Maintenance page shows who created it, and when, for 90 days. Edits, End now and deletes are **not** recorded in a separate audit trail. **DECISION:** no edit history. Reason: the repo has no audit-log facility to extend, and the event log already records the effect on each check. | Tests of REQ-5.1 and REQ-5.4 |

---

## Decisions

Decisions made in this PRD. Each one can be overruled at the gate.

| ID | Decision | Rejected alternative (why it lost) |
|---|---|---|
| DECISION-1 (REQ-1.3) | A start in the past becomes now. | Reject the past start: a form that takes a minute to fill in would always fail. Apply it retroactively: flips already processed cannot be withheld. |
| DECISION-2 (REQ-1.10) | An active window can change only its name and end. | Allow scope changes while active: they make coverage for flips already processed hard to explain. |
| DECISION-3 (REQ-1.18) | An ambiguous DST time uses the first occurrence, and a nonexistent time is rejected. | Reject ambiguous times as well: it adds friction once a year for no safety gain. |
| DECISION-4 (REQ-1.19) | No uniqueness rule, and duplicate submissions create two windows. | Unique names: legitimate repeats such as "Weekly patching" would be blocked. |
| DECISION-5 (REQ-2.6) | An up flip whose down flip was withheld and not released is withheld, even outside a window. | Send it: on-call people would get an "up" alert for a "down" they never received. |
| DECISION-6 (REQ-3.7) | Release is decided by "not covered now", not by "a window ended". | Release only when a window ends: a check that loses its tag mid-window would stay silent. |
| DECISION-7 (REQ-5.3) | The label is computed at page load only. | Add it to `checks/status/` polling: it changes a JSON shape promised to stay unchanged. |
| DECISION-8 (REQ-6.6) | 403 for the 100-window limit. | 400: inconsistent with the existing check-limit response. |
| DECISION-9 (REQ-6.9, REQ-6.11) | 409 with a JSON body for state conflicts. | 400: hides the difference between bad input and wrong state, and the repo already uses 409 for this (`resume`). |
| DECISION-10 (data) | Add `created_via` to the window. | Infer from `created_by IS NULL`: "deleted user" and "API" cannot be told apart. |
| DECISION-11 (interfaces) | The API has no edit endpoint. The API supports create, list, view, end and delete. | Add `POST maintenance/<uuid>` to edit: not asked for in M8 or Q4=B, and deploy scripts can delete and recreate an upcoming window. |
| DECISION-12 (interfaces) | API create takes `end` **or** `duration`. | `end` only: every deploy script would have to compute timestamps. |
| DECISION-13 (interfaces) | Dashboard window routes are nested under `/projects/<code>/maintenance/`. | Top-level `/maintenance/<uuid>/`, like `/integrations/<uuid>/`: nesting gives the project check and the 404 of REQ-1.17 directly. |
| DECISION-14 (NFR-2.3) | Coverage evaluation fails open, so the alert is delivered. | Fail closed: a bug would silence real alerts for everyone (R1). |
| DECISION-15 (NFR-12.1) | No audit history of window edits. | Add an edit history: there is no existing audit facility to extend, and the event log already records the effect on each check. |

---

## Assumptions

- AS-1. The 100-window limit (V10) is checked with a count before insert, with no lock. Two simultaneous creates at 99 can produce 101. This is accepted because the limit guards against mistakes, not against abuse.
- AS-2. The end-of-window pass running every ≤30 s inside `sendalerts` is enough to meet "within 60 s" (REQ-3.1). The exact interval is the Architect's choice within 10–30 s (NFR-1.3).
- AS-3. A check that is transferred to another project (`hc/front/views.py:1062-1068`) is covered by the windows of the project it belongs to when each flip is processed.
- AS-4. Up to ~2 s between a status change and its processing is normal (`sendalerts.py:213`). Tag or project changes made in that gap affect coverage (vocabulary: "covers").
- AS-5. Monthly and weekly reports are unchanged and still list checks that are down during maintenance (brief A6). Only nags change.
- AS-6. Flapping notices are unaffected, and flips during maintenance count towards them (brief A5).
- AS-7. `"maintenance"` is added to check JSON for v1, v2 and v3 alike (brief A4).
- AS-8. Window names are not secret and are visible to every project member, including read-only members (brief A10).
- AS-9. At least one `sendalerts` process is deployed (brief A9).
- AS-10. Teams that want a window narrower than the whole project tag their checks (brief A8).
- AS-11. The recompute of nag dates for the members of P after a write (REQ-1.20) is cheap enough to run inside the request. Projects have tens of members, not thousands.
- AS-12. Not verified: whether `Spec`-style models ignore unknown keys because of a project-wide `model_config`. V11 assumes they are ignored, matching the existing check endpoints that accept `api_key` in the body.
