from django.core.management.base import BaseCommand

from app.booking_lifecycle import process_booking_deadlines


class Command(BaseCommand):
    help = 'Process booking expirations and overdue design/payment-review alerts once.'

    def handle(self, *args, **options):
        expired = process_booking_deadlines()
        self.stdout.write(self.style.SUCCESS(f'Booking deadlines processed: {expired} booking(s) expired.'))
