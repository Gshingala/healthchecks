# ADR-001: Keep the Django modular monolith. Maintenance windows join hc/api and hc/front

Status: Accepted
Date: 2026-10-17

## Context
Healthchecks is one Django project. Its apps are split by concern: `hc/accounts`, `hc/api` (core domain models, REST API, `sendalerts`/`sendreports` workers), `hc/front` (every dashboard view, no models), `hc/logs`, `hc/payments`, and 30 `hc/integrations/<kind>` transport apps (`hc/settings.py:93-135`, `hc/urls.py:16-51`). Asynchronous work goes through database rows and long-running management commands. There is no broker and no second service. Maintenance windows (REQ-1…REQ-6) change a decision inside the existing alert pipeline (`sendalerts` → `notify` → `Flip.select_channels`). They also add a project-scoped dashboard page and REST endpoints. QS-1 (no regression without windows) and R7 (upstream drift) pull in different directions.

## Options
1. **Place the feature in the existing apps.** `MaintenanceWindow` goes in `hc/api/models.py`, the API views in `hc/api/views.py` + `api_urls`, the dashboard views in `hc/front/views.py`/`forms.py`/`urls.py`, and the alert logic in `sendalerts`. Buys: the feature looks as if it had always been there, uses the private access helpers in place, keeps one URL list per surface, and needs no new app wiring. Costs: it grows three upstream hotspots (`hc/api/models.py` 1586 lines, `hc/front/views.py` 1434 lines, `sendalerts.py`) and so causes more merge conflicts.
2. **New `hc/maintenance` Django app** with its own models, views, urls, templates and tests, hooking into `sendalerts`, `Check.to_dict` and `Profile`. Buys: fewer conflicts, and the feature is in one place. Costs: a second way of placing core domain code. Standalone apps here are transports or infrastructure, never core alerting entities. It still has to edit the same hotspots for the hooks.
3. **A separate service** (for example a scheduler that pauses checks). Buys: isolation. Costs: a new deployable, a second delivery path, and a change to how self-hosters run the product. It also contradicts W6 (pause semantics are not what is wanted).

## Decision
Option 1: keep the modular-monolith style and put every part of the feature in the existing app that already owns that kind of code.

## Consequences
- Easier: reviewers find each piece where its siblings live. No new `INSTALLED_APPS` entry, URL include or migration app. Deployment and local run are unchanged.
- Harder: upstream merges touch the same files. This is mitigated by adding new code in contiguous blocks (RK-9).
- Accepted risk: hotspot files grow by a few hundred lines.

## Validation
- `git diff --stat` shows no new top-level app directory and no change to `hc/urls.py` or `INSTALLED_APPS`.
- `manage.py check`, the full test suite, and `makemigrations --check --dry-run` pass.
