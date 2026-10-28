"""Permanent credential/profile removal with preserved, anonymized transactions."""
import hashlib
import logging
import uuid
from collections import defaultdict
from decimal import Decimal

from django.apps import apps
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.db.models import Q, F
from django.urls import reverse
from django.utils import timezone

from . import email_otp
from .models import (AccountMediaRemoval, User, Booking, Payment, BookingChangeRequest,
    BookingChangeImage, BookingImage, BookingDesignDelivery, Design, Review, ReviewImage,
    UserDesign, ChatSession, ChatMessage, AiRequest, AiGeneratedImage, AiImageFeedback,
    ChatModerationState, ChatModerationEvent, ChatNotification, MessageReaction, BookingStatusLog, ConcernTicket, ConcernImage, Notification,
    AdminNotification, AuditLog, EmailOTPChallenge)

logger = logging.getLogger(__name__)


def deletion_blockers(user, *, lock=False):
    """Read every booking; never trust a cached balance/payment_status flag."""
    bookings = Booking.objects.filter(user=user).order_by('pk')
    payments = Payment.objects.filter(booking__user=user).order_by('pk')
    changes = BookingChangeRequest.objects.filter(booking__user=user).order_by('pk')
    if lock:
        bookings = bookings.select_for_update()
        payments = payments.select_for_update()
        changes = changes.select_for_update()
    bookings, payments, changes = list(bookings), list(payments), list(changes)
    by_booking, revisions = defaultdict(list), defaultdict(list)
    for payment in payments: by_booking[payment.booking_id].append(payment)
    for change in changes: revisions[change.booking_id].append(change)
    blockers = []
    for booking in bookings:
        reasons = []
        if booking.status not in ('completed','cancelled','expired'):
            reasons.append('Your cancellation request is still being processed.' if booking.status == 'cancel_requested'
                else 'This booking is still active. Complete it or finalize its cancellation first.')
        paid = sum((payment.amount for payment in by_booking[booking.pk]
            if payment.payment_status == 'verified' and payment.applied_to_booking),Decimal('0.00'))
        balance = max(Decimal('0.00'),booking.total_price-paid)
        # A cancelled/expired quotation is not an outstanding invoice.
        if booking.status == 'completed' and balance > 0:
            reasons.append(f'This completed booking has an unpaid balance of PHP {balance:,.2f}.')
        for payment in by_booking[booking.pk]:
            abandoned = (payment.payment_method.startswith('paymongo_') and not payment.received_at
                and not payment.paymongo_payment_id and not payment.receipt_image
                and any(word in (payment.notes or '').lower() for word in ('did not complete','cancelled','left the paymongo checkout','expired','failed')))
            if payment.payment_status == 'pending' and not abandoned:
                reasons.append('A payment or checkout still needs to be finalized or verified.')
            if payment.payment_status == 'verified' and not payment.applied_to_booking:
                reasons.append('An additional payment still needs to be reconciled by our team.')
        if any(change.status in BookingChangeRequest.ACTIVE_STATUSES for change in revisions[booking.pk]):
            reasons.append('A booking change request is still being processed.')
        if reasons:
            blockers.append({'booking_id':booking.pk,'title':f'Booking #{booking.pk}',
                'event_type':booking.event_type or 'Event','date':booking.event_date.isoformat(),
                'reasons':list(dict.fromkeys(reasons)),
                'booking_url':reverse('customer_profile')+f'?booking_id={booking.pk}&modal=details',
                'payments_url':reverse('my_payments')})
    return blockers


def queue_account_media(names):
    """Queue detached files, including late results of cancelled AI work."""
    for name in set(filter(None,names)):
        AccountMediaRemoval.objects.get_or_create(key=hashlib.sha256(name.encode()).hexdigest(),defaults={'name':name})


def _queue_files(queryset, field_name):
    queue_account_media(queryset.exclude(**{field_name:''}).exclude(**{field_name:None}).values_list(field_name,flat=True).distinct())


