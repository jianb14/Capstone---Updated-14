"""Private signup continuation and conservative cleanup of new abandoned signups."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import EmailOTPChallenge, User
from .request_protection import RateLimited, consume_rules

RESUME_KEY = 'pending_signup'
OTP_KEY = 'email_otp_signup'


def signup_expired(user):
    return bool(user and user.role == 'customer' and not user.is_staff and not user.is_superuser
                and not user.last_login and user.pending_signup_expires_at
                and user.pending_signup_expires_at <= timezone.now())


def new_signup_expiry():
    return timezone.now() + timedelta(days=settings.PENDING_SIGNUP_RETENTION_DAYS)


def _password_digest(user):
    return salted_hmac('signup-resume', user.password, algorithm='sha256').hexdigest()


def forget_signup(request):
    for key in (RESUME_KEY, OTP_KEY, 'unverified_email'):
        request.session.pop(key, None)


def remember_signup(request, user):
    """Only call after creating the account or validating its original password."""
    from . import email_otp
    context = request.session.get(OTP_KEY, {})
    challenge = email_otp.get_challenge(context, EmailOTPChallenge.SIGNUP)
    if not challenge or challenge.user_id != user.pk or not email_otp.bound(challenge, user, context):
        request.session.pop(OTP_KEY, None)
    request.session.cycle_key()
    password_digest = _password_digest(user)
    request.session[RESUME_KEY] = {
        'user_id': user.pk, 'email': user.email.casefold(), 'password_digest': password_digest,
        'reference': salted_hmac('signup-form', f'{user.pk}:{user.email.casefold()}:{password_digest}',
                                 algorithm='sha256').hexdigest(),
    }


def remembered_signup(request):
    state = request.session.get(RESUME_KEY)
    if not isinstance(state, dict):
        return None
    try:
        user = User.objects.filter(pk=state.get('user_id')).first()
    except (TypeError, ValueError):
        user = None
    if (user and user.is_active and not user.email_verified and not user.is_superuser
            and not signup_expired(user) and user.email.casefold() == state.get('email')
            and constant_time_compare(_password_digest(user), state.get('password_digest', ''))):
        return user
    forget_signup(request)
    return None


def has_account_activity(user):
    """Any related record or assigned permission protects an account from deletion."""
    if any(getattr(user, field.name).exists() for field in user._meta.many_to_many):
        return True
    for relation in user._meta.related_objects:
        if relation.related_model is EmailOTPChallenge:
            continue
        if relation.related_model._base_manager.filter(**{relation.field.name: user}).exists():
            return True
    return False


def discard_failed_signup(identifier):
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=identifier).first()
        if (user and user.is_active and user.pending_signup_expires_at and not user.email_verified
                and not user.is_staff and not user.is_superuser and user.role == 'customer'
                and not user.last_login and not has_account_activity(user)):
            user.delete()


def prune_pending_signups(*, limit=500, dry_run=False, user_ids=None):
    """Lock/recheck each user; never backfill legacy users into this deletion policy."""
    candidates = User.objects.filter(
        pending_signup_expires_at__lte=timezone.now(), email_verified=False,
        role='customer', is_active=True, is_staff=False, is_superuser=False, last_login__isnull=True,
    )
    if user_ids is not None:
        candidates = candidates.filter(pk__in=user_ids)
    ids = list(candidates.order_by('pending_signup_expires_at', 'pk').values_list('pk', flat=True)[:limit])
    result = {'eligible': 0, 'deleted': 0, 'protected': 0}
    for identifier in ids:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=identifier).first()
            if (not user or not user.is_active or user.email_verified or user.is_staff or user.is_superuser
                    or user.role != 'customer' or user.last_login or not signup_expired(user)):
                continue
            if has_account_activity(user):
                result['protected'] += 1
                if not dry_run:
                    # Retain active records permanently and avoid starving later cleanup batches.
                    user.pending_signup_expires_at = None
                    user.save(update_fields=['pending_signup_expires_at'])
                continue
            result['eligible'] += 1
            if not dry_run:
                user.delete()
                result['deleted'] += 1
    return result


def process_signup_cleanup():
    """One bounded batch per interval across all web workers/replicas."""
    if not settings.PENDING_SIGNUP_CLEANUP_ENABLED:
        return None
    try:
        consume_rules([('signup-cleanup', 'global', 1, settings.PENDING_SIGNUP_CLEANUP_INTERVAL_SECONDS, 1)], force=True)
    except RateLimited:
        return None
    return prune_pending_signups(limit=settings.PENDING_SIGNUP_CLEANUP_BATCH_SIZE)
