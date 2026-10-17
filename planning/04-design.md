# Design: maintenance windows

`has_ui_layer` is `true` (`.forge/repo-map.json`). This app already has a visual system: Bootstrap 3 built from `stuff/` into `static/css/bootstrap.css`, colour custom properties for light and dark themes in `static/css/variables.css`, and one hand-written stylesheet per screen. This document records that system as it was found, then adds only what maintenance windows need (REQ-1.x, REQ-5.x in `planning/02-prd.md`; template contracts in `planning/03-lld.md` § "Templates and static").

Binding constraints, all met: no CDN, no web fonts fetched at runtime, no new CSS framework, no build step, no new JavaScript dependency. jQuery 3.6.0, Bootstrap 3 JS and TomSelect are already vendored in `static/js/`, and the new code uses only those. The icon font `static/fonts/icomoon.woff2` is self-hosted.

---

## 1. Token set

### 1.1 Found and already named: CSS custom properties in `static/css/variables.css`

The light values are on `:root` (`variables.css:1-80`). The dark values are on `body.dark` (`variables.css:83-163`). `base.html` adds the `dark` class from `Profile.theme`, or from `prefers-color-scheme` when the theme is `system`. Only the tokens this feature uses are listed. The file holds about 75 in total.

| Token | Light | Dark | Used by this feature for |
|---|---|---|---|
| `--body-bg` | `#FFF` | `hsl(240, 6%, 10%)` | page background |
| `--modal-content-bg` | `#fff` | `#1f1f22` | modal background |
| `--text-color` | `#333` | `hsl(240, 3.3%, 88.2%)` | body text, window names, times |
| `--text-muted` | `#767676` | `hsl(240, 3%, 55%)` | time-zone label, "Created by", ended rows, preview text, `.help-block` |
| `--text-warning` | `#8a6d3b` | `#cb964d` | preview zero-match warning (REQ-5.8) |
| `--link-color` | `#0091EA` | `hsl(202.8, 100%, 55%)` | links in the preview list, and the keyboard focus ring (§4.1) |
| `--border-muted` | `#eee` | `hsl(240, 3%, 22%)` | table row separators |
| `--state-info-bg` | `#d9edf7` | `#123051` | Maintenance label background, empty-state alert |
| `--state-info-border` | `#bce8f1` | `#163c64` | Maintenance label border |
| `--state-info-color` | `#31708f` | `#e0e2f5` | Maintenance label text and icon, withheld text in the log |
| `--log-flip-bg` | `#eee` | `#383840` | background of flip rows in the log (`log.css`, `#log tr.flip`) |
| `--tag-bg` / `--tag-color` | `#eee` / `#555` | `#303033` / `#e0e0e2` | tag pills in the Scope column (`.label-tag`, `checks.css:63`) |
| `--btn-default-bg` / `-color` / `-border` | `#fff` / `#333` / `#ccc` | `#383840` / `hsl(240, 3%, 88%)` / `transparent` | secondary buttons |
| `--btn-active-bg` / `-color` / `-border` | `#e6e6e6` / `#333` / `#adadad` | `#6f6f7f` / `hsl(240, 3%, 98%)` / `#818191` | hover, focus, active and `.active` state of `btn-default` (selected preset) |
| `--btn-remove-bg` / `-color` / `-hover` | `#fff` / `#d43f3a` / `#ffebea` | `transparent` / `#ff4c46` / `rgba(255, 76, 70, 0.15)` | Delete… trigger (`.btn-remove`) |
| `--input-border` | `#ccc` | `#464649` | text inputs and the radio ring |
| `--input-bg-disabled` | `#eeeeee` | `#29292c` | disabled inputs |

### 1.2 Found in use but never named

These values recur as hard-coded literals across the stylesheets. **This document names them for the first time.** They are *not* declared as custom properties: the codebase writes them as literals, and moving them into `variables.css` would refactor every screen, which this change does not do. New CSS uses the literal and puts the name here in a comment only where that helps.

