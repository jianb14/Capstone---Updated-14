import re
from django.db import migrations


def seed(apps, schema_editor):
    Offer = apps.get_model('app', 'DesignOffer')
    Design = apps.get_model('app', 'UserDesign')
    Category = apps.get_model('app', 'CanvasCategory')
    Asset = apps.get_model('app', 'CanvasAsset')
    for kind, model, owner in [('package', 'Package', 'package'), ('entrance', 'AddOn', 'entrance'), ('stand', 'AdditionalOnly', 'stand')]:
        for item in apps.get_model('app', model).objects.all():
            match = re.search(r'max\s+(\d+)\s+colors', item.features or '', re.I)
            offer, _ = Offer.objects.get_or_create(kind=kind, **{owner + '_id': item.pk}, defaults={
                'max_balloon_colors': int(match.group(1)) if match else None,
            })
            if kind == 'package':
                Design.objects.filter(base_package_id=item.pk, design_offer__isnull=True).update(design_offer_id=offer.pk)
    for name, kind in [('Panels', 'package'), ('Arch Frames', 'entrance'), ('Stand Frames', 'stand')]:
        Category.objects.get_or_create(name=name, defaults={
            'available_package': kind == 'package', 'available_entrance': kind == 'entrance',
            'available_stand': kind == 'stand',
        })
    category, _ = Category.objects.get_or_create(name='Styrofoam Name')
    Asset.objects.get_or_create(category=category, item_type='i-text', label='Styrofoam Name', defaults={'width': 300, 'height': 80})


class Migration(migrations.Migration):
    dependencies = [('app', '0098_design_offer_requirements')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
