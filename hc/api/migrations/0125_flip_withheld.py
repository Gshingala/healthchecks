from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0124_maintenancewindow"),
    ]

    operations = [
        migrations.AddField(
            model_name="flip",
            name="withheld",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="flip",
            name="withheld_window",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="flip",
            name="withheld_outcome",
            field=models.CharField(
                blank=True,
                choices=[("released", "Released"), ("superseded", "Superseded")],
                max_length=10,
                null=True,
            ),
        ),
    ]
