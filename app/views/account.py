"""Owner-only, session-bound deletion verification and confirmation."""
import logging

from django.conf import settings
from django.contrib.auth import logout
from django.db import transaction, OperationalError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from .. import email_otp
from ..account_deletion import deletion_blockers, remove_account
from ..models import EmailOTPChallenge, User
from ..request_protection import RateLimited, consume_rules, client_ip
from .common import _email_request_limit

logger = logging.getLogger(__name__)
PURPOSE = EmailOTPChallenge.DELETE
KEY = email_otp.session_key(PURPOSE)


def _authorized(request):
    user = request.user
    return user.is_authenticated and user.role == 'customer' and not user.is_staff and not user.is_superuser and not user.deleted_at


def _error(message, status=400, **data):
    return JsonResponse({'success':False,'message':message,**data},status=status)


def _grant(challenge, user, context):
    return bool(email_otp.bound(challenge,user,context) and challenge.purpose == PURPOSE
        and challenge.verified_at and challenge.grant_expires_at and challenge.grant_expires_at > timezone.now())


@never_cache
@require_GET
def account_deletion_status(request):
    if not _authorized(request): return _error('Please sign in to your customer account.',403)
    blockers = deletion_blockers(request.user)
    context = request.session.get(KEY,{})
    challenge = email_otp.get_challenge(context,PURPOSE)
    bound = email_otp.bound(challenge,request.user,context)
    wait = max(0,int((challenge.sent_at-timezone.now()).total_seconds())+getattr(settings,'ACCOUNT_DELETION_OTP_COOLDOWN_SECONDS',60)) if bound else 0
    return JsonResponse({'success':True,'blockers':blockers,'can_delete':not blockers,
        'step':'confirm' if _grant(challenge,request.user,context) else 'code' if bound and challenge.expires_at > timezone.now() and not challenge.verified_at else 'password',
        'masked_email':email_otp.mask_email(request.user.email),'resend_wait':wait,
        'has_password':request.user.has_usable_password(),'email_verified':request.user.email_verified})


@never_cache
@require_POST
@sensitive_post_parameters('password','code')
def delete_my_account(request):
    if not _authorized(request): return _error('Please sign in to your customer account.',403)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.deleted_at or not user.is_active: return _error('This account is no longer active.',403)
        action = request.POST.get('action','')
        context = request.session.get(KEY,{})
        if action == 'cancel':
            email_otp.invalidate(user,PURPOSE)
            request.session.pop(KEY,None)
            return JsonResponse({'success':True})
        if action not in ('request_code','resend','verify','confirm'):
            return _error('Please choose a valid account action.')
        blockers = deletion_blockers(user,lock=True)
        if blockers: return _error('Please resolve these bookings or payments before deleting your account.',409,blockers=blockers)
        try:
            if action in ('request_code','resend'):
                if action == 'request_code':
                    consume_rules([('delete-account:password:account',str(user.pk),5,600,1),
                        ('delete-account:password:ip',client_ip(request),20,600,1)],force=True)
                    if not user.check_password(request.POST.get('password','')):
                        return _error('Your current password is incorrect.',400,field='password')
                else:
                    old = email_otp.get_challenge(context,PURPOSE)
                    if not email_otp.bound(old,user,context) or old.verified_at:
                        return _error('Confirm your current password again to request a new code.',400,restart=True)
                if not email_otp.eligible(user,PURPOSE):
                    return _error('You need a verified account email and a current password before deleting your account.')
                limited,message = _email_request_limit(request,user.email,'account-deletion-otp','ACCOUNT_DELETION_OTP','account deletion code')
                if limited:
                    response = _error(message,getattr(request,'_email_limit_status',429),retry_after=request._email_retry_after)
                    response['Retry-After'] = str(request._email_retry_after)
                    return response
                replacement = email_otp.new_context(user.email)
                try: accepted = email_otp.send_code(user,PURPOSE,replacement,expected_password=user.password)
                except Exception:
                    logger.exception('Account deletion verification email could not be sent')
                    return _error('We could not send your code. Your account has not changed. Please try again later.',503)
                if not accepted: return _error('Your account details changed. Please start again.',409,restart=True)
                request.session[KEY] = replacement
                return JsonResponse({'success':True,'step':'code','masked_email':email_otp.mask_email(user.email),
                    'resend_wait':getattr(settings,'ACCOUNT_DELETION_OTP_COOLDOWN_SECONDS',60),
                    'message':'A verification code has been sent. Your account has not been deleted.'})
            challenge = email_otp.get_challenge(context,PURPOSE,lock=True)
            if not challenge or challenge.user_id != user.pk or not email_otp.bound(challenge,user,context):
                return _error('Your deletion session expired or your account details changed. Start again.',400,restart=True)
            if action == 'verify':
                accepted,wait = email_otp.verify_code(request,PURPOSE,context,request.POST.get('code','').strip())
                if not accepted:
                    response = _error('Please wait before trying another code.' if wait else 'This code is incorrect or expired.',429 if wait else 400,retry_after=wait)
                    if wait: response['Retry-After'] = str(wait)
                    return response
                return JsonResponse({'success':True,'step':'confirm','message':'Email verified. Review the details before deleting your account.'})
            if request.POST.get('acknowledge') != 'yes': return _error('Confirm that you understand this action is permanent.')
            if not _grant(challenge,user,context):
                return _error('Verify your email code again before deleting your account.',400,restart=True)
            remove_account(user)
            logout(request)
            request.session['account_deleted_notice'] = True
            return JsonResponse({'success':True,'deleted':True,'redirect_url':reverse('account_deleted')})
        except RateLimited as error:
            response = _error(str(error),429,retry_after=error.retry_after)
            response['Retry-After'] = str(error.retry_after)
            return response
        except OperationalError:
            # Do not pretend a security check or deletion succeeded during a DB outage.
            raise


@never_cache
@require_GET
def account_deleted(request):
    if not request.session.pop('account_deleted_notice',False): return redirect('home')
    return render(request,'client/account_deleted.html')
