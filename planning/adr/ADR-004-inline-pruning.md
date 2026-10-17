# ADR-004: Prune old rows inline on normal traffic, not in scheduled jobs (retroactive)

Status: Accepted
Date: 2026-10-17 (recorded retroactively. The decision predates this change, and the reason was not recorded. The 2026-10-16 revert is evidence only)

## Context
Database retention in this repository runs inline. `Check.prune()` runs on every 100th ping and deletes old pings, notifications, and flips older than 93 days (`hc/api/models.py:571-603`). No management command prunes database rows by age. `pruneobjects` only removes S3 objects (`hc/api/management/commands/pruneobjects.py:14-43`). The most recent attempt at age-based deletion, in `sendlogs`, was reverted on 2026-10-16 (commit `9b9e6f96`). Self-hosters run a fixed set of processes. Maintenance windows must be kept for 90 days after they end (REQ-5.11, NFR-8.2). The decision for this feature was taken as Q6=A in the decisions log.

## Options
1. **Inline pruning per project** when its windows are listed or created (existing pattern). Buys: no new job for self-hosters, consistent with `Check.prune`. Costs: windows of projects nobody visits stay until the next visit, so retention is "at least 90 days" in storage terms. They are never shown after 90 days, because every read path prunes first.
2. **A new management command.** Buys: exact retention. Costs: one more job to schedule, plus docs and Docker changes. That cuts against the revert above.

## Decision
Keep inline pruning. Ended windows older than 90 days are deleted for a project whenever that project's windows are listed (dashboard or API) or a window is created.

## Consequences
- No operational change for self-hosters.
- The table can hold stale rows for projects that are never visited. They are bounded by the 100 upcoming+active limit per project and by the fact that each window must be created by a visit.

## Validation
A `time-machine` test at `end + 90 d − 1 s` keeps the window and at `end + 90 d + 1 s` deletes it on the next list or create (NFR-8.2).
