"""Shared, database-backed email OTP lifecycle; no plaintext persistence."""
import math
import re
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import EmailOTPChallenge, RequestRateBucket, User
from .request_protection import bucket_key, client_ip, consume_rules
from .signup_lifecycle import signup_expired


def digest(label, value):
    return salted_hmac('balloorina.email-otp.' + label, value, algorithm='sha256').hexdigest()


def session_key(purpose):
    return 'email_otp_' + purpose


def new_context(email):
    return {
        'id': str(uuid.uuid4()), 'binding': secrets.token_urlsafe(32),
        'email': email.strip().casefold(), 'issued_at': timezone.now().isoformat(),
    }


def mask_email(email):
    local, _, domain = email.partition('@')
    return local[:1] + '***@' + domain


def eligible(user, purpose):
    if not user or not user.is_active or user.deleted_at:
        return False
    if purpose == EmailOTPChallenge.SIGNUP:
        return user.role == 'customer' and not user.email_verified and not user.is_superuser and not signup_expired(user)
    if purpose == EmailOTPChallenge.DELETE:
        return user.role == 'customer' and not user.is_staff and not user.is_superuser and user.has_usable_password() and user.email_verified
    return (purpose in (EmailOTPChallenge.RESET, EmailOTPChallenge.CHANGE) and user.has_usable_password()
            and not (user.role == 'admin' and not user.email_verified))


def invalidate(user, purpose):
    EmailOTPChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(
        consumed_at=timezone.now(), code_digest='', pending_password_hash='')


def lock_email_address(email):
    """Serialize signup and pending email replacement without changing legacy users."""
    RequestRateBucket.objects.select_for_update().get_or_create(
        key=bucket_key('account-email', email.casefold()),
        defaults={'expires_at': timezone.now() + timedelta(days=3650)},
    )


def code_digest(challenge, code):
    value = f'{challenge.pk}:{challenge.user_id}:{challenge.purpose}:{challenge.email_snapshot}:{code}'
    # Preserve the digest of codes already issued before this migration.
    if challenge.replacement_email:
        value += ':' + challenge.replacement_email
    return digest('code', value)


def send_code(user, purpose, context, *, replacement_email='', pending_password_hash='', expected_password=None):
    """Keep an older code usable if transport fails; activate only accepted mail."""
    code = f'{secrets.randbelow(1000000):06d}'
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        recipient = replacement_email or user.email.casefold()
        if (not eligible(user, purpose) or recipient != context['email']
                or (expected_password is not None and not constant_time_compare(user.password, expected_password))
                or (replacement_email and purpose != EmailOTPChallenge.SIGNUP)
                or (purpose == EmailOTPChallenge.CHANGE and not pending_password_hash)):
            return False
        previous = list(EmailOTPChallenge.objects.filter(
            user=user, purpose=purpose, consumed_at__isnull=True, sent_at__isnull=False).exclude(code_digest=''))
        # A random collision must not make an old, still-active code valid after a resend.
        for _ in range(10):
            if not any(constant_time_compare(item.code_digest, code_digest(item, code)) for item in previous):
                break
            code = f'{secrets.randbelow(1000000):06d}'
        else:
            raise RuntimeError('Unable to generate a fresh verification code.')
        challenge = EmailOTPChallenge(
            id=context['id'], user=user, purpose=purpose, email_snapshot=user.email.casefold(),
            replacement_email=replacement_email, pending_password_hash=pending_password_hash,
            session_digest=digest('session', context['binding']),
            password_digest=digest('password', user.password),
            expires_at=timezone.now() + timedelta(seconds=settings.EMAIL_OTP_TIMEOUT),
        )
        challenge.code_digest = code_digest(challenge, code)
        challenge.save()
    label = {EmailOTPChallenge.SIGNUP: 'account verification', EmailOTPChallenge.RESET: 'password reset',
             EmailOTPChallenge.CHANGE: 'password change', EmailOTPChallenge.DELETE:'account deletion'}[purpose]
    subject = {'signup': 'Verify your Balloorina account', 'reset': 'Balloorina Password Reset',
               'change': 'Confirm your Balloorina password change', 'delete':'Confirm your Balloorina account deletion'}[purpose]
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Your {label} code is:\n\n'
        f'{code}\n\n'
        f'This code expires in {settings.EMAIL_OTP_TIMEOUT // 60} minutes and can be used once.\n'
        'Do not share this code. If you did not request it, ignore this email.'
    )
    try:
        accepted = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        if accepted != 1:
            raise RuntimeError('OTP email was not accepted by the email provider.')
    except Exception:
        EmailOTPChallenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='', pending_password_hash='')
        raise
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        challenge = EmailOTPChallenge.objects.select_for_update().get(pk=challenge.pk)
        newer_sent = EmailOTPChallenge.objects.filter(
            user=user, purpose=purpose, created_at__gt=challenge.created_at, sent_at__isnull=False).exists()
        if (not eligible(user, purpose) or user.email.casefold() != challenge.email_snapshot
                or not constant_time_compare(challenge.password_digest, digest('password', user.password))
                or challenge.consumed_at or newer_sent):
            EmailOTPChallenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='', pending_password_hash='')
            return False
        EmailOTPChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).exclude(
            pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='', pending_password_hash='')
        challenge.sent_at = timezone.now()
        challenge.expires_at = challenge.sent_at + timedelta(seconds=settings.EMAIL_OTP_TIMEOUT)
        challenge.save(update_fields=['sent_at', 'expires_at'])
    return True


