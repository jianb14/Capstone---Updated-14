from django.db import migrations


def add_missing_paymongo_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return

    table_name = "app_payment"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "paymongo_checkout_session_id" not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN paymongo_checkout_session_id varchar(100) NOT NULL DEFAULT ''"
            )

        if "paymongo_payment_id" not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN paymongo_payment_id varchar(100) NOT NULL DEFAULT ''"
            )

        if "paymongo_checkout_url" not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN paymongo_checkout_url varchar(200) NOT NULL DEFAULT ''"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0044_booking_payment_status"),
    ]

    operations = [
        migrations.RunPython(
            add_missing_paymongo_columns, migrations.RunPython.noop
        ),
    ]

