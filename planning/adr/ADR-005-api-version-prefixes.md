# ADR-005: One REST view set under /api/v1, /v2 and /v3 prefixes (retroactive)

Status: Accepted
Date: 2026-10-17 (recorded retroactively. The decision predates this change, and the reason was not recorded)

## Context
`hc/api/urls.py:48-81` defines one `api_urls` list and mounts it three times, under `api/v1/`, `api/v2/` and `api/v3/`. The version is read from the path (`hc/api/decorators.py:25-30`) and set as `request.v`. Version differences live only inside serialisers, for example `Check.to_dict(v=…)` (`hc/api/models.py:439-491`). Only v3 is documented in `templates/docs/api.md`. Request validation uses Pydantic v2 models with `strict=True` (`hc/api/views.py:61`). Errors are `{"error": "..."}` from `error(msg, status)`. The new maintenance endpoints (REQ-6) and the new `"maintenance"` key in check JSON (REQ-6.15) must fit this.

## Options
1. **Add the new routes to the shared `api_urls`**, so they exist under all three prefixes and behave identically. Add `"maintenance"` for every `v` (A4). Buys: consistency, and no version logic. Costs: v1 and v2 gain endpoints that are not documented.
2. **Register the new routes under v3 only.** Buys: no undocumented endpoints. Costs: a second routing pattern, and `api_urls` would no longer be the single list.

## Decision
Keep the existing versioning approach. The new endpoints go into `api_urls`, and the additive key is version-independent.

## Consequences
- Every new endpoint is tested on all three prefixes (NFR-11.2).
- Clients that reject unknown keys see `"maintenance"` on every version. This is named in the CHANGELOG line.

## Validation
Endpoint tests are parameterised over `v ∈ {1, 2, 3}` and assert identical status codes and bodies.