| Name given here | Value | Where it recurs |
|---|---|---|
| brand green / primary | `#22bc66` (border `#1ea65a`, hover `#1da258`, active `#1a914f`) | `.btn-primary` (`bootstrap.css:2365-2388`), `.label-success`, `.label-confirmation` (`checks.css:69`), ON labels (`details.css:72`), `#nav-sign-up` (`base.css`) |
| status up | `#5cb85c` | `.status.ic-up` (`base.css`) |
| status grace | `#f0ad4e` | `.status.ic-grace`, `#my-checks-tags .grace`, `.label-warning` |
| status down / danger | `#d9534f` (border `#d43f3a`) | `.status.ic-down`, `.badge-down`, `.btn-danger`, `.label-danger`, `#my-checks-tags .down` |
| form error | `#a94442` | `.has-error *` (`bootstrap.css:2132-2158`), `.alert-danger`, `#log tr.missing td` |
| focus glow | `#66afe9` + `0 0 0 4px rgba(102, 175, 233, 0.2)` | `.form-control:focus` (`bootstrap.css:1845`), `.radio-container input:focus ~ .radiomark` (`radio.css`) |
| font stack | `-apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif`, 14px / 1.42857 | `body` (`bootstrap.css:268-273`). System fonts only |
| mono stack | `"Lucida Console", Monaco, monospace` | `log.css` |
| small text | `12px` (meta lines), `11.7px` (mini details), `13px` (log) | `log.css`, `channels.css`, `details.css` |
| label | `75%`, weight 700, padding `.2em .6em .3em`, radius `.25em` | `.label` (`bootstrap.css:3686`) |
| radius | `4px` controls, `3px` modals | `bootstrap.css` |
| section gap | `36px` | `.details-block` margin-bottom (`details.css`), `.channels-table` margin-top (`channels.css:1`) |
| row padding | `10px` top and bottom | `.channels-table .channel-row > td` (`channels.css`) |
| modal body padding (forms) | `15px 40px` | `#add-check-modal .modal-body`, `#update-name-modal .modal-body` (`checks.css`) |
| wide modal | `650px` at `min-width: 992px` | `#add-check-modal`, `#update-name-modal` (`checks.css`) |

### 1.3 New token (1)

| Token | Light | Dark | Why nothing existing covered it |
|---|---|---|---|
| `--form-error-color` | `#a94442` | `#ff4c46` | Field-error text is hard-coded `#a94442` in `bootstrap.css`, with no dark override. That measures **2.81:1** on the dark modal, which fails AA. No existing token gives AA error text in both themes. The light value equals the current one, so light mode does not change. The dark value reuses the existing dark `--btn-remove-color`. |

Declared in `static/css/variables.css` (both themes) and applied in `static/css/bootstrap-colors.css` to `.has-error .help-block`, `.has-error .control-label`, `.has-error .form-control` and `.has-error .form-control:focus`.

---

## 2. Measured contrast

Ratios computed with the WCAG 2.x relative-luminance formula, by a script run on the exact values above (output reproduced). AA needs 4.5:1 for text under 18.66px bold or 24px regular, and 3:1 for focus indicators and the graphical parts of controls.

### 2.1 Pairs this feature uses: all pass

| Pair | Light | Dark |
|---|---|---|
| `--text-color` on `--body-bg` | 12.63 | 13.43 |
| `--text-muted` on `--body-bg` (time zone, "Created by", ended rows) | 4.54 | 5.09 |
| `--text-muted` on `--modal-content-bg` (help text, preview) | 4.54 | 4.72 |
| `--text-warning` on `--modal-content-bg` (zero-match warning) | 4.85 | 6.27 |
| `--state-info-color` on `--state-info-bg` (Maintenance label text and icon; empty-state alert) | 4.53 | 10.44 |
| `--state-info-color` on `--log-flip-bg` (withheld text) | 4.71 | 9.05 |
| `--tag-color` on `--tag-bg` (scope tags) | 6.43 | 9.98 |
| `--btn-default-color` on `--btn-default-bg` | 12.63 | 8.77 |
| `--btn-active-color` on `--btn-active-bg` (hover, `.active` preset) | 10.12 | 4.72 |
| `--btn-remove-color` on page (Delete… trigger) | 4.59 | 5.38 |
| `--btn-remove-color` on `--btn-remove-hover` | 4.01 (see F-6) | n/a: translucent over dark |
| `--form-error-color` on `--modal-content-bg` (field errors) | 5.85 | 4.99 |
| `--form-error-color` on `--body-bg` | 5.85 | 5.38 |
| `.alert-danger` `#a94442` on `#f2dede` (non-field errors; not themed) | 4.53 | 4.53 |
| Focus ring `--link-color` against `--body-bg` / modal | 3.37 | 6.81 / 6.32 |

### 2.2 Findings: existing patterns that fail AA

These are named here and **not** copied into anything new, except where §3 says reuse wins and the conflict is recorded.

