# Maintenance Windows

A maintenance window is a period of time during which SITE_NAME withholds alerts
for some or all checks in a project. Use maintenance windows for planned work,
such as database upgrades or server reboots, when you expect jobs to miss their
schedules and do not want to be paged about it.

## What a Maintenance Window Does

While a maintenance window is active, the checks it covers work as usual:
they keep receiving pings, and they keep changing status (for example, from "up"
to "down" when a ping is late). The only difference is that SITE_NAME does not
send notifications about these status changes.

* A window starts at its start time (inclusive) and ends at its end time
  (exclusive).
* A window covers either **all checks** in the project, or only the
  **checks having all of the listed tags**. Tag matching is exact and
  case-sensitive: a window with the tags `db prod` covers a check tagged
  `db prod www`, but not a check tagged `db` or `DB prod`.
* A check can be covered by several overlapping windows at the same time.

## What Happens When a Window Ends

When the last maintenance window covering a check ends, and the check is still
down, SITE_NAME sends **one** "down" alert for it. The `sendalerts` process sends
this alert within 60 seconds after the window ends.

* If a check went down and then came back up during the window, SITE_NAME
  sends no alerts for it: both the "down" alert and the matching "up" alert
  are withheld.
* If SITE_NAME withheld a check's "down" alert, it also withholds the "up" alert
  that follows it, so you never receive an "up" alert without the
  "down" alert before it.
* Hourly and daily email reminders about down checks
  (see [Configuring Notifications](../configuring_notifications/)) skip checks that
  are covered by an active maintenance window.

Each withheld alert shows up in the check's event log as
**Alert not sent: maintenance window "&lt;name&gt;"**, where &lt;name&gt; is
the name of the window that covered the check.

## Limits

* A project can have at most 100 upcoming and active maintenance windows.
* A maintenance window can be at most 30 days long.
* SITE_NAME automatically deletes ended maintenance windows 90 days after
  their end time.

## Managing Maintenance Windows in the Dashboard

Open the **Maintenance** page from the project's navigation bar. On this page
you can:

* Schedule a maintenance window for a future time with **Schedule Maintenance**.
* Start a maintenance window immediately with **Start Now**.
* Edit or remove upcoming windows, and end active windows early.

On each check's details page, the **Start Maintenance** button opens a form that
starts a maintenance window immediately. The form is pre-filled to cover the checks
having all of this check's tags (or all checks, if this check has no tags).

## Managing Maintenance Windows with the API

Deploy scripts can open and close maintenance windows using the
[Management API](../api/#list-maintenance). The API lets you list, create, get,
end early, and delete maintenance windows. For example, a deploy script can
create a window with a 30-minute duration before starting a deployment, and end
it once the deployment has finished.

## Notes for Self-Hosted Instances

Maintenance windows rely on the `manage.py sendalerts` management command: it
both withholds alerts during maintenance and sends the deferred alerts after
the windows end. If you self-host SITE_NAME, make sure `sendalerts` is running.

To find withheld alerts that have not yet been released (for example, because
`sendalerts` was not running when a window ended), query the `api_flip` table:

```sql
SELECT * FROM api_flip
WHERE withheld IS NOT NULL AND withheld_outcome IS NULL;
```
