from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .. import admin_security as security
from ..admin_security_forms import AdminAcceptForm, AdminEmailForm, AdminInviteForm
from ..email_otp import digest
from ..models import AdminInvitation, User
from ..request_protection import RateLimited, client_ip, consume_rules, limit_response


def _error(request, error):
    if isinstance(error, RateLimited):
        return limit_response(request, error)
    return JsonResponse({'success': False, 'message': error.message, 'code': error.code}, status=error.status)


@never_cache
@login_required
@require_GET
def admin_email_setup(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Admins only')
    if request.user.email_verified:
        request.session.pop('admin_email_setup_required', None)
        return redirect('admin_profile')
    return redirect(reverse('admin_profile') + '?verify_email=1#admin-email-verification')


@never_cache
@login_required
@require_POST
@sensitive_post_parameters('current_password', 'code')
def admin_security_action(request, purpose, action):
    if request.user.role != 'admin' or purpose not in ('email', 'invite') or action not in ('send', 'confirm', 'resend'):
        return HttpResponseForbidden('Admin security action unavailable')
    try:
        if action in ('send', 'resend'):
            if action == 'resend':
                recipient = security.resend_challenge(request, purpose)
            else:
                form = (AdminEmailForm if purpose == 'email' else AdminInviteForm)(request.POST)
                if not form.is_valid():
                    return JsonResponse({'success': False, 'errors': form.errors, 'message': 'Check the required fields below.'}, status=400)
                data = form.cleaned_data
                payload = ({key: data[key] for key in ('first_name', 'last_name', 'phone_number')} if purpose == 'invite' else {})
                if data.get('resend_id'):
                    payload['resend_id'] = str(data['resend_id'])
                recipient = security.issue_challenge(request, purpose, data['current_password'], data['email'], payload)
            state = security.pending_challenge(request, purpose)
            if not state:
                raise security.SecurityError('This verification request is no longer available. Sign in again before continuing.', 409)
            timing = {key: state[key] for key in ('server_now', 'expires_at', 'resend_available_at', 'expires_in', 'resend_after')}
            return JsonResponse({'success': True, 'message': f'A verification code was sent to {recipient}.', 'stage': 'code', **timing})
        confirmed = security.confirm_challenge(request, purpose, (request.POST.get('code') or '').strip())
        return JsonResponse({'success': True, 'message': 'Admin email verified.' if purpose == 'email' else 'Invitation sent. The recipient can now choose their own password.',
                             'verified_email': confirmed.email if purpose == 'email' else None,
                             'redirect_url': reverse('admin_profile') if purpose == 'email' else ''})
    except (security.SecurityError, RateLimited) as exc:
        return _error(request, exc)


@never_cache
@login_required
@require_GET
def admin_invitation_list(request):
    user = User.objects.get(pk=request.user.pk)
    if not security.can_invite(user):
        return HttpResponseForbidden('Only verified, authorized admins can manage invitations')
    invitations = AdminInvitation.objects.all() if user.is_superuser else AdminInvitation.objects.filter(created_by=user)
    # A bounded recent list. Invitations are not accounts and are kept out of account KPIs.
    from django.utils import timezone
    items = [{ 'id': str(item.pk), 'email': item.email, 'first_name': item.first_name, 'last_name': item.last_name,
        'phone_number': item.phone_number, 'status': 'expired' if item.status == 'pending' and item.expires_at <= timezone.now() else item.status,
        'expires_at': item.expires_at.isoformat(), 'can_resend': item.status == 'pending' and item.created_by_id == user.pk and item.expires_at > timezone.now()}
        for item in invitations.order_by('-created_at')[:20]]
    return JsonResponse({'invitations': items})


@never_cache
@login_required
@require_POST
@sensitive_post_parameters('current_password')
def admin_invitation_revoke(request, invitation_id):
    try:
        security.revoke_invitation(request, invitation_id, request.POST.get('current_password'))
        return JsonResponse({'success': True, 'message': 'Invitation revoked. Its link can no longer create an account.'})
    except (security.SecurityError, RateLimited) as exc:
        return _error(request, exc)


def _private(response, referrer='same-origin'):
    # The token-free form needs a same-origin referrer/Origin for Django CSRF.
    # The raw-token redirect below sends no referrer at all.
    response['Referrer-Policy'] = referrer
    response['Cache-Control'] = 'no-store, private'
    return response


@never_cache
@require_GET
def admin_invitation_open(request, invitation_id, token):
    # GET is safe for mail scanners; the account is created only by a CSRF-protected POST.
    # Exchange the token for a server-side session proof, removing it from the form URL.
    if len(token) == 43:
        invitation = AdminInvitation.objects.select_related('created_by').filter(pk=invitation_id).first()
        proof = digest('admin-invite', token)
        if security.invitation_valid(invitation, invitation.created_by if invitation else None, proof):
            request.session.cycle_key()
            request.session[security.INVITE_PROOF] = {'id': str(invitation_id), 'digest': proof}
        else:
            request.session.pop(security.INVITE_PROOF, None)
    else:
        request.session.pop(security.INVITE_PROOF, None)
    return _private(redirect('admin_invitation_accept'), 'no-referrer')


@never_cache
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password', 'confirm_password')
def admin_invitation_accept(request):
    proof = request.session.get(security.INVITE_PROOF) or {}
    invitation = AdminInvitation.objects.select_related('created_by').filter(pk=proof.get('id')).first() if proof.get('id') else None
    valid = security.invitation_valid(invitation, invitation.created_by if invitation else None, proof.get('digest'))
    form = AdminAcceptForm(request.POST if request.method == 'POST' else None)
    asynchronous = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    error = None
    if request.method == 'POST':
        if request.user.is_authenticated:
            error = 'Sign out of your current account, then reopen the invitation from your email.'
        elif not valid:
            error = 'This invitation is expired, used, revoked or no longer authorized. Request a new invitation.'
        elif form.is_valid():
            try:
                consume_rules([('admin-invite:accept:ip', client_ip(request), 20, 3600, 1)], force=True)
                security.accept_invitation(proof, form.cleaned_data['password'])
            except (security.SecurityError, RateLimited) as exc:
                error = str(exc)
            else:
                request.session.pop(security.INVITE_PROOF, None)
                request.session.cycle_key()
                messages.success(request, 'Your admin account is ready. Sign in with your verified email and your new password.')
                if asynchronous:
                    return _private(JsonResponse({'success': True, 'redirect_url': reverse('login')}))
                return _private(redirect('login'))
        if asynchronous:
            return _private(JsonResponse({'success': False, 'message': error or '',
                'errors': {name: list(errors) for name, errors in form.errors.items()}}, status=400))
    return _private(render(request, 'admin/security/accept_invitation.html', {
        'invitation': invitation if valid else None, 'valid': valid, 'form': form, 'invitation_error': error,
    }, status=400 if error or (request.method == 'POST' and form.errors) else 200))
