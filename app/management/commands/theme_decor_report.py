"""Report existing Theme Decor configuration without changing package semantics."""
from django.core.management.base import BaseCommand

from app.models import CanvasCategory, OfferInclusion


class Command(BaseCommand):
    help = 'Report Theme Decor categories, default assets, and service inclusions needing review. Makes no changes.'

    def handle(self, **options):
        for category in CanvasCategory.objects.filter(name__iexact='Theme Decor'):
            self.stdout.write(f'Category #{category.pk}: {category.name}; identity={category.builtin_key or "ordinary"}; catalog assets={category.assets.count()}')
        rows = OfferInclusion.objects.filter(name__iexact='Theme Decor').select_related('offer__package', 'offer__entrance', 'offer__stand')
        for row in rows:
            self.stdout.write(f'{row.offer.name}: {row.row_type}; category={row.category_id or "none"}; quantity={row.quantity if row.quantity is not None else "Included"}; minimum={row.required_minimum}')
