from django.core.management.base import BaseCommand
from django.utils import timezone

from app.models import RequestRateBucket, SubmissionReceipt


class Command(BaseCommand):
    help = 'Remove expired request counters and short-lived submission response receipts.'

    def handle(self, *args, **options):
        removed = 0
        for model in (RequestRateBucket, SubmissionReceipt):
            while True:
                keys = list(model.objects.filter(expires_at__lte=timezone.now()).values_list('pk', flat=True)[:500])
                if not keys:
                    break
                count, _ = model.objects.filter(pk__in=keys, expires_at__lte=timezone.now()).delete()
                removed += count
        self.stdout.write(self.style.SUCCESS(f'Removed {removed} expired request-protection records.'))
