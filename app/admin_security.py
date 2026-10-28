"""Admin email bootstrap and password/OTP-authorized, recipient-owned invitations."""
import re
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.dateparse import parse_datetime

from .email_otp import digest, lock_email_address
from .models import AdminInvitation, AdminSecurityChallenge, AuditLog, User
from .request_protection import client_ip, consume_rules

SESSION_BINDING = 'admin_security_binding'
INVITE_PROOF = 'admin_invitation_proof'


class SecurityError(Exception):
    def __init__(self, message, status=400, code=None):
        self.message, self.status, self.code = message, status, code
        super().__init__(message)


def active_admin(user):
    return bool(user and user.is_active and user.role == 'admin' and not user.deleted_at and user.has_usable_password())


def can_invite(user):
    if not active_admin(user) or not user.email_verified:
        return False
    # Query current permissions; a cached permission must not survive revocation.
    return bool(user.is_superuser or User.objects.filter(pk=user.pk).filter(
        Q(user_permissions__content_type__app_label='app', user_permissions__codename='invite_administrator') |
        Q(groups__permissions__content_type__app_label='app', groups__permissions__codename='invite_administrator')
    ).exists())


def normalized_email(value):
    value = (value or '').strip().casefold()
    try:
        validate_email(value)
    except ValidationError:
        raise SecurityError('Enter a valid email address.')
    if len(value) > 254:
        raise SecurityError('Email address is too long.')
    return value


def _available_email(email, user_id=None):
    if User.objects.filter(email__iexact=email).exclude(pk=user_id).exists():
        raise SecurityError('This email already belongs to an account. Use a different email; existing accounts cannot be promoted.')


def _check_invitation_target(user, email, payload):
    resend_id = (payload or {}).get('resend_id')
    pending = AdminInvitation.objects.filter(status='pending', expires_at__gt=timezone.now())
    if resend_id:
        try:
            valid_resend = pending.filter(pk=resend_id, created_by=user, email__iexact=email).exists()
        except (ValueError, ValidationError):
            valid_resend = False
        if not valid_resend:
            raise SecurityError('This invitation is no longer pending or its email does not match. Start a new invitation.', 409)
    elif pending.filter(email__iexact=email).exists():
        raise SecurityError('A pending invitation already exists for this email. Use Resend from that invitation.', 409)


def _authorize(user, purpose):
    if not active_admin(user):
        raise SecurityError('An active administrator account is required.', 403)
    if purpose == 'email':
        if user.email_verified:
            raise SecurityError('Your admin email is already verified.', 409)
    elif purpose != 'invite' or not can_invite(user):
        raise SecurityError('Only a verified, authorized administrator can invite admins.', 403)


def _send(subject, body, email):
    try:
        if send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False) != 1:
            raise RuntimeError('Email was not accepted')
    except Exception as exc:
        raise SecurityError('The email could not be sent. No account or email changes were made. Please try again later.', 503) from exc


def _limit(request, operation):
    consume_rules([
        ('admin-security:' + operation + ':actor', str(request.user.pk), 8 if operation == 'send' else 20, 3600, 1),
        ('admin-security:' + operation + ':ip', client_ip(request), 30 if operation == 'send' else 60, 3600, 1),
    ], force=True)


def _preserve_session_after_rehash(request, user):
    # check_password may upgrade an older encoding without changing the secret.
    # Keep this reauthenticated session valid after a successful transaction.
    if request.user.password != user.password:
        update_session_auth_hash(request, user)
        request.user.password = user.password


