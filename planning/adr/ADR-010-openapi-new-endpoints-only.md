# ADR-010: First OpenAPI document, scoped to the new endpoints

Status: Accepted
Date: 2026-10-17

## Context
The repository has no machine-readable API description. The REST API is documented by hand in `templates/docs/api.md` (`.forge/repo-map.json` `api_spec: null`). The pipeline requires an OpenAPI 3.1 contract for a change with an HTTP interface. The operator decided Q7=A: the contract covers only the new maintenance-window endpoints (REQ-6.17).

## Options
1. **`planning/api/openapi.yaml` covering the 5 new operations and the Window JSON schema**, plus the additive `"maintenance"` property on the check schema, marked `x-change: added` / `x-change: changed`. It is a planning and testing artifact and is not served by the app. Buys: a precise contract for the new surface, at small cost. Costs: two descriptions of the new endpoints (YAML and `api.md`) that must agree.
2. **Describe the whole existing API.** Buys: completeness. Costs: a large retrofit unrelated to the requirement, and a higher risk of the YAML and `api.md` disagreeing. Rejected by Q7=A.
3. **No OpenAPI, only `api.md`.** Buys: one source. Costs: the pipeline gate is not met.

## Decision
Option 1: write a planning-only OpenAPI 3.1 document for the new endpoints and the one changed check field. `api.md` stays the public documentation.

## Consequences
- The document is written in the LLD phase, with exact field types and status codes (OQ-2).
- Nothing is added to the runtime. No schema-generation library is added (C-4).

## Validation
Every status code and field in `openapi.yaml` appears in the PRD's *External interfaces* and in the API tests. A reviewer checks the YAML against `api.md` at the LLD gate.
