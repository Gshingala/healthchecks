# ADR-007: Make the withhold decision in the sendalerts main loop, write it with the claim, and fail open

Status: Accepted
Date: 2026-10-17

## Context
Rules REQ-2.1–2.7 and 2.10 decide per flip whether to send or withhold. REQ-2.6 makes an up flip's decision depend on the mark of the earlier down flip. Today `process_one_flip` selects the first unprocessed flip (`.first()` orders by pk), claims it in the main thread, and submits `notify(flip)` to a thread pool (`sendalerts.py:91-121`). `notify` recomputes nag dates and calls `Flip.select_channels` (`sendalerts.py:24-55`). Both are on the path of every alert (R1). NFR-1.2 allows ≤1 extra read per flip. NFR-2.3 requires the feature to fail open.

## Options
1. **Decide in the main loop before the claim, and write the mark in the claim's conditional UPDATE.** Buys: decisions are sequential in id order within a process, so REQ-2.6 always sees the earlier down flip's mark (AH-1). A flip is never claimed without its mark. `notify` and `select_channels` stay unchanged. Costs: 1 read in the main loop per flip, including a read wasted when another worker wins the claim.
2. **Decide inside `notify`, in the executor thread.** Buys: no work in the main thread. Costs: with `--num-workers` >1, a down flip and its up flip can run in parallel threads and break REQ-2.6. It changes `notify`, which every transport test drives.
3. **Decide inside `Flip.select_channels`** by returning no channels. Buys: a tiny diff. Costs: `select_channels` cannot write marks, and "no channels" would hide the difference between withheld and no channels at all. It changes a hotspot method for everyone.
4. **Decide when the flip is created** (`Check.ping`, `handle_going_down`). Buys: the decision is next to the event. Costs: it puts window logic on the ping path, and there are several producers to change.

## Decision
Option 1: decide in `process_one_flip` before the claim, write `processed` and the withheld mark in the same conditional UPDATE, and deliver through the unchanged `notify` whenever the decision is "deliver" or raises an exception.

## Consequences
- With 0 windows, a down flip costs one indexed read that finds nothing. Up flips cost one read of the earlier down flip. The deliver path is otherwise identical, with no new statsd call (QS-1, `test_sendalerts.py:78`).
- A withheld flip still triggers the nag recompute through the executor, because its status changed.
- Across two processes a small race remains (RK-6), and it is accepted.

## Validation
- The existing `test_sendalerts.py` and `test_notify.py` pass unchanged.
- New tests: covered down flip → 0 `Notification` rows and a mark set. Up after an unreleased withheld down → withheld. An exception injected into the coverage method → delivered and logged (NFR-2.3). `assertNumQueries` on `process_one_flip` with 0 windows.
