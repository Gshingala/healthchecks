from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from datetime import timedelta as td
from typing import Any
from zoneinfo import ZoneInfo

from django import forms

from hc.api.models import MaintenanceWindow
from hc.front.validators import (
    CronValidator,
    OnCalendarValidator,
    TimezoneValidator,
    WebhookValidator,
)


def _choices(csv: str) -> list[tuple[str, str]]:
    return [(v, v) for v in csv.split(",")]


class LaxURLField(forms.URLField):
    """Subclass of URLField which additionally accepts URLs without a tld.

    For example, unlike URLField, it accepts "http://home_server"

    """

    default_validators = [WebhookValidator()]


class NameTagsForm(forms.Form):
    name = forms.CharField(max_length=100, required=False)
    slug = forms.SlugField(max_length=100, required=False)
    tags = forms.CharField(max_length=500, required=False)
    desc = forms.CharField(max_length=10000, required=False)

    def clean_tags(self) -> str:
        result = []

        for part in self.cleaned_data["tags"].split(" "):
            part = part.strip()
            if part != "":
                result.append(part)

        return " ".join(result)


class AddCheckForm(NameTagsForm):
    kind = forms.ChoiceField(choices=_choices("simple,cron,oncalendar"))
    timeout = forms.IntegerField(min_value=60, max_value=31536000)
    schedule = forms.CharField(required=False, max_length=100)
    tz = forms.CharField(max_length=36, validators=[TimezoneValidator()])
    grace = forms.IntegerField(min_value=60, max_value=31536000)

    def clean_timeout(self) -> td:
        return td(seconds=self.cleaned_data["timeout"])

    def clean_grace(self) -> td:
        return td(seconds=self.cleaned_data["grace"])

    def clean_schedule(self) -> str:
        kind = self.cleaned_data.get("kind")
        if kind == "cron":
            cron_validator = CronValidator()
            cron_validator(self.cleaned_data["schedule"])
        elif kind == "oncalendar":
            oncalendar_validator = OnCalendarValidator()
            oncalendar_validator(self.cleaned_data["schedule"])
        else:
            # If kind is not cron or oncalendar, ignore the passed in value
            # and use "* * * * *" instead.
            return "* * * * *"

        assert isinstance(self.cleaned_data["schedule"], str)
        return self.cleaned_data["schedule"]


MAINTENANCE_FORM_ERRORS: dict[str, str] = {
    "end_before_start": "End must be after start.",
    "end_in_past": "End must be in the future.",
    "too_long": "A maintenance window can be at most 30 days long.",
    "limit": "This project already has 100 upcoming or active maintenance "
    "windows. End or delete one before adding another.",
}
NONEXISTENT_TIME_ERROR = (
    "{} does not exist in {} because of a daylight-saving change. Choose another time."
)
SCOPE_CHOICES = (("all", "All checks"), ("tags", "Checks with all of these tags"))


def _messages(message: str, *codes: str) -> dict[str, str]:
    return {code: message for code in ("required", "invalid", *codes)}


class MaintenanceScopeForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        error_messages=_messages("Enter a name of 1 to 100 characters.", "max_length"),
    )
    scope = forms.ChoiceField(
        choices=SCOPE_CHOICES,
        error_messages=_messages("Choose a scope.", "invalid_choice"),
    )
    tags = forms.CharField(
        max_length=500,
        required=False,
        error_messages={"max_length": "Tags can be at most 500 characters."},
    )

    def clean_tags(self) -> str:
        return MaintenanceWindow.normalize_tags(self.cleaned_data["tags"])

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        assert cleaned_data is not None
        scope = cleaned_data.get("scope")
        if scope == "all":
            cleaned_data["tags"] = ""
        elif scope == "tags" and cleaned_data.get("tags") == "":
            self.add_error("tags", "Enter at least one tag.")
        return cleaned_data


