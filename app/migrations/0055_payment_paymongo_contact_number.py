from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0054_chatmoderationevent_chatmoderationstate"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "UPDATE app_payment "
                "SET gcash_reference_number = '' "
                "WHERE gcash_reference_number IS NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE app_payment "
                "SET gcash_sender_name = '' "
                "WHERE gcash_sender_name IS NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddField(
            model_name="payment",
            name="paymongo_contact_number",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
