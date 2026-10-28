from django.core.management.base import BaseCommand
from app.account_deletion import purge_account_media


class Command(BaseCommand):
    help = 'Retry deletion of detached customer files after permanent account removal.'

    def add_arguments(self,parser):
        parser.add_argument('--limit',type=int,default=100)

    def handle(self,*args,**options):
        count = purge_account_media(limit=max(1,options['limit']))
        self.stdout.write(f'Removed {count} detached file(s).')
