# ADR-008: End-of-window pass inside the sendalerts loop, gated by one query

Status: Accepted
Date: 2026-10-17

## Context
REQ-3 requires one down alert within 60 s once a check with a withheld, pending down flip is no longer covered. Eligibility is "not covered now" (DECISION-6), so End now, a shortened end, tag removal and project transfer all release. The alert must still go out if `sendalerts` was down at the end time (REQ-3.5), and never twice with two workers (REQ-3.6). REQ-4.4 also requires a nag recompute for the project within 60 s of any window end, even when no flip was withheld (for example, a check that went down before the window). When idle, the pass may cost ≤1 query (REQ-3.13, NFR-1.3). No new management command may be added (C-5). The existing loop has `handle_going_down`, driven by `Check.alert_after`, and `process_one_flip`, driven by `processed IS NULL` (`sendalerts.py:201-213`). Neither fits a condition that changes with window edits and tag edits.

## Options
1. **A periodic pass in the existing loop, at most every 15 s, starting with one gate query** ("any pending withheld down flips, or any ended window whose end is not yet handled?"). It then claims each ended window (conditional UPDATE on a nullable "end handled" timestamp) and recomputes nags for its project, and settles or releases each pending flip through conditional UPDATEs, sending releases through the unchanged `notify`. Buys: one rule for every release cause, catch-up after downtime for free, the existing claim discipline, no new process. Costs: one new trigger kind in the loop, and one internal column on the window table.
2. **Hook every cause** (End now, edit, tag edit, transfer, plus a timer for natural ends). Buys: immediate release. Costs: logic spread over many views, and natural ends still need a timer.
3. **A denormalised "release after" timestamp on `Check`**, polled like `alert_after`. Buys: reuses the `alert_after` pattern. Costs: it would have to be kept in sync with every window and tag edit, and it is a schema change on `api_check` for all users.
4. **A new management command.** Rejected by Q6=A and C-5.

## Decision
Option 1: one end-of-window pass inside the `sendalerts` main loop, run at most every 15 seconds and gated by a single query.

## Consequences
- Worst case from end to submit is about 15 s for the interval, 2 s of sleep and processing time. This is well inside 60 s.
- Idle cost ≤1 query per 15 s, about 0.07 queries/s (QS-6).
- Pending flips whose checks recovered or were paused are settled as *superseded*, so the pending set stays near zero and the gate stays cheap.
- While windows are active and covering down checks, the gate is true, and each pass costs a few extra queries. This is accepted, because NFR-1.3 constrains only the idle case.

## Validation
- `time-machine` tests: release at the end, not at the end of an overlapped window (REQ-3.3), after End now, after tag removal, after a simulated restart.
- Pre-claimed release → 0 sends. `assertNumQueries(1)` for an idle pass. Nag dates set after a window ends with a check that went down before the window (REQ-4.4).
