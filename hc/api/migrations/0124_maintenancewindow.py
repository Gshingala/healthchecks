import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0053_alter_profile_sms_limit"),
        ("api", "0123_alter_channel_kind"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MaintenanceWindow",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("name", models.CharField(max_length=100)),
                ("start", models.DateTimeField()),
                ("end", models.DateTimeField()),
                ("tags", models.CharField(blank=True, max_length=500)),
                (
                    "created",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "created_via",
                    models.CharField(
                        choices=[("dashboard", "Dashboard"), ("api", "API")],
                        max_length=9,
                    ),
                ),
                (
                    "end_handled",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="accounts.project",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["project", "end"], name="api_mw_project_end"),
                    models.Index(
                        condition=models.Q(("end_handled", None)),
                        fields=["end"],
                        name="api_mw_end_not_handled",
                    ),
                ],
            },
        ),
    ]
