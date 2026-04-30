from django.db import migrations, models


def add_concern_ticket_admin_notified(apps, schema_editor):
    ConcernTicket = apps.get_model("app", "ConcernTicket")
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), ConcernTicket._meta.db_table
        )
    }

    if "admin_notified" in existing_columns:
        return

    field = models.BooleanField(default=False)
    field.set_attributes_from_name("admin_notified")
    schema_editor.add_field(ConcernTicket, field)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0057_repair_review_flags"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_concern_ticket_admin_notified, migrations.RunPython.noop
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="concernticket",
                    name="admin_notified",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
