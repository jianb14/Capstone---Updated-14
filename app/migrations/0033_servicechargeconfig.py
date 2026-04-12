from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0032_bookingimage"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceChargeConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "notes",
                    models.TextField(
                        blank=True,
                        default="Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Service Charge Configuration",
                "verbose_name_plural": "Service Charge Configuration",
            },
        ),
    ]
