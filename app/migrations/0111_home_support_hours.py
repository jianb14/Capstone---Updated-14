from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0110_concern_submission_and_cancellation')]

    operations = [
        migrations.AddField(
            model_name='homecontent',
            name='support_hours',
            field=models.PositiveSmallIntegerField(default=11,
                validators=[MinValueValidator(1), MaxValueValidator(24)],
                help_text='Hours of customer support available per day.'),
        ),
    ]
