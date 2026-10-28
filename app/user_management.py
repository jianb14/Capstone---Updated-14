"""Read-only account management and explicit, email-backed access changes."""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.template.loader import render_to_string

from .account_lists import account_page_size
from .models import AuditLog, Booking, Payment, Review, User

logger = logging.getLogger(__name__)


class UserStatusError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def user_list_context(request):
    from django.core.paginator import Paginator
    from .admin_security import can_invite, pending_challenge

    accounts = User.objects.filter(deleted_at__isnull=True)
    summary = accounts.aggregate(
        total=Count('pk'), active=Count('pk', filter=Q(is_active=True)),
        inactive=Count('pk', filter=Q(is_active=False)),
        customers=Count('pk', filter=Q(role='customer')), admins=Count('pk', filter=Q(role='admin')),
    )
    query = request.GET.get('search', request.GET.get('q', '')).replace('\x00', '').strip()[:150]
    role = request.GET.get('role', '')
    status = request.GET.get('status', '')
    role = role if role in ('admin', 'customer') else ''
    status = status if status in ('active', 'inactive') else ''
    if role:
        accounts = accounts.filter(role=role)
    if status:
        accounts = accounts.filter(is_active=status == 'active')
    for word in query.split():
        match = (Q(username__icontains=word) | Q(first_name__icontains=word)
                 | Q(last_name__icontains=word) | Q(email__icontains=word)
                 | Q(phone_number__icontains=word))
        key = word.removeprefix('#USER-').removeprefix('#')
        if key.isdecimal() and len(key) < 19:
            match |= Q(pk=int(key))
        accounts = accounts.filter(match)
    per_page = account_page_size(request)
    page = Paginator(accounts.order_by('-date_joined', '-pk'), per_page).get_page(request.GET.get('page'))
    return {'users': page, 'user_summary': summary, 'per_page': per_page,
            'search_query': query, 'role_filter': role, 'status_filter': status,
            'has_filters': bool(query or role or status), 'can_invite_admin': can_invite(request.user),
            'pending_invite_security': pending_challenge(request, 'invite')}


def user_details_context(user):
    bookings = Booking.objects.filter(user=user)
    paid = Payment.objects.filter(booking__user=user, payment_status='verified', applied_to_booking=True)
    return {
        'u': user, 'booking_count': bookings.count(),
        'open_booking_count': bookings.exclude(status__in=('completed', 'cancelled', 'expired')).count(),
        'verified_paid': paid.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        'review_count': Review.objects.filter(user=user).count(),
        'user_bookings': bookings.order_by('-created_at', '-pk')[:5],
        'user_payments': Payment.objects.filter(booking__user=user).select_related('booking').order_by('-created_at', '-pk')[:5],
    }


def change_user_access(*, actor_id, target_id, active, expected_active, login_url):
    """Lock both accounts in a stable order; retries never toggle the status back."""
    with transaction.atomic():
        locked = {user.pk: user for user in User.objects.select_for_update()
                  .filter(pk__in={actor_id, target_id}).order_by('pk')}
        actor = locked.get(actor_id)
        if not actor or not actor.is_active or actor.deleted_at or actor.role != 'admin':
            raise UserStatusError('Your administrator session is no longer active. Please sign in again.', 403)
        user = locked.get(target_id)
        if not user or user.deleted_at:
            # Removed transaction owners must never be reactivated.
            raise Http404('Account not found')
        if user.pk == actor.pk:
            raise UserStatusError('You cannot change your own account access.', 403)
        if user.role not in ('admin', 'customer'):
            raise UserStatusError('Access changes are unavailable for this account role.', 403)
        if user.is_active == active:
            return user, False
        if user.is_active != expected_active:
            raise UserStatusError('This account changed while you were reviewing it. Refresh the list and try again.')
        if not active and user.role == 'admin' and not User.objects.filter(
                role='admin', is_active=True, deleted_at__isnull=True).exclude(pk=user.pk).exists():
            raise UserStatusError('The last active administrator cannot be deactivated.', 403)
        try:
            validate_email(user.email or '')
        except ValidationError:
            raise UserStatusError('This account has no valid email address. Its access was not changed.', 400)

        user.is_active = active
        user.save(update_fields=['is_active'])
        verb = 'activated' if active else 'deactivated'
        AuditLog.objects.create(user=actor, action=f'User account #USER-{user.pk} ({user.username}) {verb}; email notification sent.')
        name = user.first_name or user.username
        if active:
            explanation = ('Your access has been restored. You can sign in again.' if user.email_verified
                           else 'Your access has been restored. Complete email verification before signing in.')
        else:
            explanation = 'You can no longer sign in to this account. Contact our support team if you need help.'
        text = (f'Hi {name},\n\nYour Balloorina account has been {verb} by an administrator.\n\n'
                f'{explanation}\n\nYour existing bookings and payment records have not been cancelled or deleted.\n\n'
                + (f'Sign in: {login_url}\n\n' if active else '')
                + 'If you have questions about this change, contact the Balloorina support team.\n\nBalloorina')
        email = EmailMultiAlternatives(
            subject=f'Your Balloorina account has been {verb}', body=text,
            from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email],
        )
        email.attach_alternative(render_to_string('emails/account_access_changed.html', {
            'name': name, 'active': active, 'verb': verb, 'explanation': explanation, 'login_url': login_url,
        }), 'text/html')
        try:
            sent = email.send(fail_silently=False)
            if sent != 1:
                raise RuntimeError('The email backend did not accept the notification.')
        except Exception:
            logger.exception('Account access email failed for user %s; access change rolled back.', user.pk)
            raise UserStatusError('We could not send the account notification email. The account status was not changed. Please try again.', 503)
        return user, True
