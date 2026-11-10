from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0117_galleryimage_package')]

    operations = [migrations.AddField(
        model_name='notification', name='bar_shown_at',
        field=models.DateTimeField(blank=True, null=True),
    )]
