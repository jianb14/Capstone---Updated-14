"""Authentication: register, verify, login, password reset, logout. (split from app/views.py)"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.core.validators import validate_email as validate_email_address

from .. import email_otp
from ..models import EmailOTPChallenge
from ..request_protection import RateLimited

from .common import *  # noqa: F401,F403
from .common import (  # noqa: F401
    _is_reset_request_rate_limited,
    _is_verification_resend_rate_limited,
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

        # Email unique. If the account exists but is still unverified, point
        # the user to the resend flow instead of the old "Email already
        # exists." dead end.
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user and existing_user.email_verified:
            errors.append("Email already exists.")
        elif existing_user:
            errors.append(
                "This email is already registered but not yet verified. "
                "Please log in and use \"Resend verification code\" to get a new code."
            )

        # Username unique
        if User.objects.filter(username=username).exists():
            errors.append("Username already exists.")

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
            return render(request, "auth/register.html", {"errors": errors})

        limited, message = _is_verification_resend_rate_limited(request, email)
        if limited:
            return _otp_rate_response(request, message, 'auth/register.html')

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone,
                role=role,
                email_verified=False,
            )
        except Exception:
            logger.exception("Failed to create user account during registration.")
            errors.append(
                "We could not create your account right now. Please try again in a moment."
            )
            return render(request, "auth/register.html", {"errors": errors})

        try:
            _send_account_verification_email(request, user)
        except Exception:
            logger.exception("Failed to send account verification email.")
            user.delete()
            errors.append(
                "We could not send a verification email right now. Please try again in a moment."
            )
            return render(request, "auth/register.html", {"errors": errors})

        log_action(None, f"New user '{username}' registered. Verification email sent.")
        messages.success(
            request,
            "Account created. Enter the verification code sent to your Gmail before logging in.",
        )
        return redirect("verify_account_otp")

    return render(request, "auth/register.html")


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

    if not user:
        messages.error(request, "Invalid verification link.")
        return redirect("login")

    if user.email_verified:
        messages.success(request, "Your email is already verified. You can log in.")
        return redirect("login")

    if not email_verification_token_generator.check_token(user, token):
        # Dead-end fix: huwag nang ipabalik sa register (doon ay "Email
        # already exists" lang ang lalabas).  I-redirect sa login kung saan
        # may "Resend verification email" button at naka-prefill ang email.
        request.session["unverified_email"] = user.email
        return redirect("login")

    if request.method == 'GET':
        return render(request, 'auth/verify_email_link.html')

    user.email_verified = True
    user.save(update_fields=["email_verified"])
    email_otp.invalidate(user, EmailOTPChallenge.SIGNUP)
    log_action(user, "Email verified.")
    messages.success(request, "Email verified successfully. You can now log in.")
    return redirect("login")


User = get_user_model()


def user_login(request):
    # Email na naka-stash mula sa invalid/expired verification link —
    # para may persistent na banner at prefill sa login page.
    stashed_email = request.session.pop("unverified_email", "")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password")

        # Try to get user by email
        try:
            user_obj = User.objects.get(email=email)
            username = user_obj.username  # Django authenticate needs username
        except User.DoesNotExist:
            return render(
                request, "auth/login.html", {"error": "Invalid email or password."}
            )

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_superuser and not getattr(user, "email_verified", True):
                # Persistent inline banner imbes na lilipas na toast — dito
                # naka-prefill ang email at may "Resend verification email".
                return render(
                    request,
                    "auth/login.html",
                    {
                        "unverified_email": email,
                        "verify_message": (
                            "Please confirm your email address before logging in. "
                            "Request a verification code below to confirm your account."
                        ),
                    },
                )

            login(request, user)

            log_action(user, "User logged in.")
            if request.POST.get("remember_me"):
                request.session.set_expiry(1209600)  # 2 weeks
            else:
                request.session.set_expiry(0)  # browser close

            if user.role == "customer":
                messages.success(request, "Login successful! Welcome.")
                return redirect("home")
            elif user.role in ["admin", "staff"]:
                messages.success(request, "Login successful! Welcome to the dashboard.")
                return redirect("dashboard")
        else:
            return render(
                request, "auth/login.html", {"error": "Invalid email or password."}
            )

    context = {}
    if stashed_email:
        context["unverified_email"] = stashed_email
        context["verify_message"] = (
            "This verification link is invalid or expired. "
            "Click the button below to receive a verification code."
        )
    return render(request, "auth/login.html", context)


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
    if purpose == EmailOTPChallenge.SIGNUP:
        return 'If your account still needs verification, check your inbox and spam folder for a verification code.'
    return 'If the email exists and is eligible, check your inbox and spam folder for a password reset code.'


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
        limited, message = _is_verification_resend_rate_limited(request, email)
        if limited:
            return _otp_rate_response(request, message, 'auth/resend_verification.html', {'email': email})
        context, accepted = _request_otp(request, email, EmailOTPChallenge.SIGNUP)
        request.session[email_otp.session_key(EmailOTPChallenge.SIGNUP)] = context
        if accepted:
            log_action(None, 'Verification code requested.')
        messages.info(request, _otp_notice(EmailOTPChallenge.SIGNUP))
        return redirect('verify_account_otp')
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


def _otp_template_context(context, purpose):
    from django.utils.dateparse import parse_datetime
    from datetime import timedelta
    import math
    issued = parse_datetime(context.get('issued_at', '')) or timezone.now()
    prefix = 'VERIFICATION_RESEND' if purpose == EmailOTPChallenge.SIGNUP else 'FORGOT_PASSWORD'
    wait = max(0, math.ceil((issued + timedelta(seconds=getattr(settings, prefix + '_COOLDOWN_SECONDS', 60)) - timezone.now()).total_seconds()))
    email = context.get('email', '')
    local, _, domain = email.partition('@')
    return {
        'masked_email': (local[:1] + '***@' + domain), 'resend_wait': wait,
        'otp_minutes': settings.EMAIL_OTP_TIMEOUT // 60,
        'is_signup': purpose == EmailOTPChallenge.SIGNUP,
    }


def _otp_page(request, purpose):
    from django.db import OperationalError
    key = email_otp.session_key(purpose)
    context = request.session.get(key)
    entry = 'resend_verification' if purpose == EmailOTPChallenge.SIGNUP else 'forgot_password'
    route = 'verify_account_otp' if purpose == EmailOTPChallenge.SIGNUP else 'verify_password_otp'
    if not context:
        return redirect(entry)
    if request.method == 'POST' and request.POST.get('action') == 'resend':
        limiter = _is_verification_resend_rate_limited if purpose == EmailOTPChallenge.SIGNUP else _is_reset_request_rate_limited
        limited, message = limiter(request, context['email'])
        if limited:
            data = _otp_template_context(context, purpose)
            data['resend_wait'] = request._email_retry_after
            return _otp_rate_response(request, message, 'auth/verify_otp.html', data)
        replacement, accepted = _request_otp(request, context['email'], purpose)
        # Failed sending preserves the previously accepted code and browser binding.
        if accepted or not email_otp.get_challenge(context, purpose):
            request.session[key] = replacement
        messages.info(request, _otp_notice(purpose))
        return redirect(route)
    try:
        challenge = email_otp.get_challenge(context, purpose)
        user = User.objects.filter(pk=challenge.user_id).first() if challenge else None
        if purpose == EmailOTPChallenge.RESET and email_otp.grant_valid(challenge, user, context):
            return redirect('reset_password_otp')
        if request.method == 'POST':
            accepted, retry = email_otp.verify_code(request, purpose, context, (request.POST.get('code') or '').strip())
            if retry:
                raise RateLimited(retry, message='Too many incorrect codes. Please wait before trying again.')
            if accepted:
                if purpose == EmailOTPChallenge.SIGNUP:
                    request.session.pop(key, None)
                    log_action(user, 'Email verified using a one-time code.')
                    messages.success(request, 'Email verified successfully. You can now log in.')
                    return redirect('login')
                return redirect('reset_password_otp')
            messages.error(request, 'The code is invalid, expired, or already used. Please check it or request a new code.')
    except RateLimited as error:
        request._email_retry_after = error.retry_after
        request._email_limit_status = 429
        return _otp_rate_response(request, str(error), 'auth/verify_otp.html', _otp_template_context(context, purpose))
    except OperationalError:
        request._email_retry_after = 5
        request._email_limit_status = 503
        return _otp_rate_response(request, 'Request protection is temporarily unavailable. Please try again in 5 seconds.',
                                  'auth/verify_otp.html', _otp_template_context(context, purpose))
    return render(request, 'auth/verify_otp.html', _otp_template_context(context, purpose))


@never_cache
@sensitive_post_parameters('code')
@require_http_methods(['GET', 'POST'])
def verify_account_otp(request):
    return _otp_page(request, EmailOTPChallenge.SIGNUP)


@never_cache
@sensitive_post_parameters('code')
@require_http_methods(['GET', 'POST'])
def verify_password_otp(request):
    return _otp_page(request, EmailOTPChallenge.RESET)


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
def change_password(request):
    if request.method == "POST":
        # Check if it's an AJAX request
        is_ajax = request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"

        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            email_otp.invalidate(user, EmailOTPChallenge.RESET)
            log_action(request.user, "Changed their password.")
            update_session_auth_hash(
                request, user
            )  # Important to keep the user logged in
            if is_ajax:
                return JsonResponse(
                    {"success": True, "message": "Password updated successfully!"}
                )
            messages.success(request, "Your password was successfully updated!")
        else:
            if is_ajax:
                return JsonResponse({"success": False, "errors": form.errors})
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{error}")
    # I-redirect sa tamang profile page base sa role — ang admin/staff ay
    # hindi dapat mapupunta sa customer-only na pahina ("Not allowed").
    if request.user.role in ["admin", "staff"]:
        return redirect("admin_profile")
    return redirect("customer_profile")


def create_admin_account(request):
    User = get_user_model()
    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser("admin", "admin@example.com", "admin12345", role="admin")
        return HttpResponse("Admin account created! Username: admin, Password: admin12345. PLEASE DELETE THIS ROUTE AFTER USE.")
    return HttpResponse("Admin already exists.")