def _issue_locked(user, purpose, email, payload, binding):
    last = AdminSecurityChallenge.objects.filter(user=user, purpose=purpose).order_by('-created_at').first()
    if last and last.created_at > timezone.now() - timedelta(seconds=60):
        raise SecurityError('Wait 60 seconds before requesting another code.', 429)
    _available_email(email, user.pk if purpose == 'email' else None)
    if purpose == 'invite':
        _check_invitation_target(user, email, payload)
    if purpose == 'email' and AdminInvitation.objects.filter(email__iexact=email, status='pending', expires_at__gt=timezone.now()).exists():
        raise SecurityError('This email has a pending admin invitation. Use another email or revoke that invitation first.')
    recipient = email if purpose == 'email' else user.email
    code = f'{secrets.randbelow(1000000):06d}'
    challenge = AdminSecurityChallenge.objects.create(
        user=user, purpose=purpose, email_snapshot=user.email, target_email=email, payload=payload,
        session_digest=digest('admin-session', binding), password_digest=digest('admin-password', user.password),
        code_digest=digest('admin-code', code), expires_at=timezone.now() + timedelta(minutes=5))
    description = ('verify your admin email' if purpose == 'email' else f'authorize an admin invitation for {email}')
    _send('Balloorina admin verification code',
          f'Your code to {description} is {code}.\n\nIt expires in 5 minutes. Never share this code. '
          'If you did not request it, do not use it and secure your admin password.', recipient)
    AdminSecurityChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).exclude(pk=challenge.pk).update(
        consumed_at=timezone.now(), code_digest='')
    AuditLog.objects.create(user=user, action=f'Admin security verification requested ({purpose}).')
    return challenge, recipient


def issue_challenge(request, purpose, password, email, payload=None):
    _limit(request, 'send')
    email = normalized_email(email)
    binding = request.session.get(SESSION_BINDING) or secrets.token_urlsafe(32)
    request.session[SESSION_BINDING] = binding
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        _authorize(user, purpose)
        if not user.check_password(password or ''):
            raise SecurityError('Your current password is incorrect.')
        data = {**(payload or {}), '_reauth_at': timezone.now().isoformat()}
        challenge, recipient = _issue_locked(user, purpose, email, data, binding)
    _preserve_session_after_rehash(request, user)
    request.session['admin_security_' + purpose] = str(challenge.pk)
    return recipient


def _reauth_current(challenge):
    try:
        started = parse_datetime(challenge.payload.get('_reauth_at', '')) or challenge.created_at
        return timezone.is_aware(started) and timedelta(0) <= timezone.now() - started < timedelta(minutes=15)
    except (TypeError, ValueError):
        return False


def resend_challenge(request, purpose):
    """Resend the same operation using recent password proof; never trust POST details."""
    _limit(request, 'send')
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        _authorize(user, purpose)
        try:
            previous = AdminSecurityChallenge.objects.select_for_update().filter(
                pk=request.session.get('admin_security_' + purpose), user=user, purpose=purpose).first()
        except (ValueError, ValidationError):
            previous = None
        binding = request.session.get(SESSION_BINDING, '')
        if not _proof_bound(previous, user, binding, allow_expired=True) or not _reauth_current(previous):
            raise SecurityError('Confirm your current password to send a new code. Your details are saved.', 409, 'reauth_required')
        # Preserve the original password-confirmation time across all resends.
        payload = {**previous.payload, '_reauth_at': previous.payload.get('_reauth_at') or previous.created_at.isoformat()}
        challenge, recipient = _issue_locked(user, purpose, previous.target_email, payload, binding)
    request.session['admin_security_' + purpose] = str(challenge.pk)
    return recipient


def _proof_bound(challenge, user, binding, *, allow_expired=False):
    return bool(challenge and not challenge.consumed_at and (allow_expired or challenge.expires_at > timezone.now())
        and challenge.failed_attempts < 5 and challenge.email_snapshot.casefold() == user.email.casefold()
        and constant_time_compare(challenge.password_digest, digest('admin-password', user.password))
        and constant_time_compare(challenge.session_digest, digest('admin-session', binding)))


def challenge_timing(challenge):
    now = timezone.now()
    resend_at = challenge.created_at + timedelta(seconds=60)
    return {'server_now': now.isoformat(), 'expires_at': challenge.expires_at.isoformat(),
            'resend_available_at': resend_at.isoformat(),
            'expires_in': max(0, math.ceil((challenge.expires_at - now).total_seconds())),
            'resend_after': max(0, math.ceil((resend_at - now).total_seconds()))}


