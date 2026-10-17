# ADR-009: Compute coverage at read time and batch it for lists

Status: Accepted
Date: 2026-10-17

## Context
"Window W covers check C at t" depends on C's current project and tags (`Check.matches_tag_set`, `hc/api/models.py:416-417`) and on W's interval and tags. Coverage is read in four places: `sendalerts` (at `flip.created`), nags (now), the checks list and details page labels (now, REQ-5.3), and check JSON (now, REQ-6.15). NFR-1.1 allows ≤2 extra queries on the list endpoints. The existing `assertNumQueries(3)` on `GET /api/v1/checks/` (`hc/api/tests/test_list_checks.py:47`) should keep passing for projects without windows (brief success measure 3). `Check.to_dict` already avoids per-check queries by building URLs by hand (`hc/api/models.py:463-480`).

## Options
1. **Compute at read time.** Lists annotate the existing checks query with an EXISTS subquery ("this check's project has an active window"), then fetch the active windows in one extra query only when some row is flagged, and match tags in Python. Single-check reads do one small query. `to_dict` accepts a precomputed value. Buys: no extra query when the project has no active window, nothing to keep in sync, and correct results right after tag edits and transfers. Costs: in-Python tag matching per check, which is cheap because there are at most 100 windows per project.
2. **Store a window↔check join table.** Buys: simple reads. Costs: must be rebuilt on every tag edit, check creation, transfer and window edit. It is a large new sync burden and a source of wrong alerts.
3. **Compute per check inside `to_dict`.** Buys: simplest code. Costs: N queries per list (R5).

## Decision
Option 1: coverage is computed at read time from windows and check attributes, and list views batch it with an EXISTS annotation and at most one window fetch.

## Consequences
- With 0 active windows, list query counts are unchanged.
- Single-check API responses (get, create, update, pause, resume, delete) cost one more query. No existing test pins those counts. Characterization test 3 records the baseline first.
- The label is not live-updated by `checks/status/` polling (DECISION-7).

## Validation
`assertNumQueries` on `/projects/<code>/checks/` and `GET /api/v3/checks/` with 0, 1 and 50 windows and 500 checks: baseline with 0 active windows, baseline + 1 otherwise (NFR-1.1).