| ID | Pattern | Measured | Status |
|---|---|---|---|
| F-1 | `.btn-primary`: white on `#22bc66` (hover `#1da258` 3.30, active `#1a914f` 4.03) | **2.48** | Pre-existing and app-wide. Reused for the one primary action per screen, so this feature does not add a second primary style (see Assumptions A-1). Fix belongs to a separate change: white on `#117a3f` is 5.41, on `#15733e` 5.91. Both are already in the palette. |
| F-2 | `.btn-danger`: white on `#d9534f` | **3.96** | Pre-existing. Reused for confirm buttons in modals, as `remove_check_modal.html` does (A-1). Fix candidate: white on `#c9302c` is 5.33. |
| F-3 | Body links `--link-color` `#0091EA` on white | **3.37** | Pre-existing, light theme only (dark 6.81). Affects the preview's check links. Fix candidate: `--link-hover-color` `#00629e` is 6.48. |
| F-4 | `.btn:focus { outline: 0 }` (`base.css`): the `btn-default` focus state is `#e6e6e6` on `#fff`, **1.26:1**, so keyboard focus was effectively invisible | 1.26 | **Fixed in this change**, keyboard only: `.btn:focus-visible` gets `outline: 2px solid var(--link-color); outline-offset: 2px`. Mouse focus looks the same as before. |
| F-5 | Radio focus is a 4px glow at 20% opacity | ≈1.2 | **Fixed in this change**, keyboard only: `.radio-container input:focus-visible ~ .radiomark` gets the same 2px ring. |
| F-6 | `.btn-remove:hover` light `#d43f3a` on `#ffebea` | 4.01 | Pre-existing. Shown only while the pointer is over the button. Left unchanged. |
| F-7 | Dark field errors `#a94442` on the dark modal | **2.81** | **Fixed in this change** by `--form-error-color` (§1.3). |
| F-8 | `.channel-row .actions .btn { visibility: hidden }` until row hover (`channels.css`) hides the buttons from the keyboard and from touch | n/a | Pre-existing. **Not extended**: maintenance row actions are always visible. |
| F-9 | `--text-muted` on `--table-bg-hover` (4.17 light, 4.38 dark) and on `--log-flip-bg` (3.91 light, 3.33 dark) | <4.5 | Pre-existing. Maintenance rows get no hover background, and withheld text uses `--state-info-color`, not muted. |
| F-10 | Dark `.alert.no-events` / `.no-channels` text `#878790` on `#29292c` | 4.07 | Pre-existing. The Maintenance empty state uses `.alert.alert-info` (10.44 dark) instead, the same pattern as the empty checks page. |
| F-11 | `.form-control:focus` border `#66afe9` on white ≈2.2 | <3 | Pre-existing and app-wide. Text inputs still show the caret, so focus is visible. Left unchanged. |

---

## 3. Screen archetypes

| Archetype the feature needs | Existing analogue reused | Where it is used |
|---|---|---|
| Project section page with a table of objects and row actions | Integrations page: `templates/front/channels.html` (`table.table` with per-row `.actions`, `messages` loop at the top) | Maintenance page (REQ-5.4) |
| Primary "create" button at the top of a list | Checks page "Add Check" `btn btn-primary` opening a modal (`checks.html:139-147`) | "Schedule…" |
| Create and edit form | Modal form `.modal > .modal-dialog > form.form-horizontal > .modal-content`, `col-sm-3` labels and `col-sm-9` controls (`add_check_modal.html`); one modal per row for edit (`channels.html`, `#name-<code>`) | Schedule, Start now, Edit, and Start maintenance on the details page |
| Field error | `.form-group.has-error` plus `.help-block` that replaces the help text (`hc/integrations/call/templates/add_call.html:35-55`) | Every window form field |
| Destructive or consequential confirm | `remove_check_modal.html`: Cancel `btn-default` and confirm `btn-danger` in `.modal-footer` | End now, Delete |
| Empty state | `.alert.alert-info` with the explanation (`checks.html:163`) | "No maintenance windows yet." (REQ-5.6) |
| Error state (whole request) | `messages` → `<p class="alert alert-{{ message.tags }}">` (`channels.html:9-15`) | 400 responses MW-D10, D11, D12 as `error_message`, rendered `alert-danger` |
| Success feedback | `messages.success` → `.alert-success` (same loop) | after every successful write (§5.9) |
| Status label on a check | `.label` family: `label-tag`, `label-danger` "Disabled" (`channels.html`) | Maintenance label (REQ-5.3) |
| Log annotation | Flip row in `log_row.html` (`tr.flip`) | Withheld text (REQ-5.1, 5.2) |
| Navigation entry | `#nav-main-sections` `<li class="active">` (`base.html`) | "Maintenance" (REQ-1.1) |

No new archetype is needed.

---

## 4. Components

Real class names. Each component lists the states it needs. ✔ marks what is shipped in this change (§6). Everything else is markup for the developer to use verbatim.

### 4.1 Buttons: reused, no new styles

| Role | Classes | States |
|---|---|---|
| Primary create (page header) | `btn btn-primary` | rest; hover `#1da258`; active `#1a914f`; **keyboard focus ✔ 2px `--link-color` ring, offset 2px**; disabled `[disabled]` (Bootstrap opacity .65, `not-allowed`) |
| Secondary (Start Now…, Edit…, End Now…, Start Maintenance…, Cancel, presets) | `btn btn-default` (`btn-sm` in rows and on the details page) | rest; hover, focus and active → `--btn-active-*`; selected preset → `.active` + `aria-pressed="true"`; keyboard focus ✔ ring; disabled |
| Destructive trigger (Delete…) | `btn btn-sm btn-remove` | rest; hover and focus `--btn-remove-hover`; keyboard focus ✔ ring |
| Modal submit | `btn btn-primary` (Save, Schedule, Start) / `btn btn-danger` (End Now, Delete) | rest, hover, focus as above; **loading**: on submit, `disabled` is set and the text is replaced by `data-pending-text` (REQ-1.19). It is re-enabled only by a page reload |

Repeated row buttons include the window name for screen readers: `Edit<span class="sr-only"> {{ mw.name }}</span>&hellip;`.

