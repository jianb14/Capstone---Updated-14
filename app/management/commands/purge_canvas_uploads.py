from django.core.management.base import BaseCommand

from app.account_deletion import purge_account_media
from app.canvas_uploads import purge_orphan_uploads


class Command(BaseCommand):
    help = 'Remove unreferenced canvas uploads older than 24 hours and retry queued media removals.'

    def handle(self, **options):
        removed = purge_orphan_uploads()
        purge_account_media()
        self.stdout.write(f'Removed {removed} orphan canvas uploads.')
