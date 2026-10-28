from django.db import migrations


def preserve_asset_names(apps, schema_editor):
    Asset = apps.get_model('app', 'CanvasAsset')
    for asset in Asset.objects.using(schema_editor.connection.alias).filter(label='', label_ref__isnull=False).select_related('label_ref').iterator():
        asset.label = asset.label_ref.name
        asset.save(using=schema_editor.connection.alias, update_fields=['label'])


class Migration(migrations.Migration):
    dependencies = [('app', '0115_secure_admin_invitations')]
    operations = [
        migrations.RunPython(preserve_asset_names, migrations.RunPython.noop),
        migrations.AlterModelOptions(name='canvasasset', options={'ordering': ['category__order', 'subgroup', 'sort_order', 'id']}),
        migrations.RemoveField(model_name='canvasasset', name='label_ref'),
        migrations.DeleteModel(name='CanvasLabel'),
    ]
