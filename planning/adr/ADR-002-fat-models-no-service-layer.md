# ADR-002: Domain logic on models and managers, no service layer (retroactive)

Status: Accepted
Date: 2026-10-17 (recorded retroactively. The decision predates this change, and the reason was not recorded)

## Context
Throughout the repository, domain behaviour is written as methods on Django models and custom managers: `Check.get_status`, `Check.going_down_after`, `Check.ping`, `Check.prune` (`hc/api/models.py`), `Flip.select_channels` (`hc/api/models.py:1390-1408`), `Channel.notify`, `Profile.update_next_nag_date`, `Project.update_next_nag_dates` (`hc/accounts/models.py:350-357`, `:488-499`), and `ProfileManager.for_user` and `ProjectManager.for_api_key` (`hc/accounts/models.py:61`, `:397`). Views and management commands call these directly. There is no `services/` module or repository layer (`.forge/repo-map.json` `patterns_observed`). The maintenance-window feature needs a home for its rules: state, coverage, the limits shared by the dashboard and the API, JSON, and pruning.

## Options
1. **Fat models (existing).** Buys: one obvious place for each rule, consistent with the code around it, and easy to test through `BaseTestCase`. Costs: large model files.
2. **Introduce a service module for maintenance logic.** Buys: smaller model files and a clear seam. Costs: a second, inconsistent pattern that only this feature uses.

## Decision
Keep the existing fat-model pattern. The maintenance-window rules are methods on `MaintenanceWindow` and its custom manager, and the changes to nag behaviour are made on `Profile`.

## Consequences
- The dashboard and the API share one model-level validator for V5–V7 and V10, so they cannot drift apart (R6).
- `hc/api/models.py` grows further (RK-9).

## Validation
- No new `services`, `repositories` or similar module appears in the diff.
- The rules of V5–V7 and V10 are implemented once and tested through both the form and the API tests.