def pending_challenge(request, purpose):
    """Restore an unfinished form without disclosing a code or any password."""
    try:
        _authorize(request.user, purpose)
        challenge = AdminSecurityChallenge.objects.filter(
            pk=request.session.get('admin_security_' + purpose), user=request.user, purpose=purpose).first()
    except (SecurityError, ValueError, ValidationError):
        return {}
    if not _proof_bound(challenge, request.user, request.session.get(SESSION_BINDING, ''), allow_expired=True):
        return {}
    return {'email': challenge.target_email, 'recipient': challenge.target_email if purpose == 'email' else request.user.email,
            'first_name': challenge.payload.get('first_name', ''), 'last_name': challenge.payload.get('last_name', ''),
            'phone_number': challenge.payload.get('phone_number', ''), 'resend_id': challenge.payload.get('resend_id', ''),
            'stage': ('code' if challenge.expires_at > timezone.now() else 'expired' if _reauth_current(challenge) else 'details'),
            **challenge_timing(challenge)}


def _locked_proof(request, purpose, code):
    """Wrong attempts commit before raising; success remains locked until the action commits."""
    user = User.objects.select_for_update().get(pk=request.user.pk)
    _authorize(user, purpose)
    try:
        challenge = AdminSecurityChallenge.objects.select_for_update().filter(
            pk=request.session.get('admin_security_' + purpose), user=user, purpose=purpose).first()
    except (ValueError, ValidationError):
        challenge = None
    valid_binding = _proof_bound(challenge, user, request.session.get(SESSION_BINDING, ''))
    if not valid_binding:
        expired = _proof_bound(challenge, user, request.session.get(SESSION_BINDING, ''), allow_expired=True)
        return user, None, SecurityError('This code has expired. Send a new code.' if expired else 'This code is no longer valid. Send a new code.',
                                         400, 'code_expired' if expired else 'code_unavailable')
    if not re.fullmatch(r'\d{6}', code or '', flags=re.ASCII) or not constant_time_compare(challenge.code_digest, digest('admin-code', code)):
        challenge.failed_attempts += 1
        if challenge.failed_attempts >= 5:
            challenge.consumed_at, challenge.code_digest = timezone.now(), ''
        challenge.save(update_fields=['failed_attempts', 'consumed_at', 'code_digest'])
        return user, None, SecurityError('Incorrect code. After 5 incorrect attempts, request a new code.')
    return user, challenge, None


def confirm_challenge(request, purpose, code):
    _limit(request, 'verify')
    # This budget spans resends and sessions, preventing a fresh guessing budget per code.
    consume_rules([('admin-security:code:actor', str(request.user.pk), 10, 600, 1)], force=True)
    result = None
    with transaction.atomic():
        user, challenge, error = _locked_proof(request, purpose, code)
        if challenge:
            lock_email_address(challenge.target_email)
            _available_email(challenge.target_email, user.pk if purpose == 'email' else None)
            if purpose == 'email':
                if AdminInvitation.objects.filter(email__iexact=challenge.target_email, status='pending', expires_at__gt=timezone.now()).exists():
                    raise SecurityError('This email now has a pending invitation. Request a code for another email.')
                user.email, user.email_verified, user.pending_signup_expires_at = challenge.target_email, True, None
                user.save(update_fields=['email', 'email_verified', 'pending_signup_expires_at'])
                AuditLog.objects.create(user=user, action='Admin verified their own email using current password and email code.')
                result = user
            else:
                result = _issue_invitation(request, user, challenge)
            challenge.consumed_at, challenge.code_digest = timezone.now(), ''
            challenge.save(update_fields=['consumed_at', 'code_digest'])
    if error:
        raise error
    request.session.pop('admin_security_' + purpose, None)
    if purpose == 'email':
        request.session.pop('admin_email_setup_required', None)
    return result