class MaintenanceWindowForm(MaintenanceScopeForm):
    start_date = forms.DateField(
        input_formats=["%Y-%m-%d"],
        error_messages=_messages("Enter a valid start date and time."),
    )
    start_time = forms.TimeField(
        input_formats=["%H:%M"],
        error_messages=_messages("Enter a valid start date and time."),
    )
    end_date = forms.DateField(
        input_formats=["%Y-%m-%d"],
        error_messages=_messages("Enter a valid end date and time."),
    )
    end_time = forms.TimeField(
        input_formats=["%H:%M"],
        error_messages=_messages("Enter a valid end date and time."),
    )

    def __init__(self, *args: Any, tz: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tz = tz

    def _to_utc(self, prefix: str) -> datetime | None:
        """Combine the local date and time fields into an aware UTC datetime.

        Ambiguous local times resolve to their first occurrence (fold=0).
        Return None and add an error if the local time does not exist.
        """
        d = self.cleaned_data.get(f"{prefix}_date")
        t = self.cleaned_data.get(f"{prefix}_time")
        if d is None or t is None:
            return None

        tzinfo = ZoneInfo(self.tz)
        local = datetime.combine(d, t, tzinfo=tzinfo)
        result = local.astimezone(timezone.utc)
        # A nonexistent local time does not survive the round trip unchanged
        if result.astimezone(tzinfo).replace(tzinfo=None) != local.replace(tzinfo=None):
            label = local.strftime("%Y-%m-%d %H:%M")
            self.add_error(
                f"{prefix}_date", NONEXISTENT_TIME_ERROR.format(label, self.tz)
            )
            return None
        return result

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        start, end = self._to_utc("start"), self._to_utc("end")
        if start and end:
            cleaned_data["start"] = start
            cleaned_data["end"] = end
        return cleaned_data

    def apply_times(
        self, at: datetime, *, original_start: datetime | None = None
    ) -> tuple[datetime, datetime] | None:
        start = self.cleaned_data["start"] if original_start is None else original_start
        try:
            return MaintenanceWindow.clean_times(
                start,
                self.cleaned_data["end"],
                at=at,
                move_start=original_start is None,
            )
        except MaintenanceWindow.Invalid as e:
            self.add_error("end_date", MAINTENANCE_FORM_ERRORS[e.code])
            return None


class StartNowForm(MaintenanceScopeForm):
    duration_minutes = forms.IntegerField(
        min_value=1,
        max_value=43200,
        error_messages=_messages(
            "Enter a length of 1 to 43200 minutes.", "min_value", "max_value"
        ),
    )


class FilteringRulesForm(forms.Form):
    filter_subject = forms.BooleanField(required=False)
    filter_body = forms.BooleanField(required=False)
    filter_http_body = forms.BooleanField(required=False)
    filter_default_fail = forms.BooleanField(required=False)
    start_kw = forms.CharField(required=False, max_length=200)
    success_kw = forms.CharField(required=False, max_length=200)
    failure_kw = forms.CharField(required=False, max_length=200)
    methods = forms.ChoiceField(required=False, choices=(("", "Any"), ("POST", "POST")))
    manual_resume = forms.BooleanField(required=False)


class TimeoutForm(forms.Form):
    timeout = forms.IntegerField(min_value=60, max_value=31536000)
    grace = forms.IntegerField(min_value=60, max_value=31536000)

    def clean_timeout(self) -> td:
        return td(seconds=self.cleaned_data["timeout"])

    def clean_grace(self) -> td:
        return td(seconds=self.cleaned_data["grace"])


class CronPreviewForm(forms.Form):
    schedule = forms.CharField(max_length=100, validators=[CronValidator()])
    tz = forms.CharField(max_length=36, validators=[TimezoneValidator()])


class CronForm(forms.Form):
    schedule = forms.CharField(max_length=100, validators=[CronValidator()])
    tz = forms.CharField(max_length=36, validators=[TimezoneValidator()])
    grace = forms.IntegerField(min_value=60, max_value=31536000)

    def clean_grace(self) -> td:
        return td(seconds=self.cleaned_data["grace"])


class OnCalendarForm(forms.Form):
    schedule = forms.CharField(max_length=100, validators=[OnCalendarValidator()])
    tz = forms.CharField(max_length=36, validators=[TimezoneValidator()])
    grace = forms.IntegerField(min_value=60, max_value=31536000)

    def clean_grace(self) -> td:
        return td(seconds=self.cleaned_data["grace"])


class AddUrlForm(forms.Form):
    error_css_class = "has-error"
    value = LaxURLField(max_length=1000, assume_scheme="https")


class PhoneNumberForm(forms.Form):
    error_css_class = "has-error"
    label = forms.CharField(max_length=100, required=False)
    phone = forms.CharField()

    def clean_phone(self) -> str:
        v = self.cleaned_data["phone"]
        assert isinstance(v, str)

        stripped = v.encode("ascii", "ignore").decode("ascii")
        stripped = stripped.replace(" ", "").replace("-", "")
        if not re.match(r"^\+\d{5,15}$", stripped):
            raise forms.ValidationError("Invalid phone number format.")

        return stripped

    def get_json(self) -> str:
        return json.dumps({"value": self.cleaned_data["phone"]})


class PhoneUpDownForm(PhoneNumberForm):
    up = forms.BooleanField(required=False, initial=True)
    down = forms.BooleanField(required=False, initial=True)

    def clean(self) -> None:
        super().clean()

        down = self.cleaned_data.get("down")
        up = self.cleaned_data.get("up")

        if not down and not up:
            self.add_error("down", "Please select at least one.")

    def get_json(self) -> str:
        return json.dumps(
            {
                "value": self.cleaned_data["phone"],
                "up": self.cleaned_data["up"],
                "down": self.cleaned_data["down"],
            }
        )


class ChannelNameForm(forms.Form):
    name = forms.CharField(max_length=100, required=False)


class SearchForm(forms.Form):
    q = forms.RegexField(regex=r"^[0-9a-zA-Z\s]{3,100}$")


class LogFiltersForm(forms.Form):
    # min_value is 2010-01-01, max_value is 2030-01-01
    u = forms.FloatField(min_value=1262296800, max_value=1893448800, required=False)
    end = forms.FloatField(min_value=1262296800, max_value=1893448800, required=False)
    success = forms.BooleanField(required=False)
    fail = forms.BooleanField(required=False)
    start = forms.BooleanField(required=False)
    log = forms.BooleanField(required=False)
    ign = forms.BooleanField(required=False)
    notification = forms.BooleanField(required=False)
    flip = forms.BooleanField(required=False)

    def clean_u(self) -> datetime | None:
        if self.cleaned_data["u"]:
            return datetime.fromtimestamp(self.cleaned_data["u"], tz=timezone.utc)
        return None

    def clean_end(self) -> datetime | None:
        if self.cleaned_data["end"]:
            return datetime.fromtimestamp(self.cleaned_data["end"], tz=timezone.utc)
        return None

    def kinds(self) -> tuple[str, ...]:
        kind_keys = ("success", "fail", "start", "log", "ign", "notification", "flip")
        return tuple(key for key in kind_keys if self.cleaned_data[key])


class TransferForm(forms.Form):
    project = forms.UUIDField()


class BadgeSettingsForm(forms.Form):
    target = forms.ChoiceField(choices=_choices("all,tag,check"))
    tag = forms.CharField(max_length=100, required=False)
    check = forms.UUIDField(required=False)
    fmt = forms.ChoiceField(choices=_choices("svg,json,shields"))
    states = forms.ChoiceField(choices=_choices("2,3"))
