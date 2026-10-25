"""Authentication: register, verify, login, password reset, logout. (split from app/views.py)"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int, url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.core.validators import validate_email as validate_email_address
from django.contrib.auth.hashers import make_password
from django.urls import reverse
from django.db import IntegrityError

from .. import email_otp, signup_lifecycle
from ..models import EmailOTPChallenge
from ..request_protection import RateLimited, consume_rules, client_ip

from .common import *  # noqa: F401,F403
from .common import (  # noqa: F401
    _is_reset_request_rate_limited,
    _is_verification_resend_rate_limited,
    _email_request_limit,
)


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Token generator para sa account email verification.

    May sariling ``key_salt`` (hindi interchangeable sa password-reset
    tokens) at mas mahabang expiry (``EMAIL_VERIFICATION_TIMEOUT``, 24 oras
    by default) kaysa sa 30-minute na reset tokens.
    """

    key_salt = "app.views.auth.EmailVerificationTokenGenerator"

    def check_token(self, user, token):
        """Check that a verification token is correct for the given user."""
        if not (user and token):
            return False
        # Parse the token
        try:
            ts_b36, _ = token.split("-")
        except ValueError:
            return False

        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        # Check that the timestamp/uid has not been tampered with
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, ts, secret),
                token,
            ):
                break
        else:
            return False

        # Check the timestamp is within the verification window
        timeout = getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 86400)
        if (self._num_seconds(self._now()) - ts) > timeout:
            return False

        return True


email_verification_token_generator = EmailVerificationTokenGenerator()


def _send_account_verification_email(request, user):
    context = email_otp.new_context(user.email)
    if not email_otp.send_code(user, EmailOTPChallenge.SIGNUP, context):
        raise RuntimeError("Verification code was not accepted by the email provider.")
    request.session[email_otp.session_key(EmailOTPChallenge.SIGNUP)] = context


User = get_user_model()


