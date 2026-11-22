"""Map only the five existing inclusions explicitly approved by the owner."""
from django.db import migrations
from django.db.models import Q


def map_theme_decor(apps, schema_editor):
    alias = schema_editor.connection.alias
    Category = apps.get_model('app', 'CanvasCategory')
    Inclusion = apps.get_model('app', 'OfferInclusion')
    Requirement = apps.get_model('app', 'DesignRequirement')
    category = Category.objects.using(alias).get(builtin_key='theme_decor')
    target = Q(offer__kind='package', offer__package__name__in=['Package 1-B', 'Package 2', 'Package 3', 'Package 4']) | Q(offer__kind='stand', offer__stand__name='Stand B')
    approved_types = Q(row_type='service') | Q(offer__kind='stand', offer__stand__name='Stand B', row_type='item')
    for row in Inclusion.objects.using(alias).filter(target, approved_types, name__iexact='Theme Decor', category__isnull=True):
        existing = Requirement.objects.using(alias).filter(offer_id=row.offer_id, category_id=category.pk).first()
        if existing and (existing.minimum != 0 or existing.required or existing.maximum != row.quantity):
            raise RuntimeError(f'Theme Decor in offer #{row.offer_id} already has a different allowance. Review its existing rule before mapping inclusion #{row.pk}.')
        if Inclusion.objects.using(alias).filter(offer_id=row.offer_id, category_id=category.pk).exists():
            raise RuntimeError(f'Theme Decor is already mapped in offer #{row.offer_id}. Review duplicate inclusion #{row.pk}.')
        row.row_type = 'item'
        row.category_id = category.pk
        row.required_minimum = 0
        row.save(using=alias, update_fields=['row_type', 'category', 'required_minimum'])
        Requirement.objects.using(alias).get_or_create(
            offer_id=row.offer_id, category_id=category.pk,
            defaults={'display_name': row.name, 'required': False, 'minimum': 0, 'maximum': row.quantity})


class Migration(migrations.Migration):
    dependencies = [('app', '0122_category_uploads')]
    operations = [migrations.RunPython(map_theme_decor, migrations.RunPython.noop)]