def get_challenge(context, purpose, lock=False):
    try:
        identifier = uuid.UUID(context['id'])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    query = EmailOTPChallenge.objects
    if lock:
        query = query.select_for_update()
    return query.filter(pk=identifier, purpose=purpose).first()


def bound(challenge, user, context):
    return bool(challenge and user and challenge.sent_at and not challenge.consumed_at
                and user.is_active and not user.deleted_at and user.email.casefold() == challenge.email_snapshot
                and context.get('email') == (challenge.replacement_email or challenge.email_snapshot)
                and constant_time_compare(challenge.session_digest, digest('session', context.get('binding', '')))
                and constant_time_compare(challenge.password_digest, digest('password', user.password)))


def grant_valid(challenge, user, context):
    return bool(eligible(user, EmailOTPChallenge.RESET) and bound(challenge, user, context) and challenge.purpose == EmailOTPChallenge.RESET
                and challenge.verified_at and challenge.grant_expires_at
                and challenge.grant_expires_at > timezone.now())


def verification_wait(context, purpose, challenge):
    """Keep the account lockout visible after refresh or resend."""
    scope = 'email-otp:wrong:' + purpose
    keys = [bucket_key(scope, context.get('email', ''))]
    if challenge:
        keys.append(bucket_key(scope + ':account', str(challenge.user_id)))
    bucket = RequestRateBucket.objects.filter(
        pk__in=keys, count__gte=settings.EMAIL_OTP_MAX_ATTEMPTS,
        expires_at__gt=timezone.now(),
    ).order_by('-expires_at').first()
    return max(1, math.ceil((bucket.expires_at - timezone.now()).total_seconds())) if bucket else 0