@never_cache
@sensitive_post_parameters('password', 'confirm_password')
@require_http_methods(['GET', 'POST'])
def register(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        phone = request.POST.get("phone", "").strip()
        role = "customer"

        errors = []

        # Required fields
        if not first_name:
            errors.append("First name is required.")
        if not last_name:
            errors.append("Last name is required.")
        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        elif not re.fullmatch(r"[A-Za-z0-9._%+-]+@gmail\.com", email):
            errors.append(
                "Please enter a valid Gmail address (example: yourname@gmail.com)."
            )
        if not password:
            errors.append("Password is required.")
        if not confirm_password:
            errors.append("Confirm password is required.")
        if not phone:
            errors.append("Phone number is required.")

        # Only an account already owned by this browser can expose its pending status.
        existing_user = User.objects.filter(email__iexact=email).first()
        pending_user = signup_lifecycle.remembered_signup(request)
        if existing_user and pending_user and existing_user.pk == pending_user.pk:
            return render(request, 'auth/register.html', _signup_banner_context(request))

        # Apply storage/format constraints before checking conflicts, so invalid
        # details cannot turn database errors into an account-existence oracle.
        for field_name, value in (('first_name', first_name), ('last_name', last_name),
                                  ('username', username), ('email', email)):
            if value:
                try:
                    User._meta.get_field(field_name).clean(value, None)
                except ValidationError as error:
                    errors.extend(error.messages)

        # Password match
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Password rules
        if password:
            if len(password) < 8:
                errors.append("Password must be at least 8 characters.")
            if not re.search(r"[A-Z]", password):
                errors.append("Password must contain at least 1 uppercase letter.")
            if not re.search(r"\d", password):
                errors.append("Password must contain at least 1 number.")
            if not re.search(r"[^A-Za-z0-9]", password):
                errors.append("Password must contain at least 1 special character.")

        # Phone number validation
        cleaned_phone = re.sub(r"[\s\-\(\)\+]", "", phone)
        if phone and not cleaned_phone.isdigit():
            errors.append("Phone number must contain only digits.")
        elif phone and (len(cleaned_phone) < 10 or len(cleaned_phone) > 15):
            errors.append("Phone number must be between 10 and 15 digits.")

        if errors:
            return render(request, "auth/register.html", {**_signup_banner_context(request), "errors": errors})

        limited, message = _is_verification_resend_rate_limited(request, email)
        if limited:
            return _otp_rate_response(request, message, 'auth/register.html')

        # Reclaim only expired, explicitly marked new signups with no related activity.
        from django.db.models import Q
        collisions = list(User.objects.filter(Q(email__iexact=email) | Q(username=username)).values_list('pk', flat=True))
        if settings.PENDING_SIGNUP_CLEANUP_ENABLED:
            signup_lifecycle.prune_pending_signups(user_ids=collisions, limit=max(1, len(collisions)))
        try:
            with transaction.atomic():
                email_otp.lock_email_address(email)
                if User.objects.filter(Q(email__iexact=email) | Q(username=username)).exists():
                    return _public_registration_result(request, email)
                user = User.objects.create_user(
                    username=username, email=email, password=password, first_name=first_name,
                    last_name=last_name, phone_number=phone, role=role, email_verified=False,
                    pending_signup_expires_at=signup_lifecycle.new_signup_expiry(),
                )
        except IntegrityError:
            # A competing username claim has the same public response as any valid signup.
            return _public_registration_result(request, email)
        except Exception:
            logger.exception("Failed to create user account during registration.")
            errors.append("We could not create your account right now. Please try again in a moment.")
            return render(request, "auth/register.html", {**_signup_banner_context(request), "errors": errors})

        try:
            _send_account_verification_email(request, user)
        except Exception:
            logger.exception("Failed to send account verification email.")
            signup_lifecycle.discard_failed_signup(user.pk)
            errors.append(
                "We could not send a verification email right now. Please try again in a moment."
            )
            return render(request, "auth/register.html", {**_signup_banner_context(request), "errors": errors})

        signup_lifecycle.remember_signup(request, user)
        log_action(None, 'New website signup started. Verification code sent.')
        messages.info(request, _otp_notice(EmailOTPChallenge.SIGNUP))
        return redirect('verify_account_otp')

    return render(request, 'auth/register.html', _signup_banner_context(request))


def _public_registration_result(request, email):
    # Same redirect and notice whether the conflict is an email or a username.
    signup_lifecycle.forget_signup(request)
    request.session[signup_lifecycle.OTP_KEY] = email_otp.new_context(email)
    messages.info(request, _otp_notice(EmailOTPChallenge.SIGNUP))
    return redirect('verify_account_otp')


def _signup_banner_context(request):
    user = signup_lifecycle.remembered_signup(request)
    if not user:
        return {}
    context = request.session.get(signup_lifecycle.OTP_KEY, {})
    challenge = email_otp.get_challenge(context, EmailOTPChallenge.SIGNUP)
    email = context['email'] if (challenge and challenge.user_id == user.pk
        and email_otp.bound(challenge, user, context)) else user.email
    return {'pending_signup': True, 'masked_pending_email': email_otp.mask_email(email),
            'login_email': user.email, 'pending_expires_at': user.pending_signup_expires_at,
            'signup_reference': request.session[signup_lifecycle.RESUME_KEY].get('reference', '')}


@never_cache
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def verify_email(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = (User.objects.select_for_update() if request.method == 'POST' else User.objects).get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if not user or not email_verification_token_generator.check_token(user, token):
        messages.info(request, 'This verification link is invalid or expired. Log in to continue verification.')
        return redirect('login')
    if user.email_verified:
        return redirect('login')
    if signup_lifecycle.signup_expired(user):
        messages.info(request, 'This signup has expired. Please register again.')
        return redirect('register')

    if request.method == 'GET':
        return render(request, 'auth/verify_email_link.html')

    user.email_verified = True
    user.pending_signup_expires_at = None
    user.save(update_fields=['email_verified', 'pending_signup_expires_at'])
    email_otp.invalidate(user, EmailOTPChallenge.SIGNUP)
    if request.session.get(signup_lifecycle.RESUME_KEY, {}).get('user_id') == user.pk:
        signup_lifecycle.forget_signup(request)
    log_action(user, "Email verified.")
    messages.success(request, "Email verified successfully. You can now log in.")
    return redirect("login")


User = get_user_model()


@never_cache
@sensitive_post_parameters('password')
@require_http_methods(['GET', 'POST'])
def user_login(request):
    request.session.pop('unverified_email', None)
    return_to = request.POST.get('next') or request.GET.get('next')
    if return_to and url_has_allowed_host_and_scheme(
        return_to, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        request.session['login_return_to'] = return_to

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password")

        # Try to get user by email
        try:
            user_obj = User.objects.get(email__iexact=email)
            username = user_obj.username  # Django authenticate needs username
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return render(
                request, "auth/login.html", {"error": "Invalid email or password."}
            )

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_superuser and not getattr(user, "email_verified", True):
                if signup_lifecycle.signup_expired(user):
                    signup_lifecycle.forget_signup(request)
                    messages.info(request, 'This signup has expired. Please register again.')
                    return redirect('register')
                signup_lifecycle.remember_signup(request, user)
                return render(request, 'auth/login.html', _signup_banner_context(request))

            signup_lifecycle.forget_signup(request)
            login(request, user)

            log_action(user, "User logged in.")
            if request.POST.get("remember_me"):
                request.session.set_expiry(1209600)  # 2 weeks
            else:
                request.session.set_expiry(0)  # browser close

            if user.role == "customer":
                messages.success(request, "Login successful! Welcome.")
                destination = request.session.pop('login_return_to', '')
                if destination and url_has_allowed_host_and_scheme(
                    destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
                ):
                    return redirect(destination)
                return redirect("home")
            elif user.role in ["admin", "staff"]:
                request.session.pop('login_return_to', None)
                messages.success(request, "Login successful! Welcome to the dashboard.")
                return redirect("dashboard")
        else:
            return render(
                request, "auth/login.html", {"error": "Invalid email or password."}
            )

    return render(request, 'auth/login.html', _signup_banner_context(request))


@never_cache
@require_http_methods(['POST'])
def continue_verification(request):
    user = signup_lifecycle.remembered_signup(request)
    if not user:
        messages.info(request, 'Log in with your email and password to continue verification.')
        return redirect('login')
    reference = request.POST.get('signup_reference')
    if reference and not constant_time_compare(reference, request.session[signup_lifecycle.RESUME_KEY].get('reference', '')):
        messages.info(request, 'Your active signup has changed. Continue with the account shown below.')
        return render(request, 'auth/login.html', _signup_banner_context(request))
    context = request.session.get(signup_lifecycle.OTP_KEY, {})
    challenge = email_otp.get_challenge(context, EmailOTPChallenge.SIGNUP)
    if challenge and challenge.user_id == user.pk and email_otp.bound(challenge, user, context):
        return redirect('verify_account_otp')
    return _start_signup_code(request, user.email, private=True)


@never_cache
@require_http_methods(['POST'])
def dismiss_signup_verification(request):
    signup_lifecycle.forget_signup(request)
    request.session.cycle_key()
    return redirect('login')


def _otp_rate_response(request, message, template, context=None):
    messages.error(request, message)
    response = render(request, template, context or {}, status=getattr(request, '_email_limit_status', 429))
    response['Retry-After'] = str(request._email_retry_after)
    response['Cache-Control'] = 'no-store'
    return response


def _request_otp(request, email, purpose):
    context = email_otp.new_context(email)
    accepted = False
    try:
        user = User.objects.filter(email__iexact=email).first()
        if email_otp.eligible(user, purpose):
            accepted = email_otp.send_code(user, purpose, context)
    except Exception:
        logger.exception('Failed to send %s email code.', purpose)
    return context, accepted


def _otp_notice(purpose):
    if purpose == EmailOTPChallenge.CHANGE:
        return 'A password change code has been sent. Your password stays the same until you verify it.'
    if purpose == EmailOTPChallenge.SIGNUP:
        return 'If your account still needs verification, check your inbox and spam folder for a verification code.'
    return 'If the email exists and is eligible, check your inbox and spam folder for a password reset code.'


def _start_signup_code(request, email, *, private=False):
    limited, message = _is_verification_resend_rate_limited(request, email)
    if limited:
        if private:
            return _otp_rate_response(request, message, 'auth/login.html', _signup_banner_context(request))
        return _otp_rate_response(request, message, 'auth/resend_verification.html', {'email': email})
    context, accepted = _request_otp(request, email, EmailOTPChallenge.SIGNUP)
    if private and not accepted:
        messages.error(request, 'We could not send your code. Your signup is saved. Please try again later.')
        return render(request, 'auth/login.html', _signup_banner_context(request), status=503)
    request.session[email_otp.session_key(EmailOTPChallenge.SIGNUP)] = context
    if accepted:
        log_action(None, 'Verification code requested.')
    messages.info(request, _otp_notice(EmailOTPChallenge.SIGNUP))
    return redirect('verify_account_otp')


@never_cache
@require_http_methods(['GET', 'POST'])
def resend_verification(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().casefold()
        try:
            validate_email_address(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid account email.')
            return render(request, 'auth/resend_verification.html', {'email': email})
        signup_lifecycle.forget_signup(request)
        return _start_signup_code(request, email)
    return render(request, 'auth/resend_verification.html')


@never_cache
@require_http_methods(['GET', 'POST'])
def forgot_password_request(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().casefold()
        try:
            validate_email_address(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid account email.')
            return render(request, 'auth/forgot_password.html')
        limited, message = _is_reset_request_rate_limited(request, email)
        if limited:
            return _otp_rate_response(request, message, 'auth/forgot_password.html')
        context, _accepted = _request_otp(request, email, EmailOTPChallenge.RESET)
        request.session[email_otp.session_key(EmailOTPChallenge.RESET)] = context
        messages.info(request, _otp_notice(EmailOTPChallenge.RESET))
        return redirect('verify_password_otp')
    return render(request, 'auth/forgot_password.html')


def _profile_route(user):
    return 'admin_profile' if user.role in ('admin', 'staff') else 'customer_profile'


def _otp_template_context(context, purpose):
    from django.utils.dateparse import parse_datetime
    from datetime import timedelta
    import math
    from django.db import OperationalError
    issued = parse_datetime(context.get('issued_at', '')) or timezone.now()
    prefix = {EmailOTPChallenge.SIGNUP: 'VERIFICATION_RESEND', EmailOTPChallenge.RESET: 'FORGOT_PASSWORD',
              EmailOTPChallenge.CHANGE: 'PASSWORD_CHANGE_OTP'}[purpose]
    wait = max(0, math.ceil((issued + timedelta(seconds=getattr(settings, prefix + '_COOLDOWN_SECONDS', 60)) - timezone.now()).total_seconds()))
    try:
        challenge = email_otp.get_challenge(context, purpose)
        verify_wait = email_otp.verification_wait(context, purpose, challenge)
    except OperationalError:
        challenge, verify_wait = None, 5
    expires = challenge.expires_at if challenge else issued + timedelta(seconds=settings.EMAIL_OTP_TIMEOUT)
    local, _, domain = context.get('email', '').partition('@')
    return {
        'masked_email': local[:1] + '***@' + domain, 'resend_wait': wait,
        'otp_minutes': settings.EMAIL_OTP_TIMEOUT // 60,
        'expiry_seconds': max(0, math.ceil((expires - timezone.now()).total_seconds())),
        'verify_wait': verify_wait,
        'is_signup': purpose == EmailOTPChallenge.SIGNUP,
        'is_change': purpose == EmailOTPChallenge.CHANGE,
        'digits': range(1, 7),
    }


def _otp_send_limit(request, email, purpose):
    if purpose == EmailOTPChallenge.SIGNUP:
        return _is_verification_resend_rate_limited(request, email)
    if purpose == EmailOTPChallenge.RESET:
        return _is_reset_request_rate_limited(request, email)
    return _email_request_limit(request, email, 'password-change-otp', 'PASSWORD_CHANGE_OTP', 'password change code')


def _resend_bound_code(request, context, purpose):
    old = email_otp.get_challenge(context, purpose)
    user = User.objects.filter(pk=old.user_id).first() if old else None
    if email_otp.bound(old, user, context):
        if purpose == EmailOTPChallenge.CHANGE and request.user.pk != user.pk:
            return context, False
        replacement = email_otp.new_context(context['email'])
        try:
            accepted = email_otp.send_code(user, purpose, replacement, replacement_email=old.replacement_email,
                                           pending_password_hash=old.pending_password_hash, expected_password=user.password)
        except Exception:
            logger.exception('Failed to resend %s email code.', purpose)
            return context, False
        return replacement, accepted
    if purpose == EmailOTPChallenge.CHANGE:
        return context, False
    return _request_otp(request, context['email'], purpose)


def _otp_page(request, purpose):
    from django.db import OperationalError
    key = email_otp.session_key(purpose)
    context = request.session.get(key)
    entry = {EmailOTPChallenge.SIGNUP: 'resend_verification', EmailOTPChallenge.RESET: 'forgot_password',
             EmailOTPChallenge.CHANGE: (_profile_route(request.user) if request.user.is_authenticated else 'login')}[purpose]
    route = {EmailOTPChallenge.SIGNUP: 'verify_account_otp', EmailOTPChallenge.RESET: 'verify_password_otp',
             EmailOTPChallenge.CHANGE: 'verify_change_password_otp'}[purpose]
    if not context:
        return redirect(entry)
    try:
        challenge = email_otp.get_challenge(context, purpose)
        user = User.objects.filter(pk=challenge.user_id).first() if challenge else None
        if purpose == EmailOTPChallenge.SIGNUP and signup_lifecycle.signup_expired(user):
            signup_lifecycle.forget_signup(request)
            messages.info(request, 'This signup session has expired. Please register again.')
            return redirect('register')
        if purpose == EmailOTPChallenge.CHANGE and (not email_otp.bound(challenge, user, context) or user.pk != request.user.pk):
            messages.error(request, 'Start your password change again from your profile.')
            return redirect(entry)
        if request.method == 'POST' and request.POST.get('action') == 'resend':
            limited, message = _otp_send_limit(request, context['email'], purpose)
            if limited:
                data = _otp_template_context(context, purpose)
                data['resend_wait'] = request._email_retry_after
                return _otp_rate_response(request, message, 'auth/verify_otp.html', data)
            replacement, accepted = _resend_bound_code(request, context, purpose)
            if accepted or not challenge:
                request.session[key] = replacement
            if purpose == EmailOTPChallenge.CHANGE and not accepted:
                messages.error(request, 'We could not send a new code. Your password has not changed. Please try again later.')
            else:
                messages.info(request, _otp_notice(purpose))
            return redirect(route)
        if purpose == EmailOTPChallenge.RESET and email_otp.grant_valid(challenge, user, context):
            return redirect('reset_password_otp')
        if request.method == 'POST':
            code = (request.POST.get('code') or ''.join(request.POST.get('digit_' + str(i), '') for i in range(1, 7))).strip()
            accepted, retry = email_otp.verify_code(request, purpose, context, code)
            if retry:
                raise RateLimited(retry, message='Too many incorrect codes. Please wait before trying again.')
            if accepted:
                if purpose == EmailOTPChallenge.SIGNUP:
                    signup_lifecycle.forget_signup(request)
                    log_action(user, 'Email verified using a one-time code.')
                    messages.success(request, 'Email verified successfully. You can now log in.')
                    return redirect('login')
                if purpose == EmailOTPChallenge.CHANGE:
                    user.refresh_from_db()
                    update_session_auth_hash(request, user)
                    request.session.pop(key, None)
                    log_action(user, 'Changed password using an email one-time code.')
                    messages.success(request, 'Your password was successfully updated!')
                    return redirect(_profile_route(user))
                return redirect('reset_password_otp')
            messages.error(request, 'The code is invalid, expired, or already used. Please check it or request a new code.')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    except RateLimited as error:
        request._email_retry_after = error.retry_after
        request._email_limit_status = 429
        data = _otp_template_context(context, purpose)
        data['verify_wait'] = error.retry_after
        return _otp_rate_response(request, str(error), 'auth/verify_otp.html', data)
    except OperationalError:
        request._email_retry_after = 5
        request._email_limit_status = 503
        return _otp_rate_response(request, 'Request protection is temporarily unavailable. Please try again in 5 seconds.',
                                  'auth/verify_otp.html', _otp_template_context(context, purpose))
    return render(request, 'auth/verify_otp.html', _otp_template_context(context, purpose))


_OTP_FIELDS = ('code', 'digit_1', 'digit_2', 'digit_3', 'digit_4', 'digit_5', 'digit_6')


@never_cache
@sensitive_post_parameters(*_OTP_FIELDS)
@require_http_methods(['GET', 'POST'])
def verify_account_otp(request):
    return _otp_page(request, EmailOTPChallenge.SIGNUP)


@never_cache
@sensitive_post_parameters(*_OTP_FIELDS)
@require_http_methods(['GET', 'POST'])
def verify_password_otp(request):
    return _otp_page(request, EmailOTPChallenge.RESET)


@login_required
@never_cache
@sensitive_post_parameters(*_OTP_FIELDS)
@require_http_methods(['GET', 'POST'])
def verify_change_password_otp(request):
    return _otp_page(request, EmailOTPChallenge.CHANGE)


@never_cache
@sensitive_post_parameters('password')
@require_http_methods(['GET', 'POST'])
def change_signup_email(request):
    from django.db import OperationalError
    key = email_otp.session_key(EmailOTPChallenge.SIGNUP)
    context = request.session.get(key, {})
    challenge = email_otp.get_challenge(context, EmailOTPChallenge.SIGNUP)
    user = User.objects.filter(pk=challenge.user_id).first() if challenge else None
    if not email_otp.bound(challenge, user, context) or not email_otp.eligible(user, EmailOTPChallenge.SIGNUP):
        messages.info(request, 'Continue verification first, then choose Change email address.')
        return redirect('resend_verification')
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().casefold()
        try:
            consume_rules([('signup-email:account', str(user.pk), 5, 600, 1),
                           ('signup-email:ip', client_ip(request), 10, 600, 1)], force=True)
            if not user.check_password(request.POST.get('password') or ''):
                raise ValidationError('Enter the original password you used to create this account.')
            if not re.fullmatch(r'[A-Za-z0-9._%+-]+@gmail\.com', email):
                raise ValidationError('Please enter a valid Gmail address.')
            if email == context['email']:
                raise ValidationError('Enter a different email address, or return to verification.')
            if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                raise ValidationError('This email is already registered. Choose another email address.')
            limited, message = _otp_send_limit(request, email, EmailOTPChallenge.SIGNUP)
            if limited:
                return _otp_rate_response(request, message, 'auth/change_signup_email.html', {'email': email})
            replacement = email_otp.new_context(email)
            try:
                accepted = email_otp.send_code(user, EmailOTPChallenge.SIGNUP, replacement,
                    replacement_email=email if email != user.email.casefold() else '',
                    expected_password=user.password)
            except Exception:
                logger.exception('Failed to send replacement signup email code.')
                accepted = False
            if not accepted:
                messages.error(request, 'We could not send the code. Your account email has not changed. Please try again later.')
            else:
                request.session[key] = replacement
                messages.success(request, 'Enter the code sent to your new email to finish creating your account.')
                return redirect('verify_account_otp')
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        except RateLimited as error:
            request._email_retry_after = error.retry_after
            return _otp_rate_response(request, str(error), 'auth/change_signup_email.html', {'email': email})
        except OperationalError:
            request._email_retry_after, request._email_limit_status = 5, 503
            return _otp_rate_response(request, 'Please try again in 5 seconds.', 'auth/change_signup_email.html')
        return render(request, 'auth/change_signup_email.html', {'email': email})
    return render(request, 'auth/change_signup_email.html')


@never_cache
@sensitive_post_parameters('password', 'confirm_password')
@require_http_methods(['GET', 'POST'])
def reset_password_otp(request):
    from django.db import OperationalError
    key = email_otp.session_key(EmailOTPChallenge.RESET)
    context = request.session.get(key, {})
    try:
        challenge = email_otp.get_challenge(context, EmailOTPChallenge.RESET)
        user = User.objects.filter(pk=challenge.user_id).first() if challenge else None
        if not email_otp.grant_valid(challenge, user, context):
            messages.error(request, 'Verify a new password reset code before setting your password.')
            return redirect('forgot_password')
        if request.method == 'POST':
            password = request.POST.get('password') or ''
            if password != (request.POST.get('confirm_password') or ''):
                messages.error(request, 'Passwords do not match.')
            else:
                try:
                    result = email_otp.reset_password(context, password)
                except ValidationError as error:
                    messages.error(request, ' '.join(error.messages))
                else:
                    if not result:
                        messages.error(request, 'Your reset authorization has expired or already been used.')
                        return redirect('forgot_password')
                    request.session.pop(key, None)
                    request.session.cycle_key()
                    log_action(result, 'Password reset using an email one-time code.')
                    messages.success(request, 'Password updated successfully. You can now log in.')
                    return redirect('login')
    except OperationalError:
        request._email_retry_after = 5
        request._email_limit_status = 503
        return _otp_rate_response(request, 'Account recovery is temporarily unavailable. Please try again in 5 seconds.',
                                  'auth/reset_password.html', {'is_valid_link': True})
    return render(request, 'auth/reset_password.html', {'is_valid_link': True})


@never_cache
@sensitive_post_parameters('password', 'confirm_password')
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def password_reset_confirm(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = (User.objects.select_for_update() if request.method == 'POST' else User.objects).get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    is_valid_link = bool(user and default_token_generator.check_token(user, token))

    if request.method == "POST":
        if not is_valid_link:
            messages.error(request, "This reset link is invalid or expired.")
            return redirect("forgot_password")

        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(
                request, "auth/reset_password.html", {"is_valid_link": is_valid_link}
            )

        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return render(
                request, "auth/reset_password.html", {"is_valid_link": is_valid_link}
            )

        user.set_password(password)
        user.save(update_fields=['password'])
        email_otp.invalidate(user, EmailOTPChallenge.RESET)
        email_otp.invalidate(user, EmailOTPChallenge.CHANGE)
        log_action(user, "Password reset via forgot password.")
        messages.success(request, "Password updated successfully. You can now log in.")
        return redirect("login")

    return render(request, "auth/reset_password.html", {"is_valid_link": is_valid_link})


def user_logout(request):
    if request.user.is_authenticated:
        log_action(request.user, "User logged out.")
    logout(request)
    return redirect("home")


@login_required
@never_cache
@sensitive_post_parameters('old_password', 'new_password1', 'new_password2')
@require_http_methods(['GET', 'POST'])
def change_password(request):
    if request.method == 'POST':
        is_ajax = request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            limited, message = _otp_send_limit(request, request.user.email, EmailOTPChallenge.CHANGE)
            if limited:
                errors = {'__all__': [message]}
                status = getattr(request, '_email_limit_status', 429)
            else:
                context = email_otp.new_context(request.user.email)
                try:
                    accepted = email_otp.send_code(request.user, EmailOTPChallenge.CHANGE, context,
                        pending_password_hash=make_password(form.cleaned_data['new_password1']),
                        expected_password=request.user.password)
                except Exception:
                    logger.exception('Failed to send password change code.')
                    accepted = False
                if accepted:
                    request.session[email_otp.session_key(EmailOTPChallenge.CHANGE)] = context
                    if is_ajax:
                        return JsonResponse({'success': True, 'otp_required': True,
                            'redirect_url': reverse('verify_change_password_otp'), 'message': 'Verify your email code to update your password.'})
                    return redirect('verify_change_password_otp')
                errors = {'__all__': ['We could not send the verification code. Your password has not changed. Please try again later.']}
                status = 503
        else:
            errors, status = form.errors, 200
        if is_ajax:
            response = JsonResponse({'success': False, 'errors': errors}, status=status)
            if hasattr(request, '_email_retry_after'):
                response['Retry-After'] = str(request._email_retry_after)
            return response
        for items in errors.values():
            for error in items:
                messages.error(request, error)
    return redirect(_profile_route(request.user))


def create_admin_account(request):
    User = get_user_model()
    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser("admin", "admin@example.com", "admin12345", role="admin")
        return HttpResponse("Admin account created! Username: admin, Password: admin12345. PLEASE DELETE THIS ROUTE AFTER USE.")
    return HttpResponse("Admin already exists.")