### 4.2 Navigation item (REQ-1.1). In `base.html`, after Badges and before Settings

```django
<li {% if page == 'maintenance' %} class="active" {% endif %}>
    <a href="{% url 'hc-maintenance' project.code %}">Maintenance</a>
</li>
```
States are inherited from `#nav-main-sections`: rest; hover and active get a 5px `--border-muted` underline (≥768px) or a left bar (<768px); focus uses the browser default outline (links are not affected by the `.btn` outline reset).

### 4.3 Maintenance label ✔ (REQ-5.3) in `templates/front/maintenance_label.html`

```html
<span class="label label-maintenance" role="img"
      title="Under maintenance until Nov 7, 23:30 Europe/Riga (Postgres upgrade)"
      aria-label="Under maintenance until Nov 7, 23:30 Europe/Riga (Postgres upgrade)"><span class="ic-maintenance" aria-hidden="true"></span> Maintenance</span>
```
- Context: `mw` (the covering window with the latest end), `tz`. Include it with `{% include "front/maintenance_label.html" with mw=… tz=… %}`.
- Placement: on the checks list, inside `.my-checks-name` after the tag labels (`checks_table.html`). On the details page, inside `#details-head` after the tag labels.
- Style: Bootstrap `.label` metrics, text and icon `--state-info-color` on `--state-info-bg`, 1px `--state-info-border`. Blue "information" was chosen because the existing status colours already mean up (green), late (amber), down (red) and paused or new (grey). Maintenance must not read as any of them.
- It is never conveyed by colour alone: the visible word "Maintenance", the icon, and the full sentence in `title` and the accessible name.
- States: **rest** only. It is not interactive. **Absent** when the check is not covered now (REQ-5.3).
- `role="img"` is added to the LLD contract so that `aria-label` is a valid accessible name. ARIA 1.2 does not allow naming a role-less `<span>`, and screen readers ignore it there.
- Verified escaping (REQ-5.9): a name `<script>alert(1)</script>` renders as `(&lt;script&gt;alert(1)&lt;/script&gt;)` (Django shell render, §6).

### 4.4 Maintenance icon ✔ `.ic-maintenance`

A 16×16 wrench drawn as an inline SVG data URI and applied with CSS `mask`, so it takes `currentColor`. It is 1em square with `vertical-align: -0.125em`. It is always `aria-hidden="true"` next to visible text. Non-text contrast equals its text colour (4.53 light and 10.44 dark in the label; 4.71 and 9.05 in the log).

### 4.5 Withheld text in the event log ✔ (REQ-5.1, 5.2) in `templates/front/log_row.html` flip branch

```html
Status: <strong>up ➔ down</strong>.
<span class="withheld"><span class="ic-maintenance" aria-hidden="true"></span> Alert not sent: maintenance window "Postgres upgrade"</span>
```
- Renders only when `event.withheld` is truthy. The quoted name is omitted when `event.withheld_window_name` is `None` (REQ-5.2).
- Style: `#log tr.flip .withheld { margin-left: 8px; color: var(--state-info-color) }`. It is used by `log.html`, `log_events` and the details-page events, because all three include `log_row.html`.
- States: present or absent. The row keeps the existing `nowrap` and ellipsis behaviour.

### 4.6 Maintenance page in `templates/front/maintenance.html`

```django
{% extends "base_project.html" %}
{% load compress static hc_extras tz %}
{% block title %}Maintenance - {{ site_name }}{% endblock %}
{% block content %}
<div class="row">
<div id="maintenance" class="col-sm-12" {% if open_modal %}data-open-modal="{{ open_modal }}"{% endif %}>
    {% for message in messages %}<p class="alert alert-{{ message.tags }}">{{ message }}</p>{% endfor %}
    {% if error_message %}<p class="alert alert-danger">{{ error_message }}</p>{% endif %}

    <div class="maintenance-head">
        <h1>Maintenance</h1>
        {% if rw %}
        <button type="button" class="btn btn-default" data-toggle="modal" data-target="#start-now-modal">Start Now&hellip;</button>
        <button type="button" class="btn btn-primary" data-toggle="modal" data-target="#add-maintenance-modal">Schedule&hellip;</button>
        {% endif %}
    </div>
    <p>While a maintenance window is active, covered checks keep receiving pings and changing
       status, but no alerts are sent. When it ends, each covered check that is still down sends
       one alert. Times are in your time zone, {{ tz }}.</p>

    {% if active or upcoming or ended %}
        {% include "front/maintenance_section.html" with section_id="maintenance-active" title="Active" windows=active state="active" %}
        …upcoming ("Upcoming"), ended ("Ended in the last 90 days")…
    {% else %}
        <div class="alert alert-info">No maintenance windows yet.</div>
    {% endif %}
</div>
</div>
{# modals: add, start-now, and per window edit-/end-/remove- (rw only) #}
{% endblock %}
```
A section is rendered only when it has windows. They always appear in the order Active, Upcoming, Ended (REQ-5.4). Reason: three empty headings add noise, and the empty state already covers "nothing at all". The section markup can be inlined instead of using a sub-template; the LLD lists only `maintenance_row.html`.

