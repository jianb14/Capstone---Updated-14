from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0103_builtin_styro_name')]
    operations = [
        migrations.CreateModel(name='RequestRateBucket', fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('count', models.PositiveBigIntegerField(default=0)),
            ('expires_at', models.DateTimeField(db_index=True)),
        ]),
        migrations.CreateModel(name='SubmissionReceipt', fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('expires_at', models.DateTimeField(db_index=True)),
            ('status_code', models.PositiveSmallIntegerField(default=0)),
            ('body', models.TextField(blank=True)),
            ('headers', models.JSONField(default=dict)),
        ]),
    ]
