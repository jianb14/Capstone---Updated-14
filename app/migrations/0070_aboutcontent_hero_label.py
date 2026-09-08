from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0069_homecontent_cta_primary_text_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='aboutcontent',
            name='hero_label',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]