"""Shared, database-backed email OTP lifecycle; no plaintext persistence."""
import math
import re
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import EmailOTPChallenge, RequestRateBucket, User
from .request_protection import bucket_key, client_ip, consume_rules


def digest(label, value):
    return salted_hmac('balloorina.email-otp.' + label, value, algorithm='sha256').hexdigest()


def session_key(purpose):
    return 'email_otp_' + purpose


def new_context(email):
    return {
        'id': str(uuid.uuid4()), 'binding': secrets.token_urlsafe(32),
        'email': email.strip().casefold(), 'issued_at': timezone.now().isoformat(),
    }


def eligible(user, purpose):
    if not user or not user.is_active:
        return False
    if purpose == EmailOTPChallenge.SIGNUP:
        return not user.email_verified and not user.is_superuser
    return purpose == EmailOTPChallenge.RESET and user.has_usable_password()


def invalidate(user, purpose):
    EmailOTPChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(
        consumed_at=timezone.now(), code_digest='')


def code_digest(challenge, code):
    return digest('code', f'{challenge.pk}:{challenge.user_id}:{challenge.purpose}:{challenge.email_snapshot}:{code}')


def send_code(user, purpose, context):
    """Keep an older code usable if transport fails; activate only accepted mail."""
    code = f'{secrets.randbelow(1000000):06d}'
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if not eligible(user, purpose) or user.email.casefold() != context['email']:
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
            id=context['id'], user=user, purpose=purpose, email_snapshot=context['email'],
            session_digest=digest('session', context['binding']),
            password_digest=digest('password', user.password),
            expires_at=timezone.now() + timedelta(seconds=settings.EMAIL_OTP_TIMEOUT),
        )
        challenge.code_digest = code_digest(challenge, code)
        challenge.save()
    subject = ('Verify your Balloorina account' if purpose == EmailOTPChallenge.SIGNUP
               else 'Balloorina Password Reset')
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Your {"account verification" if purpose == EmailOTPChallenge.SIGNUP else "password reset"} code is:\n\n'
        f'{code}\n\n'
        f'This code expires in {settings.EMAIL_OTP_TIMEOUT // 60} minutes and can be used once.\n'
        'Do not share this code. If you did not request it, ignore this email.'
    )
    try:
        accepted = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        if accepted != 1:
            raise RuntimeError('OTP email was not accepted by the email provider.')
    except Exception:
        EmailOTPChallenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='')
        raise
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        challenge = EmailOTPChallenge.objects.select_for_update().get(pk=challenge.pk)
        newer_sent = EmailOTPChallenge.objects.filter(
            user=user, purpose=purpose, created_at__gt=challenge.created_at, sent_at__isnull=False).exists()
        if (not eligible(user, purpose) or user.email.casefold() != challenge.email_snapshot
                or not constant_time_compare(challenge.password_digest, digest('password', user.password))
                or challenge.consumed_at or newer_sent):
            EmailOTPChallenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='')
            return False
        EmailOTPChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).exclude(
            pk=challenge.pk).update(consumed_at=timezone.now(), code_digest='')
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
                and user.is_active and user.email.casefold() == challenge.email_snapshot
                and context.get('email') == challenge.email_snapshot
                and constant_time_compare(challenge.session_digest, digest('session', context.get('binding', '')))
                and constant_time_compare(challenge.password_digest, digest('password', user.password)))


def grant_valid(challenge, user, context):
    return bool(bound(challenge, user, context) and challenge.purpose == EmailOTPChallenge.RESET
                and challenge.verified_at and challenge.grant_expires_at
                and challenge.grant_expires_at > timezone.now())


def verify_code(request, purpose, context, code):
    """Return (accepted, retry_after). Wrong guesses commit even at the limit."""
    consume_rules([('email-otp:verify:ip', client_ip(request), settings.EMAIL_OTP_VERIFY_PER_IP,
                    settings.EMAIL_OTP_ATTEMPT_WINDOW, 1)], force=True)
    challenge = get_challenge(context, purpose)
    scope = 'email-otp:wrong:' + purpose
    identity = context.get('email', '')
    key = bucket_key(scope, identity)
    with transaction.atomic():
        # Always lock the user before its challenge; issuance/reset/legacy flows use the same order.
        user = User.objects.select_for_update().filter(pk=challenge.user_id).first() if challenge else None
        challenge = get_challenge(context, purpose, lock=True)
        consume_rules([(scope, identity, settings.EMAIL_OTP_MAX_ATTEMPTS, settings.EMAIL_OTP_ATTEMPT_WINDOW, 1)], force=True)
        valid = (bound(challenge, user, context) and eligible(user, purpose)
                 and not challenge.verified_at and challenge.expires_at > timezone.now()
                 and re.fullmatch(r'[0-9]{6}', code or '')
                 and constant_time_compare(challenge.code_digest, code_digest(challenge, code)))
        if valid:
            # Only wrong guesses count against the account budget.
            RequestRateBucket.objects.filter(pk=key, count__gt=0).update(count=F('count') - 1)
            challenge.verified_at = timezone.now()
            challenge.code_digest = ''
            if purpose == EmailOTPChallenge.SIGNUP:
                user.email_verified = True
                user.save(update_fields=['email_verified'])
                invalidate(user, purpose)
            else:
                challenge.grant_expires_at = timezone.now() + timedelta(seconds=settings.EMAIL_OTP_RESET_TIMEOUT)
            challenge.save(update_fields=['verified_at', 'code_digest', 'grant_expires_at'])
            return True, 0
        if challenge and bound(challenge, user, context):
            EmailOTPChallenge.objects.filter(pk=challenge.pk).update(failed_attempts=F('failed_attempts') + 1)
        bucket = RequestRateBucket.objects.filter(pk=key).first()
        if bucket and bucket.count >= settings.EMAIL_OTP_MAX_ATTEMPTS:
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
        return user
