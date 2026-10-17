# Decisions log

Every open question raised while planning, the options offered, the recommendation, and what was decided -- by the operator, or by the recommendation standing when no answer came.

## brownfield build 20261017-125034-e0fb / brainstorm -- 2026-10-17 13:00

| # | Question | Decision | Recommended | Decided by |
|---|---|---|---|---|
| Q1 | Which checks can a maintenance window cover? | B: All checks, or checks matching all given tags | B: All checks, or checks matching all given tags | operator (accepted the recommendation) |
| Q2 | Should windows be one-off only, or also recurring (e.g. every Sunday 02:00–03:00)? | A: One-off only (plus a 'start now for N hours' button and the API) | A: One-off only (plus a 'start now for N hours' button and the API) | operator (accepted the recommendation) |
| Q3 | When a window ends and a covered check is still down (its alert was withheld), what happens? | A: Send one down alert at window end | A: Send one down alert at window end | operator (accepted the recommendation) |
| Q4 | Should windows be manageable through the REST API as well as the dashboard? | B: Dashboard and REST API (list, create, view, end early, delete) | B: Dashboard and REST API (list, create, view, end early, delete) | operator (accepted the recommendation) |
| Q5 | Should outages during a maintenance window still count in downtime statistics and monthly/weekly reports? | A: Yes, keep counting them as today | A: Yes, keep counting them as today | operator (accepted the recommendation) |

## brownfield build 20261017-125034-e0fb / analyst -- 2026-10-17 13:04

| # | Question | Decision | Recommended | Decided by |
|---|---|---|---|---|
| Q6 | How are ended maintenance windows deleted after 90 days? The change request names `manage.py pruneobjects`, but that command only deletes S3 ping bodies (hc/api/management/commands/pruneobjects.py:14-43), and no job prunes database rows by age. | A: Prune inline, per project, when its windows are listed or created | A: Prune inline, per project, when its windows are listed or created | operator (accepted the recommendation) |
| Q7 | What should the OpenAPI contract cover, given that the repo has none and documents its API by hand in templates/docs/api.md? | A: Only the new maintenance-window endpoints | A: Only the new maintenance-window endpoints | operator (accepted the recommendation) |