```html
<section id="maintenance-active" class="maintenance-section" aria-labelledby="maintenance-active-title">
  <h2 id="maintenance-active-title">Active</h2>
  <table class="table maintenance-table">
    <tr><th>Name</th><th>Start</th><th>End</th><th>Scope</th>{% if rw %}<th><span class="sr-only">Actions</span></th>{% endif %}</tr>
    {% for mw in windows %}{% include "front/maintenance_row.html" %}{% endfor %}
  </table>
</section>
```

Page states:

| State | What renders |
|---|---|
| Empty (REQ-5.6) | `.alert.alert-info` "No maintenance windows yet.". Writers still see both header buttons |
| Populated | non-empty sections in fixed order |
| Read-only member (REQ-1.15) | no header buttons, no Actions column, no modals in the HTML |
| Success after a write | `.alert-success` message at the top (§5.9) |
| Request error 400 (MW-D10/11/12) | `.alert-danger` with `error_message` at the top, then the normal page |
| Form error 200 | the page, with the failing modal reopened by `data-open-modal` and its errors shown (§4.8) |

### 4.7 Window row in `templates/front/maintenance_row.html`

```django
<tr class="mw-{{ state }}">
  <td>
    <div class="mw-name">{{ mw.name }}</div>
    <div class="mw-created-by">{% if mw.created_by %}Created by {{ mw.created_by.email }}{% elif mw.created_via == "api" %}Created via API{% else %}Created by deleted user{% endif %}</div>
  </td>
  <td class="mw-time">{{ mw.start|timezone:tz|date:"M j, Y H:i" }} <span class="mw-tz">{{ tz }}</span></td>
  <td class="mw-time">{{ mw.end|timezone:tz|date:"M j, Y H:i" }} <span class="mw-tz">{{ tz }}</span></td>
  <td>{% if mw.tags %}{% for tag in mw.tags.split %}<span class="label label-tag">{{ tag }}</span> {% endfor %}{% else %}All checks{% endif %}</td>
  {% if rw %}
  <td class="actions">
    {% if state != "ended" %}<button type="button" class="btn btn-sm btn-default" data-toggle="modal" data-target="#edit-{{ mw.code }}">Edit<span class="sr-only"> {{ mw.name }}</span>&hellip;</button>{% endif %}
    {% if state == "active" %}<button type="button" class="btn btn-sm btn-default" data-toggle="modal" data-target="#end-{{ mw.code }}">End Now<span class="sr-only"> {{ mw.name }}</span>&hellip;</button>{% endif %}
    {% if state == "upcoming" %}<button type="button" class="btn btn-sm btn-remove" data-toggle="modal" data-target="#remove-{{ mw.code }}">Delete<span class="sr-only"> {{ mw.name }}</span>&hellip;</button>{% endif %}
  </td>
  {% endif %}
</tr>
```
- Style: `.maintenance-table` rows have 10px vertical padding, a 1px `--border-muted` separator, no border on the header row, and no hover background (rows are not clickable; see F-9). `.mw-tz` and `.mw-created-by` are 12px `--text-muted`. `.mw-ended > td` is `--text-muted`, but the section heading still says "Ended", so state is not shown by colour alone.
- Controls per state (REQ-1.13, 1.14, 1.15): upcoming → Edit and Delete; active → Edit and End Now; ended → none.

### 4.8 Window form modal: schedule and edit, in `templates/front/maintenance_form_modal.html`

The wrapper is the existing modal form pattern. `id` is `add-maintenance-modal` for scheduling and `edit-<code>` per window. Field ids use the prefix `mw-add` or `mw-<code>`, so several modals can share a page without id collisions.

