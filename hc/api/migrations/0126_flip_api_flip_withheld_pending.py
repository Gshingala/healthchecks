from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0125_flip_withheld"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="flip",
            index=models.Index(
                condition=models.Q(
                    ("withheld__isnull", False), ("withheld_outcome", None)
                ),
                fields=["withheld"],
                name="api_flip_withheld_pending",
            ),
        ),
    ]
