from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0070_aboutcontent_hero_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='aboutcontent',
            name='hero_image',
            field=models.ImageField(blank=True, null=True, upload_to='about_content/'),
        ),
        migrations.AddField(
            model_name='aboutcontent',
            name='hero_stat_number',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='aboutcontent',
            name='hero_stat_text',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='aboutcontent',
            name='hero_points',
            field=models.TextField(blank=True, default=''),
        ),
    ]