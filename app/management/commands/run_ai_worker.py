import threading

from django.core.management.base import BaseCommand

from app.ai_worker import run_once, worker_loop


class Command(BaseCommand):
    help = 'Process durable AI requests (optional dedicated worker service).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one queued request and exit.')

    def handle(self, *args, **options):
        if options['once']:
            run_once()
            return
        stop = threading.Event()
        try:
            worker_loop(stop)
        except KeyboardInterrupt:
            stop.set()
