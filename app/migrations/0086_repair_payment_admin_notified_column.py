from django.db import migrations, models


def add_payment_admin_notified_column(apps, schema_editor):
    """
    Migration 0046 added ``Payment.admin_notified`` to the migration state with
    ``database_operations=[]``, so databases created before the column was
    patched in manually (SQLite) never got the actual column. Fresh databases
    (e.g. PostgreSQL) are missing it, which breaks queries and fixture loads.
    Add it if missing; no-op when it already exists.
    """
    Payment = apps.get_model("app", "Payment")
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), Payment._meta.db_table
        )
    }

    if "admin_notified" in existing_columns:
        return

    field = models.BooleanField(default=False)
    field.set_attributes_from_name("admin_notified")
    schema_editor.add_field(Payment, field)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0085_backfill_booking_status_logs"),
    ]

    operations = [
        migrations.RunPython(
            add_payment_admin_notified_column,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