def purge_account_media(*, limit=100):
    """Delete detached files, protect shared files and retry storage outages later."""
    fields = [(model,field.name) for model in apps.get_app_config('app').get_models()
              for field in model._meta.fields if isinstance(field,models.FileField)]
    removed = 0
    for key in AccountMediaRemoval.objects.order_by('attempted_at','created_at').values_list('pk',flat=True)[:limit]:
        try:
            with transaction.atomic():
                task = AccountMediaRemoval.objects.select_for_update().filter(pk=key).first()
                if not task: continue
                if any(model.objects.filter(**{field:task.name}).exists() for model,field in fields):
                    task.delete()  # Another owner/retained record still uses this file.
                    continue
                AccountMediaRemoval.objects.filter(pk=key).update(attempted_at=timezone.now(),attempts=F('attempts')+1)
                try:
                    default_storage.delete(task.name)
                except Exception:
                    logger.warning('Account media removal deferred for task %s',key)
                    continue
                task.delete()
                removed += 1
        except Exception:
            logger.exception('Account media removal will be retried for task %s',key)
    return removed


def remove_account(user):
    """Caller owns the user/booking/payment locks and a verified deletion grant."""
    owned = Booking.objects.filter(user=user)
    groups = [
        (ReviewImage.objects.filter(review__user=user),'image'),
        (UserDesign.objects.filter(user=user),'thumbnail'),
        (AiGeneratedImage.objects.filter(request__user=user),'image'),
        (ChatMessage.objects.filter(Q(sender=user)|Q(receiver=user)|Q(session__user=user)),'image'),
        (ConcernImage.objects.filter(concern__user=user),'image'),
        (owned,'reference_image'),(BookingImage.objects.filter(booking__user=user),'image'),
        (BookingChangeImage.objects.filter(change_request__booking__user=user),'image'),
        (BookingDesignDelivery.objects.filter(booking__user=user),'image'),
        (Design.objects.filter(booking__user=user),'image'),
        (Payment.objects.filter(booking__user=user),'receipt_image'),
    ]
    for query,field in groups: _queue_files(query,field)
    Review.objects.filter(user=user).delete()
    user.liked_reviews.clear()
    UserDesign.objects.filter(user=user).delete()
    AiImageFeedback.objects.filter(user=user).delete()
    AiRequest.objects.filter(user=user).delete()
    MessageReaction.objects.filter(user=user).delete()
    ChatNotification.objects.filter(user=user).delete()
    ChatMessage.objects.filter(Q(sender=user)|Q(receiver=user)|Q(session__user=user)).delete()
    ChatSession.objects.filter(user=user).delete()
    ChatModerationState.objects.filter(user=user).delete()
    ChatModerationEvent.objects.filter(user=user).delete()
    ConcernTicket.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()
    AdminNotification.objects.filter(user=user).delete()
    AuditLog.objects.filter(user=user).delete()
    EmailOTPChallenge.objects.filter(user=user).delete()
    BookingImage.objects.filter(booking__user=user).delete()
    BookingChangeImage.objects.filter(change_request__booking__user=user).delete()
    BookingDesignDelivery.objects.filter(booking__user=user).delete()
    Design.objects.filter(booking__user=user).delete()
    owned.update(event_location='Removed after account deletion',event_lat=None,event_lng=None,
        venue_landmark='',special_requests='',motto_text='',design_theme='',color_palette='',
        reference_image='',edit_request_reason='',cancel_request_reason='',admin_denial_reason='',
        edit_original_snapshot=None)
    BookingChangeRequest.objects.filter(booking__user=user).update(
        reason='Removed after account deletion',original={},proposed={},quote={},admin_notes='')
    BookingStatusLog.objects.filter(booking__user=user).update(notes='')
    Payment.objects.filter(booking__user=user).update(receipt_image='',gcash_sender_name='',
        paymongo_contact_number='',paymongo_checkout_url='',notes='')
    Payment.objects.filter(booking__user=user,payment_status='pending').update(notes='Checkout expired before account deletion.')
    user.groups.clear()
    user.user_permissions.clear()
    user.username = 'deleted_'+uuid.uuid4().hex
    user.first_name, user.last_name = 'Deleted','customer'
    user.email, user.phone_number = '',None
    user.is_active = user.email_verified = False
    user.deleted_at = timezone.now()
    user.last_login = user.pending_signup_expires_at = None
    user.set_unusable_password()
    user.save(update_fields=['username','first_name','last_name','email','phone_number','is_active',
        'email_verified','deleted_at','last_login','pending_signup_expires_at','password'])
    AuditLog.objects.create(user=user,action='Customer permanently removed their account. Anonymous transaction records retained.')
    # Metadata commits first. Failed physical deletions stay in the durable retry queue.
    transaction.on_commit(lambda:purge_account_media(limit=20))