```django
<div id="{{ modal_id }}" class="modal maintenance-modal">
 <div class="modal-dialog">
  <form method="post" action="{{ action }}" class="form-horizontal scope-{{ form.scope.value|default:'all' }}" data-preview-url="{% url 'hc-maintenance-preview' project.code %}">
   {% csrf_token %}
   <div class="modal-content">
    <div class="modal-header">
      <button type="button" class="close" data-dismiss="modal" aria-label="Close">&times;</button>
      <h4>{% if mw %}Edit Maintenance Window{% else %}Schedule Maintenance{% endif %}</h4>
    </div>
    <div class="modal-body">
      {% if form.non_field_errors %}<div class="alert alert-danger">{{ form.non_field_errors|join:" " }}</div>{% endif %}

      <div class="form-group {% if form.name.errors %}has-error{% endif %}">
        <label for="{{ p }}-name" class="col-sm-3 control-label">Name</label>
        <div class="col-sm-9">
          <input id="{{ p }}-name" name="name" type="text" maxlength="100" required class="form-control"
                 value="{{ form.name.value|default:'' }}" aria-describedby="{{ p }}-name-help"
                 {% if form.name.errors %}aria-invalid="true"{% endif %}>
          {% if form.name.errors %}<div id="{{ p }}-name-help" class="help-block">{{ form.name.errors|join:" " }}</div>
          {% else %}<span id="{{ p }}-name-help" class="help-block">Shown on this page and in the event log.</span>{% endif %}
        </div>
      </div>

      <div class="form-group {% if form.start_date.errors or form.start_time.errors %}has-error{% endif %}">
        <label for="{{ p }}-start-date" class="col-sm-3 control-label">Start</label>
        <div class="col-sm-9">
          <input id="{{ p }}-start-date" name="start_date" type="date" class="form-control mw-date" required value="{{ form.start_date.value|default:'' }}" aria-describedby="{{ p }}-start-help">
          <input name="start_time" type="time" class="form-control mw-time-input" required aria-label="Start time" value="{{ form.start_time.value|default:'' }}" aria-describedby="{{ p }}-start-help">
          {% if … errors %}<div id="{{ p }}-start-help" class="help-block">{{ errors }}</div>
          {% else %}<span id="{{ p }}-start-help" class="help-block">In {{ tz }}. A time in the past starts the window now.</span>{% endif %}
        </div>
      </div>

      … End: the same as Start, with names end_date / end_time and help "In {{ tz }}. At most 30 days after the start." …

      <div class="form-group {% if form.scope.errors %}has-error{% endif %}">
        <span id="{{ p }}-scope-label" class="col-sm-3 control-label">Scope</span>
        <div class="col-sm-9" role="radiogroup" aria-labelledby="{{ p }}-scope-label">
          <label class="radio-container"><input type="radio" name="scope" value="all" {% if form.scope.value != "tags" %}checked{% endif %}><span class="radiomark"></span> All checks</label>
          <label class="radio-container"><input type="radio" name="scope" value="tags" {% if form.scope.value == "tags" %}checked{% endif %}><span class="radiomark"></span> Checks with all of these tags</label>
          {% if form.scope.errors %}<div class="help-block">{{ form.scope.errors|join:" " }}</div>{% endif %}
        </div>
      </div>

      <div class="form-group mw-tags-group {% if form.tags.errors %}has-error{% endif %}">
        <label for="{{ p }}-tags" class="col-sm-3 control-label">Tags</label>
        <div class="col-sm-9">
          <input id="{{ p }}-tags" name="tags" type="text" maxlength="500" class="mw-tags" value="{{ form.tags.value|default:'' }}" aria-describedby="{{ p }}-tags-help">
          {% if form.tags.errors %}<div id="{{ p }}-tags-help" class="help-block">{{ form.tags.errors|join:" " }}</div>
          {% else %}<span id="{{ p }}-tags-help" class="help-block">Separate tags with spaces. A check must have every tag to be covered.</span>{% endif %}
        </div>
      </div>

      <div class="form-group"><div class="col-sm-9 col-sm-offset-3">
        <div class="maintenance-preview" aria-live="polite"></div>
      </div></div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>
      <button type="submit" class="btn btn-primary" data-pending-text="Saving&hellip;">{% if mw %}Save{% else %}Schedule{% endif %}</button>
    </div>
   </div>
  </form>
 </div>
</div>
```
- **Edit of an active window** (REQ-1.9, 1.10): Start and Scope render as `<p class="form-control-static">` text, and their current values go in `<input type="hidden">` fields named `start_date`, `start_time`, `scope` and `tags`. Inputs are not disabled, because disabled inputs are not submitted and the form would then fail V2. Help under Start: "This window has already started. Only its name and end time can be changed."
- Tags input: TomSelect with the same options as `add-check-modal.js:15-27` (`create: true, delimiter: " "`, options from `all_tags`). No new dependency.
- Native `type="date"` and `type="time"` post `YYYY-MM-DD` and `HH:MM`, which match `MaintenanceWindowForm.input_formats`.
- Field states: **rest**; **focus** (Bootstrap `.form-control:focus`, see F-11; radios ✔ ring); **error**: `.has-error`, `--form-error-color` border and message replacing the help text, `aria-invalid="true"`, entered values kept (REQ-1.4); **disabled**: not used.
- Where each error goes: V1 → name; V2, V3 → start; V4–V7 → end (LLD `apply_times` adds them to `end_date`); V8 → scope; V9 → tags; V10 limit and MW-D09 "already started" → `.alert-danger` at the top of the modal body as non-field errors.

### 4.9 Start-now modal in `templates/front/maintenance_start_now_modal.html`

The same wrapper, header "Start Maintenance Now", `id="start-now-modal"`, prefix `mw-now`. It has the Name, Scope, Tags and preview groups from §4.8. Start and End are replaced by:

