import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0116_remove_canvas_labels')]

    operations = [
        migrations.AddField(
            model_name='galleryimage',
            name='package',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='gallery_images', to='app.package'),
        ),
    ]
