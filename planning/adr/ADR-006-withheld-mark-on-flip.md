# ADR-006: Store the withheld mark as nullable columns on Flip, with the window referenced by code and no FK

Status: Accepted
Date: 2026-10-17

## Context
For each flip that `sendalerts` withholds, the system must record that it was withheld, which window withheld it (shown in the event log, REQ-5.1 and REQ-5.2), and, for down flips, whether the alert was later released (REQ-3). The PRD leaves the physical form to the Architect (PRD "New logical record: withheld mark"). Forces:
- `Check.prune()` deletes old flips with `self.flip_set.filter(created__lt=…).delete()` on every 100th ping (`hc/api/models.py:596-603`). `Flip` has no reverse foreign keys today, so Django can run this as a single fast DELETE. **Any table with an FK to `Flip` (CASCADE or SET_NULL) makes Django collect the flips into memory and delete or update the related rows first.** That would slow a hot path for every user (R1, RK-4).
- An FK from `Flip` to the window table would need an index on `api_flip` for SET_NULL, and window deletes would update `api_flip`.
- The end-of-window pass needs a cheap "any pending withheld down flips?" query (QS-6).
- Migrations must be additive and portable to four engines (REQ-7.2).

## Options
1. **Nullable columns on `Flip` (withheld time, withheld window code as a UUID with no FK, a released/superseded settle record) plus one partial index on pending withheld down flips.** Buys: `Check.prune` stays a fast delete. The decision and the claim can write the mark in the same UPDATE (ADR-007). The event log reads it with no join. A dangling window code naturally shows "maintenance window" without a name after pruning (REQ-5.2). Costs: three columns on a large table. The window reference is not enforced by the database. The partial index is not created on MySQL/MariaDB.
2. **A separate `FlipWithhold` table with a 1:1 FK to `Flip`.** Buys: no change to `api_flip`. Costs: the prune turns into collect-then-delete on every 100th ping for every user. The mark needs a second write that is not atomic with the claim.
3. **Columns on `Flip` with a real FK to `MaintenanceWindow` (SET_NULL).** Buys: referential integrity, which matches the PRD wording "window reference becomes null". Costs: a new FK index on `api_flip`, an UPDATE of `api_flip` on every window prune, and the SQLite migration path for adding an FK column is unverified (AH-3).

## Decision
Option 1: store the mark as three nullable, default-less columns on `Flip`, with the window referenced by its UUID code and no FK, and add one partial index for pending withheld down flips.

## Consequences
- `FlipDict` and `Flip.to_dict` are unchanged. The API `/flips/` shape is frozen (C-6).
- REQ-5.11's "window reference becomes null" is met in behaviour, not in storage: the code stays and resolves to no window. This is raised as OQ-1 for the gate.
- On MySQL/MariaDB the pending query scans `api_flip` without the partial index. That is the same limit that `api_flip_not_processed` has today (AH-2).
- The PostgreSQL index build holds a write lock for one scan of `api_flip` (RK-10).

## Validation
- A characterization test pins `Check.prune()`'s flip deletion as a single DELETE with `assertNumQueries` (HLD testing strategy, item 4).
- `sqlmigrate` output for the column migration shows `ADD COLUMN` on SQLite and PostgreSQL, with no table rebuild.
- A REQ-5.2 test deletes the window and asserts the log text without a name.
