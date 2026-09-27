from django.db import migrations, models
import django.utils.timezone


def create_missing_confirmed_logs(apps, schema_editor):
    """Backfill: gumawa ng missing 'confirmed' log entry para sa mga booking
    na naging confirmed/completed via payment verification (bago pa maidagdag
    ang logging sa payments flow)."""
    Booking = apps.get_model("app", "Booking")
    BookingStatusLog = apps.get_model("app", "BookingStatusLog")

    for booking in Booking.objects.filter(status__in=["confirmed", "completed"]):
        has_confirmed_log = BookingStatusLog.objects.filter(
            booking_id=booking.id, new_status="confirmed"
        ).exists()
        if has_confirmed_log:
            continue

        log = BookingStatusLog.objects.create(
            booking_id=booking.id,
            old_status="pending_payment",
            new_status="confirmed",
            changed_by_id=None,
            notes="Payment verified. Booking confirmed.",
        )
        # auto_now_add ang created_at, kaya i-update manually para tugma sa
        # huling pagbabago ng booking (approximate ng totoong transition time)
        timestamp = booking.updated_at or timezone.now()
        BookingStatusLog.objects.filter(pk=log.pk).update(created_at=timestamp)


def reverse_backfill(apps, schema_editor):
    Booking = apps.get_model("app", "Booking")
    BookingStatusLog = apps.get_model("app", "BookingStatusLog")

    confirmed_ids = list(
        Booking.objects.filter(
            status__in=["confirmed", "completed"]
        ).values_list("id", flat=True)
    )
    BookingStatusLog.objects.filter(
        booking_id__in=confirmed_ids,
        new_status="confirmed",
        notes="Payment verified. Booking confirmed.",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0084_aiimagefeedback"),
    ]

    operations = [
        migrations.RunPython(create_missing_confirmed_logs, reverse_backfill),
    ]