```html
<div class="form-group {% if form.duration_minutes.errors %}has-error{% endif %}">
  <label for="mw-now-duration" class="col-sm-3 control-label">Length</label>
  <div class="col-sm-9">
    <input id="mw-now-duration" name="duration_minutes" type="number" min="1" max="43200" required
           class="form-control mw-duration" value="{{ form.duration_minutes.value|default:'60' }}" aria-describedby="mw-now-duration-help"> minutes
    <div class="btn-group mw-presets" role="group" aria-label="Preset lengths">
      <button type="button" class="btn btn-default btn-sm" data-minutes="30"  aria-pressed="false">30 min</button>
      <button type="button" class="btn btn-default btn-sm active" data-minutes="60" aria-pressed="true">1 hour</button>
      <button type="button" class="btn btn-default btn-sm" data-minutes="120" aria-pressed="false">2 hours</button>
      <button type="button" class="btn btn-default btn-sm" data-minutes="240" aria-pressed="false">4 hours</button>
    </div>
    {% if form.duration_minutes.errors %}<div id="mw-now-duration-help" class="help-block">{{ form.duration_minutes.errors|join:" " }}</div>
    {% else %}<span id="mw-now-duration-help" class="help-block">Starts now. 1 to 43200 minutes (30 days).</span>{% endif %}
  </div>
</div>
```
Submit: `btn btn-primary`, text "Start", `data-pending-text="Starting…"`. A preset button sets the number input and becomes `.active` / `aria-pressed="true"`. Typing a number that matches no preset clears all `.active` (the "Custom" length of REQ-1.6).

**Details page** (REQ-1.7): writers get `<button type="button" class="btn btn-sm btn-default" data-toggle="modal" data-target="#start-now-modal">Start Maintenance&hellip;</button>` in the Current Status block, right after the Pause form (`details.html`, `.text-right` under `#current-status-content`). It includes the same modal, pre-filled: name `Maintenance: <name or code>` truncated to 100, scope `tags` with `check.tags` when the check has tags, otherwise `all`.

### 4.10 Confirm modals: End now and Delete

These are the `remove_check_modal.html` pattern exactly (`class="modal"`, without `maintenance-modal`).

| | End Now (`#end-<code>`) | Delete (`#remove-<code>`) |
|---|---|---|
| Header `h4` | End "{{ mw.name }}" Now? | Delete Maintenance Window? |
| Body | `<p>The window <strong>{{ mw.name }}</strong> ends immediately. Covered checks that are down right now will send their alerts within a minute.</p>` | `<p>You are about to delete <strong>{{ mw.name }}</strong>. It has not started, so no alerts are affected.</p><p>There is no undo.</p>` |
| Footer | Cancel `btn btn-default` · `btn btn-danger` "End Now", `data-pending-text="Ending…"` | Cancel `btn btn-default` · `btn btn-danger` "Delete", `data-pending-text="Deleting…"` |
| Form | POST `hc-end-maintenance`, CSRF | POST `hc-remove-maintenance`, CSRF |

End now uses the danger style even though it deletes nothing, because it can page on-call people at once (REQ-3.4).

### 4.11 Scope preview `.maintenance-preview` (REQ-5.7, 5.8)

It is an `aria-live="polite"` region below Tags. `maintenance.js` updates it with `.text()` and DOM nodes built with jQuery `$("<a>").text(name).attr("href", url)`, never `.html()` (REQ-5.9). Each change triggers one debounced (300 ms) request.

| State | Content | Class |
|---|---|---|
| Idle (modal just opened, scope "all") | request fires at once; shows the loading text | — |
| Loading | "Checking which checks this covers…" | — (`--text-muted`) |
| Success, N ≥ 1 | "Covers N checks right now:" + `<ul>` of up to 20 links + "and M more" when N > 20 | — |
| Empty, N = 0 | "No checks have all of these tags right now. The window will still apply to checks that get these tags later." | `.warning` (`--text-warning`) |
| Error (non-200 / network) | "Could not load the preview. You can still save the window." | — |
| Scope "tags" with empty tags | cleared (empty) | — |

### 4.12 JavaScript behaviour `static/js/maintenance.js` (jQuery only)

1. On load, if `#maintenance[data-open-modal]` is set, open the matching modal: `add` → `#add-maintenance-modal`, `start-now` → `#start-now-modal`, `edit-<uuid>` → `#edit-<uuid>`.
2. Scope radios toggle the form class `scope-all` / `scope-tags`. The CSS hides `.mw-tags-group` under `.scope-all`.
3. Preview as in §4.11.
4. Presets as in §4.9.
5. On `submit` of any form inside `.maintenance-modal`, or of an End or Delete confirm form: set `disabled` on the submit button and replace its text with `data-pending-text`.

Load it on `maintenance.html` and `details.html` inside `{% compress js %}`, after `tom-select.popular.min.js`.

### 4.13 Success messages (§3 success feedback)

