from django.db import migrations, models


def add_review_flag_columns(apps, schema_editor):
    Review = apps.get_model("app", "Review")
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), Review._meta.db_table
        )
    }

    fields = [
        ("is_featured", models.BooleanField(default=False)),
        ("admin_notified", models.BooleanField(default=False)),
    ]

    for name, field in fields:
        if name in existing_columns:
            continue
        field.set_attributes_from_name(name)
        schema_editor.add_field(Review, field)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0056_remove_legacy_user_moderation_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_review_flag_columns, migrations.RunPython.noop
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="review",
                    name="is_featured",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="review",
                    name="admin_notified",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
