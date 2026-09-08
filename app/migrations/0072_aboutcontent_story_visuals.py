from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0071_aboutcontent_hero_visuals'),
    ]

    operations = [
        # The new story-section fields were first added as hero_* fields in 0071,
        # then renamed to story_* once the design moved to the Our Story section.
        migrations.RenameField(
            model_name='aboutcontent',
            old_name='hero_stat_number',
            new_name='story_stat_number',
        ),
        migrations.RenameField(
            model_name='aboutcontent',
            old_name='hero_stat_text',
            new_name='story_stat_text',
        ),
        migrations.RenameField(
            model_name='aboutcontent',
            old_name='hero_points',
            new_name='story_points',
        ),
        migrations.RemoveField(
            model_name='aboutcontent',
            name='hero_image',
        ),
    ]