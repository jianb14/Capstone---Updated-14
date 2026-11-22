from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0123_map_theme_decor_inclusions')]

    operations = [
        migrations.AddField(
            model_name='canvasupload',
            name='library_removed_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
