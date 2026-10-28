import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0112_customer_account_deletion')]

    operations = [
        migrations.AddField(
            model_name='notification', name='concern',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications', to='app.concernticket')),
        migrations.AlterField(
            model_name='notification', name='booking',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications', to='app.booking')),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(
                check=(models.Q(booking__isnull=False, concern__isnull=True)
                    | models.Q(booking__isnull=True, concern__isnull=False)),
                name='notification_has_one_target')),
    ]
