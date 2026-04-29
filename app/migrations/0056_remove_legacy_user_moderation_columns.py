from django.db import migrations


LEGACY_USER_COLUMNS = [
    "chat_banned_until",
    "profanity_strikes",
    "last_profanity_strike_date",
]


def drop_legacy_user_moderation_columns(apps, schema_editor):
    table_name = "app_user"
    connection = schema_editor.connection
    existing_columns = {
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), table_name
        )
    }

    quoted_table = schema_editor.quote_name(table_name)
    for column_name in LEGACY_USER_COLUMNS:
        if column_name in existing_columns:
            schema_editor.execute(
                f"ALTER TABLE {quoted_table} DROP COLUMN {schema_editor.quote_name(column_name)}"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0055_payment_paymongo_contact_number"),
    ]

    operations = [
        migrations.RunPython(
            drop_legacy_user_moderation_columns,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