def verify_code(request, purpose, context, code):
    """Return (accepted, retry_after). Wrong guesses commit even at the limit."""
    consume_rules([('email-otp:verify:ip', client_ip(request), settings.EMAIL_OTP_VERIFY_PER_IP,
                    settings.EMAIL_OTP_ATTEMPT_WINDOW, 1)], force=True)
    challenge = get_challenge(context, purpose)
    scope = 'email-otp:wrong:' + purpose
    identity = context.get('email', '')
    keys = [bucket_key(scope, identity)]
    with transaction.atomic():
        # Always lock the user before its challenge; issuance/reset/legacy flows use the same order.
        user = User.objects.select_for_update().filter(pk=challenge.user_id).first() if challenge else None
        challenge = get_challenge(context, purpose, lock=True)
        rules = [(scope, identity, settings.EMAIL_OTP_MAX_ATTEMPTS, settings.EMAIL_OTP_ATTEMPT_WINDOW, 1)]
        if user:
            account_scope = scope + ':account'
            rules.append((account_scope, str(user.pk), settings.EMAIL_OTP_MAX_ATTEMPTS, settings.EMAIL_OTP_ATTEMPT_WINDOW, 1))
            keys.append(bucket_key(account_scope, str(user.pk)))
        consume_rules(rules, force=True)
        valid = (bound(challenge, user, context) and eligible(user, purpose)
                 and not challenge.verified_at and challenge.expires_at > timezone.now()
                 and re.fullmatch(r'[0-9]{6}', code or '')
                 and constant_time_compare(challenge.code_digest, code_digest(challenge, code)))
        if purpose == EmailOTPChallenge.CHANGE:
            valid = valid and request.user.is_authenticated and request.user.pk == user.pk and bool(challenge.pending_password_hash)
        if purpose == EmailOTPChallenge.DELETE:
            valid = valid and request.user.is_authenticated and user is not None and request.user.pk == user.pk
        if valid:
            # Only wrong guesses count against the account budget.
            RequestRateBucket.objects.filter(pk__in=keys, count__gt=0).update(count=F('count') - 1)
            challenge.verified_at = timezone.now()
            challenge.code_digest = ''
            if purpose == EmailOTPChallenge.SIGNUP:
                if challenge.replacement_email:
                    lock_email_address(challenge.replacement_email)
                    if User.objects.filter(email__iexact=challenge.replacement_email).exclude(pk=user.pk).exists():
                        raise ValidationError('This email is already registered. Choose another email address.')
                    user.email = challenge.replacement_email
                user.email_verified = True
                user.pending_signup_expires_at = None
                user.save(update_fields=['email', 'email_verified', 'pending_signup_expires_at'])
                invalidate(user, purpose)
                if challenge.replacement_email:
                    invalidate(user, EmailOTPChallenge.RESET)
                    invalidate(user, EmailOTPChallenge.CHANGE)
            elif purpose == EmailOTPChallenge.CHANGE:
                user.password = challenge.pending_password_hash
                user.save(update_fields=['password'])
                invalidate(user, EmailOTPChallenge.RESET)
                invalidate(user, EmailOTPChallenge.CHANGE)
                challenge.pending_password_hash = ''
            else:
                challenge.grant_expires_at = timezone.now() + timedelta(seconds=settings.EMAIL_OTP_RESET_TIMEOUT)
            challenge.save(update_fields=['verified_at', 'code_digest', 'grant_expires_at', 'pending_password_hash'])
            return True, 0
        if challenge and bound(challenge, user, context):
            EmailOTPChallenge.objects.filter(pk=challenge.pk).update(failed_attempts=F('failed_attempts') + 1)
        bucket = RequestRateBucket.objects.filter(pk__in=keys, count__gte=settings.EMAIL_OTP_MAX_ATTEMPTS).order_by('-expires_at').first()
        if bucket:
            return False, max(1, math.ceil((bucket.expires_at - timezone.now()).total_seconds()))
        return False, 0


def reset_password(context, password):
    challenge = get_challenge(context, EmailOTPChallenge.RESET)
    if not challenge:
        return False
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=challenge.user_id)
        challenge = get_challenge(context, EmailOTPChallenge.RESET, lock=True)
        if not grant_valid(challenge, user, context):
            return False
        validate_password(password, user=user)
        user.set_password(password)
        user.save(update_fields=['password'])
        invalidate(user, EmailOTPChallenge.RESET)
        invalidate(user, EmailOTPChallenge.CHANGE)
        return user
