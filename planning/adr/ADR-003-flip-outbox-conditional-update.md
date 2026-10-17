# ADR-003: Flip rows as the alert outbox, claimed by conditional UPDATE (retroactive)

Status: Accepted
Date: 2026-10-17 (recorded retroactively. The decision predates this change, and the reason was not recorded)

## Context
A status change inserts a `Flip` row (`Check.ping`, `handle_going_down`, pause/resume). `sendalerts` selects the first row with `processed IS NULL`, claims it with `Flip.objects.filter(id=…, processed=None).update(processed=now())`, and only then hands it to `notify()` in a thread pool (`hc/api/management/commands/sendalerts.py:105-121`). It goes on only when exactly one row was updated. The same conditional-UPDATE-and-rowcount claim guards status changes (`sendalerts.py:164-168`) and nag sends (`hc/api/management/commands/sendreports.py:78-82`). Pause and resume insert flips that are already processed (`mark_as_processed=True`, `hc/api/views.py:557`, `:582`), so no alert is sent for them. The result is a database outbox with **at-most-once** delivery: a crash after the claim and before `notify` loses that one alert, and several workers can never send it twice. The maintenance-window feature adds a second producer of alerts, the end-of-window release (REQ-3.6, NFR-2.2, R2).

## Options
1. **Keep the outbox and the conditional-UPDATE claim for every new claim** (withheld marks, releases, ended windows). Buys: the same delivery guarantee and the same failure modes as today, already proven with several `sendalerts` processes. Costs: at-most-once, not exactly-once.
2. **Row locks (`select_for_update`) or advisory locks.** Buys: stronger exclusion. Costs: these are new in this repo, behave differently across SQLite, PostgreSQL and MySQL, and hold transactions open around network sends.

## Decision
Keep the Flip-outbox design. Every new cross-worker state change in this feature is claimed with a conditional UPDATE whose row count is checked.

## Consequences
- End-of-window alerts have exactly the guarantee of normal alerts (NFR-2.2).
- No locking primitive differs between the four engines.
- Accepted: a crash between a claim and the send loses that alert, as it does today.

## Validation
A test pre-claims a release (it simulates the second worker by running the conditional UPDATE first) and asserts that the pass then creates 0 `Notification` rows. A second test asserts exactly 1 row per channel when the claim succeeds (REQ-3.6).