def _issue_invitation(request, user, challenge):
    now = timezone.now()
    AdminInvitation.objects.filter(email__iexact=challenge.target_email, status='pending', expires_at__lte=now).update(status='expired', token_digest='')
    invitation = AdminInvitation.objects.select_for_update().filter(email__iexact=challenge.target_email, status='pending').first()
    resend_id = challenge.payload.get('resend_id')
    if invitation and (not resend_id or str(invitation.pk) != resend_id or invitation.created_by_id != user.pk):
        raise SecurityError('A pending invitation already exists for this email. Use Resend from that invitation.', 409)
    if resend_id and not invitation:
        raise SecurityError('This invitation is no longer pending. Start a new invitation.', 409)
    token = secrets.token_urlsafe(32)
    fields = dict(email=challenge.target_email, first_name=challenge.payload['first_name'], last_name=challenge.payload['last_name'],
        phone_number=challenge.payload['phone_number'], created_by=user, creator_email=user.email,
        creator_password_digest=digest('admin-password', user.password), token_digest=digest('admin-invite', token),
        expires_at=now + timedelta(hours=24))
    if invitation:
        for key, value in fields.items():
            setattr(invitation, key, value)
        invitation.save()
    else:
        invitation = AdminInvitation.objects.create(**fields)
    link = request.build_absolute_uri(reverse('admin_invitation_open', args=[invitation.pk, token]))
    _send('You are invited to administer Balloorina',
        f'Hello {invitation.first_name},\n\nA verified Balloorina administrator invited you to create an admin account. '
        f'Choose your own password using this single-use link within 24 hours:\n\n{link}\n\n'
        'No account is created until you accept. Do not forward this link. If this was unexpected, ignore this email.', invitation.email)
    AuditLog.objects.create(user=user, action=f'Admin invitation {"resent" if resend_id else "sent"} to {invitation.email} (#{invitation.pk}).')
    return invitation


def invitation_valid(invitation, creator, proof):
    return bool(invitation and invitation.status == 'pending' and invitation.expires_at > timezone.now()
        and can_invite(creator) and creator.email.casefold() == invitation.creator_email.casefold()
        and constant_time_compare(invitation.creator_password_digest, digest('admin-password', creator.password))
        and proof and constant_time_compare(invitation.token_digest, proof))


def accept_invitation(proof, password):
    from django.contrib.auth.password_validation import UserAttributeSimilarityValidator, validate_password
    try:
        original = AdminInvitation.objects.get(pk=proof.get('id'))
    except (AdminInvitation.DoesNotExist, ValueError, ValidationError):
        raise SecurityError('This invitation is invalid or no longer available.')
    with transaction.atomic():
        creator = User.objects.select_for_update().filter(pk=original.created_by_id).first()
        # Confirm/resend also lock the address before the invitation. Keep that
        # order across different creators to avoid an address/invitation deadlock.
        lock_email_address(original.email)
        invitation = AdminInvitation.objects.select_for_update().get(pk=original.pk)
        if not invitation_valid(invitation, creator, proof.get('digest')):
            raise SecurityError('This invitation is expired, used, revoked or no longer authorized. Ask the main administrator for a new invitation.')
        _available_email(invitation.email)
        user = User(username='admin_' + secrets.token_hex(16), email=invitation.email, first_name=invitation.first_name,
            last_name=invitation.last_name, phone_number=invitation.phone_number, role='admin', email_verified=True,
            is_active=True, is_staff=False, is_superuser=False)
        try:
            validate_password(password, user=user)
            UserAttributeSimilarityValidator().validate(password, user=user)
        except ValidationError as exc:
            raise SecurityError(' '.join(exc.messages))
        if len(password) < 8 or not re.search(r'[A-Z]', password) or not re.search(r'\d', password) or not re.search(r'[^A-Za-z0-9]', password):
            raise SecurityError('Password must be at least 8 characters and include 1 uppercase letter, 1 number, and 1 special character.')
        user.set_password(password)
        user.save()
        invitation.status, invitation.accepted_user, invitation.accepted_at, invitation.token_digest = 'accepted', user, timezone.now(), ''
        invitation.save(update_fields=['status', 'accepted_user', 'accepted_at', 'token_digest'])
        AuditLog.objects.create(user=user, action=f'Admin invitation accepted (#{invitation.pk}); authorized by account #{creator.pk}.')
        return user


def revoke_invitation(request, invitation_id, password):
    _limit(request, 'revoke')
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        _authorize(user, 'invite')
        if not user.check_password(password or ''):
            raise SecurityError('Your current password is incorrect.')
        invitation = AdminInvitation.objects.select_for_update().filter(pk=invitation_id, status='pending').first()
        if not invitation or (invitation.created_by_id != user.pk and not user.is_superuser):
            raise SecurityError('This pending invitation is not available.', 404)
        invitation.status, invitation.token_digest = 'revoked', ''
        invitation.save(update_fields=['status', 'token_digest'])
        AuditLog.objects.create(user=user, action=f'Admin invitation revoked (#{invitation.pk}).')
    _preserve_session_after_rehash(request, user)
