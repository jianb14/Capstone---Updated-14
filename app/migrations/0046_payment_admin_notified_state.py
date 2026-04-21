from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0045_repair_payment_paymongo_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="payment",
                    name="admin_notified",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]

