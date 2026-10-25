from django.core.management.base import BaseCommand, CommandError

from app.signup_lifecycle import prune_pending_signups


class Command(BaseCommand):
    help = 'Remove expired new website signups with no account activity. Legacy accounts are excluded.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Count eligible accounts without deleting them.')
        parser.add_argument('--limit', type=int, default=500, help='Maximum candidate accounts to inspect.')

    def handle(self, *args, **options):
        if options['limit'] < 1:
            raise CommandError('--limit must be at least 1.')
        result = prune_pending_signups(limit=options['limit'], dry_run=options['dry_run'])
        self.stdout.write(self.style.SUCCESS(
            f"Eligible: {result['eligible']}; deleted: {result['deleted']}; protected: {result['protected']}."
        ))