`messages.success` after each successful write: "Maintenance window scheduled." · "Maintenance window started." · "Maintenance window updated." · "Maintenance window ended." · "Maintenance window deleted." (REQ-1.12 fixes the last one; the other four are this document's decision so that every action confirms success). When "Start Maintenance…" is used from the details page, the redirect is still to the Maintenance page (PRD: one create path), and the message appears there.

---

## 5. New in this change, with the reason for each

| New | Why the existing set did not have it |
|---|---|
| `--form-error-color` token | No token gives AA field-error text in dark mode; the hard-coded `#a94442` is 2.81:1 there (F-7). |
| `.ic-maintenance` | The icon font (`icomoon.css`) has 12 glyphs and none means maintenance. Adding one would mean rebuilding the font from `stuff/`, which is a build step. A CSS-mask data URI follows the `#search` icon precedent (`checks.css`, inline base64 SVG). |
| `.label-maintenance` | No existing label means "known and deliberate". Every existing label colour already means up, late, down, paused, ignored or tag. It is built only from the existing `--state-info-*` tokens. |
| `#log tr.flip .withheld` | Flip rows had no secondary annotation. Uses `--state-info-color` because `--text-muted` fails on `--log-flip-bg` (F-9). |
| `.maintenance-head`, `.maintenance-section`, `.maintenance-table`, `.mw-*`, `.maintenance-modal` sizing, `.maintenance-preview` | Layout for one new screen. Every value is copied from the existing pattern named in §1.2: 36px section gap, 10px row padding, 15px 40px modal padding, 650px modal. |
| `.btn:focus-visible` and radio `:focus-visible` rings (global) | Fixes F-4 and F-5. The app removed button focus outlines and had no other visible keyboard focus. Mouse focus looks the same as before. |

---

## 6. Applied in this change

| File | Change | Visible now? |
|---|---|---|
| `static/css/maintenance.css` (new) | All §4 styles | Yes. Served by the running app: `GET /static/css/maintenance.css` → 200, and the login page HTML links `href="/static/css/maintenance.css"` (runserver on 127.0.0.1:18766, Host `localhost:8000`) |
| `templates/base.html` | `maintenance.css` added to the `{% compress css %}` block after `login.css` | Yes, on every page |
| `static/css/variables.css` | `--form-error-color` in both themes | Yes |
| `static/css/bootstrap-colors.css` | `.has-error` text and border use `--form-error-color` | Yes. Dark mode only; light is unchanged |
| `static/css/base.css` | `.btn:focus-visible` ring | Yes, on keyboard focus |
| `static/css/radio.css` | radio `:focus-visible` ring | Yes, on keyboard focus |
| `templates/front/maintenance_label.html` (new) | §4.3 | Once a view includes it |
| `templates/front/log_row.html` | §4.5 withheld branch, guarded by `event.withheld` | Once `Flip` provides `withheld` (LLD) |

Verification:
- `SECRET_KEY=dummy-key .venv/bin/python manage.py test --parallel 1` → `Ran 1769 tests in 20.619s`, `OK`, exit 0.
- A Django shell render of `maintenance_label.html` with `end=2026-11-07T21:30Z`, `tz=Europe/Riga` and name `<script>alert(1)</script>` gave `title="Under maintenance until Nov 7, 23:30 Europe/Riga (&lt;script&gt;alert(1)&lt;/script&gt;)"`.
- `log_row.html` rendered with `withheld=True` gave `Alert not sent: maintenance window "Postgres &quot;upgrade&quot; &lt;b&gt;"`. With the name `None` it gave the text without a name. With `withheld=False` it gave no span.

**Not done in this phase. Left for the developer, with exact markup above:** the nav item (§4.2; `{% url 'hc-maintenance' %}` would raise `NoReverseMatch` until the route exists), `maintenance.html`, `maintenance_row.html`, `maintenance_form_modal.html`, `maintenance_start_now_modal.html`, `maintenance.js`, the label includes in `checks_table.html` and `details.html`, and the details-page button. None of these can be rendered or tested before the views and URLs in `planning/03-lld.md` exist.

---

## Assumptions

- A-1: Where reuse and AA conflict on an app-wide pattern (F-1 `.btn-primary`, F-2 `.btn-danger`, F-3 link colour), this feature reuses the existing class and does not add a maintenance-only variant. Reason: a second primary, danger or link style would be visible as "new work" and splits the system. The fix values are listed in §2.2 for a separate app-wide change, to be decided at the gate. This is a conflict between "WCAG AA for whatever you touch" and "reuse existing classes". It is named here, not hidden.
- A-2: Accessibility fixes that change nothing for mouse users in light mode (F-4, F-5, F-7) were applied app-wide now, because the maintenance forms depend on them and they cannot be confined to new screens without creating a second focus or error style.
- A-3: `event.withheld` and `event.withheld_window_name` are the attribute names on log events, per the LLD template contract. If the developer names them differently, only `log_row.html` changes.
- A-4: Window tags are read as `mw.tags.split` in templates. The LLD defines `tags_set()`, which is unordered, and the PRD requires first-seen order (V9).
- A-5: Time format on the Maintenance page is `M j, Y H:i` plus the time-zone name. The label keeps the LLD's `M j, H:i`. Rows include the year because the ended section reaches back 90 days and windows can be scheduled across a year boundary.
- A-6: The wrench SVG was checked by its path geometry, not rendered in a browser here (no headless browser in this environment). The first browser check of the details page should confirm that it reads as a wrench at 10–14px.
