"""Authentication: register, verify, login, password reset, logout. (split from app/views.py)"""

from .common import *  # noqa: F401,F403
from .common import _is_reset_request_rate_limited  # noqa: F401


def _send_account_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"uidb64": uid, "token": token})
    )
    subject = "Verify your Balloorina account"
    body = (
        f"Hi {user.first_name or user.username},\n\n"
        f"Thanks for registering at Balloorina.\n"
        f"Please verify your Gmail by clicking the link below:\n{verify_url}\n\n"
        f"If you did not create this account, you can ignore this email."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@balloorina.local")
    send_mail(
        subject,
        body,
        from_email,
        [user.email],
        fail_silently=False,
    )


User = get_user_model()


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

        # Email unique
        if User.objects.filter(email=email).exists():
            errors.append("Email already exists.")

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
            "Registration successful! Please check your Gmail and verify your account before logging in.",
        )
        return redirect("login")

    return render(request, "auth/register.html")


def verify_email(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if not user:
        messages.error(request, "Invalid verification link.")
        return redirect("login")

    if user.email_verified:
        messages.success(request, "Your email is already verified. You can log in.")
        return redirect("login")

    if not default_token_generator.check_token(user, token):
        messages.error(
            request,
            "This verification link is invalid or expired. Please register again.",
        )
        return redirect("register")

    user.email_verified = True
    user.save(update_fields=["email_verified"])
    log_action(user, "Email verified.")
    messages.success(request, "Email verified successfully. You can now log in.")
    return redirect("login")


User = get_user_model()


def user_login(request):
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
                return render(
                    request,
                    "auth/login.html",
                    {
                        "error": "Please verify your Gmail first. Check your inbox for the verification link."
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

    return render(request, "auth/login.html")


def forgot_password_request(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        generic_message = "If the email exists, a password reset link has been sent."

        if not email:
            messages.error(request, "Please enter your account email.")
            return render(request, "auth/forgot_password.html")

        is_limited, rate_limit_message = _is_reset_request_rate_limited(request, email)
        if is_limited:
            messages.error(request, rate_limit_message)
            return render(request, "auth/forgot_password.html")

        try:
            user = User.objects.get(email__iexact=email)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(
                reverse(
                    "password_reset_confirm", kwargs={"uidb64": uid, "token": token}
                )
            )
            subject = "Balloorina Password Reset"
            body = (
                f"Hi {user.first_name or user.username},\n\n"
                f"We received a request to reset your password.\n"
                f"Use the link below:\n{reset_url}\n\n"
                f"If you did not request this, you can ignore this message."
            )
            from_email = getattr(
                settings, "DEFAULT_FROM_EMAIL", "no-reply@balloorina.local"
            )
            send_mail(
                subject,
                body,
                from_email,
                [user.email],
                fail_silently=getattr(settings, "EMAIL_FAIL_SILENTLY", True),
            )
        except User.DoesNotExist:
            pass
        except Exception:
            logger.exception("Failed to send forgot-password email.")

        messages.success(request, generic_message)
        return redirect("forgot_password")

    return render(request, "auth/forgot_password.html")


def password_reset_confirm(request, uidb64, token):
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
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
        user.save()
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
