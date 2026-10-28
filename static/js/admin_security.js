/* Privileged forms always POST with CSRF. No passwords, codes or tokens enter storage. */
(() => {
    'use strict';
    const modal = document.getElementById('adminInviteModal');
    let invitationItems = [], listing = false, revokeId = '';
    const notifyInvitation = (form, message, kind = 'success') => {
        if (modal?.contains(form)) window.AdminConfigurationFeedback?.show(message, kind);
    };
    const feedback = (form, message, success = false) => {
        const node = form.querySelector('.ase-feedback');
        node.textContent = message;
        node.toggleAttribute('data-success', success);
        delete node.dataset.validationSummary;
    };
    const csrf = form => form.querySelector('[name=csrfmiddlewaretoken]').value;
    const codeDigits = form => [...form.querySelectorAll('[data-otp-digit]')];
    const syncCode = form => { form.elements.code.value = codeDigits(form).map(field => field.value).join(''); };
    const focusCode = form => codeDigits(form)[0]?.focus();
    const securityForms = [...document.querySelectorAll('[data-security-flow]')];
    const codeClocks = new WeakMap();
    const formatTime = seconds => Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
    function remainingTime(form) {
        const clock = codeClocks.get(form);
        if (!clock) return null;
        // Monotonic elapsed time avoids resetting the countdown if the device
        // clock changes. The deadlines always come from the server.
        const now = clock.serverNow + performance.now() - clock.started;
        return {expires: Math.max(0, Math.ceil((clock.expires - now) / 1000)),
                resend: Math.max(0, Math.ceil((clock.resend - now) / 1000))};
    }
    function updateClock(form) {
        const remaining = remainingTime(form);
        const isCode = form.dataset.stage === 'code';
        const expired = form.dataset.stage === 'expired';
        const submit = form.querySelector('[type=submit]');
        const busy = Boolean(form.dataset.busy);
        if (isCode && remaining?.expires === 0 && !busy) {
            stage(form, 'expired'); feedback(form, ''); return;
        }
        if (remaining) {
            const expiry = form.querySelector('[data-code-expiry]');
            expiry.textContent = remaining.expires ? 'Code expires in ' + formatTime(remaining.expires) + '.' : 'This code has expired. Request a new code.';
            expiry.classList.toggle('is-expired', remaining.expires === 0);
        }
        submit.disabled = busy || Boolean(remaining && !isCode && remaining.resend > 0);
        submit.textContent = isCode ? 'Verify code and continue' :
            (remaining?.resend ? 'Request another code in ' + formatTime(remaining.resend) :
                (expired ? 'Send new code' : form.dataset.sendUrl.includes('/email/') ? 'Send verification code' : 'Send authorization code'));
        const resend = form.querySelector('[data-security-resend]');
        resend.disabled = busy || Boolean(remaining?.resend);
        resend.textContent = remaining?.resend ? 'Resend in ' + formatTime(remaining.resend) : 'Resend code';
        form.querySelector('[data-security-back]').disabled = busy;
    }
    function setClock(form, timing) {
        const serverNow = Date.parse(timing.server_now), expires = Date.parse(timing.expires_at), resend = Date.parse(timing.resend_available_at);
        if (![serverNow, expires, resend].every(Number.isFinite)) return;
        codeClocks.set(form, {serverNow, expires, resend, started: performance.now()});
        updateClock(form);
    }
    setInterval(() => securityForms.forEach(updateClock), 1000);
    function clearErrorMessage(node, form) {
        form.querySelectorAll('[aria-describedby~="' + node.id + '"]').forEach(field => {
            const ids = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id !== node.id);
            if (ids.length) field.setAttribute('aria-describedby', ids.join(' '));
            else field.removeAttribute('aria-describedby');
            field.removeAttribute('aria-invalid');
        });
        node.remove();
        const summary = form.querySelector('.ase-feedback[data-validation-summary]');
        if (summary && !form.querySelector('[aria-invalid="true"]')) feedback(form, '');
    }
    function clearFieldErrors(form) {
        form.querySelectorAll('.ase-field-error').forEach(node => clearErrorMessage(node, form));
    }
    function showFieldError(form, name, messages) {
        const field = form.elements.namedItem(name);
        if (!field || field.disabled || !field.id) return;
        let node = document.getElementById(field.id + 'Error');
        if (!node) {
            node = document.createElement('p');
            node.id = field.id + 'Error'; node.className = 'ase-field-error';
            const parent = name === 'code' ? form.querySelector('.ase-otp-fieldset') : field.closest('.password-visibility-field');
            (parent || field).after(node);
        }
        node.textContent = Array.isArray(messages) ? messages.join(' ') : messages;
        const targets = name === 'code' ? codeDigits(form) : [field];
        targets.forEach(input => {
            input.setAttribute('aria-invalid', 'true');
            const ids = new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
            ids.add(node.id); input.setAttribute('aria-describedby', [...ids].join(' '));
        });
    }
    function validateForm(form) {
        clearFieldErrors(form);
        if (form.dataset.stage === 'code') {
            syncCode(form);
            if (!codeDigits(form).every(field => /^[0-9]$/.test(field.value))) showFieldError(form, 'code', 'Enter all 6 digits from your email.');
        }
        for (const field of form.querySelectorAll('input')) {
            if (!field.willValidate || field.hasAttribute('data-otp-digit')) continue;
            const label = field.labels?.[0]?.textContent.replace('*', '').trim() || 'This field';
            let message = '';
            if (field.required && (!field.value || (field.type !== 'password' && !field.value.trim()))) message = label + ' is required.';
            else if (field.validity.typeMismatch) message = 'Enter a valid email address.';
            else if (field.validity.patternMismatch) message = 'Enter the 6-digit verification code.';
            else if (!field.validity.valid) message = field.validationMessage;
            else if (field.name === 'phone_number' && !/^[0-9]{10,15}$/.test(field.value.replace(/[\s\-()+]/g, ''))) message = 'Enter a phone number with 10 to 15 digits.';
            if (message) showFieldError(form, field.name, message);
        }
        const first = form.querySelector('[aria-invalid="true"]');
        if (first) {
            feedback(form, '');
            first.focus(); return false;
        }
        return true;
    }
    document.querySelectorAll('.ase-form[data-security-flow],.ase-form.ase-revoke').forEach(form => {
        form.noValidate = true;
        form.addEventListener('input', event => {
            const field = event.target;
            if (!field.id || !field.hasAttribute('aria-invalid')) return;
            const node = (field.getAttribute('aria-describedby') || '').split(/\s+/)
                .map(id => document.getElementById(id)).find(item => item?.classList.contains('ase-field-error'));
            if (node) clearErrorMessage(node, form);
        });
        form.addEventListener('reset', () => clearFieldErrors(form));
    });
    document.querySelectorAll('[data-security-flow]').forEach(form => {
        const fields = codeDigits(form);
        function clearCodeError() {
            const node = document.getElementById(form.elements.code.id + 'Error');
            if (node) clearErrorMessage(node, form);
        }
        function distribute(value, index) {
            const digits = value.replace(/[^0-9]/g, '').slice(0, 6);
            if (!digits) { syncCode(form); return; }
            const start = digits.length === 6 ? 0 : index;
            [...digits].forEach((digit, offset) => { if (fields[start + offset]) fields[start + offset].value = digit; });
            clearCodeError(); syncCode(form);
            fields[Math.min(start + digits.length, 5)].focus();
        }
        fields.forEach((field, index) => {
            // Mobile autofill may insert all six digits in one input event.
            field.maxLength = 6;
            field.addEventListener('focus', () => field.select());
            field.addEventListener('beforeinput', event => {
                if (event.data && event.inputType.startsWith('insert') && !/[0-9]/.test(event.data)) event.preventDefault();
            });
            field.addEventListener('input', event => {
                const value = event.inputType === 'insertText' && /^[0-9]$/.test(event.data || '') ? event.data : field.value;
                field.value = ''; distribute(value, index);
            });
            field.addEventListener('paste', event => {
                event.preventDefault(); distribute(event.clipboardData.getData('text'), index);
            });
            field.addEventListener('keydown', event => {
                if (event.ctrlKey || event.metaKey || event.altKey) return;
                if (event.key.length === 1 && !/^[0-9]$/.test(event.key)) event.preventDefault();
                else if (event.key === 'Backspace' && !field.value && index > 0) {
                    event.preventDefault(); fields[index - 1].value = ''; fields[index - 1].focus(); clearCodeError(); syncCode(form);
                } else if (event.key === 'ArrowLeft' && index > 0) {
                    event.preventDefault(); fields[index - 1].focus();
                } else if (event.key === 'ArrowRight' && index < 5) {
                    event.preventDefault(); fields[index + 1].focus();
                }
            });
        });
    });
    async function post(url, form, data) {
        const response = await fetch(url, { method: 'POST', body: data, credentials: 'same-origin',
            headers: {'X-CSRFToken': csrf(form), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'} });
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session has expired. Sign in again before continuing.');
        const result = await response.json();
        if (!response.ok || !result.success) {
            const details = result.errors ? Object.values(result.errors).flat().join('\n') : '';
            const error = new Error(details || result.message || 'This request could not be completed.');
            error.fields = result.errors;
            error.code = result.code;
            throw error;
        }
        return result;
    }
    function stage(form, next) {
        clearFieldErrors(form);
        const isCode = next === 'code', details = next === 'details';
        form.dataset.stage = next;
        form.querySelector('[data-security-fields]').hidden = !details;
        form.querySelectorAll('[data-security-fields] input').forEach(input => { input.disabled = !details; });
        form.querySelector('[data-security-code]').hidden = !isCode;
        form.querySelector('[data-security-expired]').hidden = next !== 'expired';
        const code = form.elements.code;
        code.disabled = !isCode;
        code.value = '';
        codeDigits(form).forEach(field => { field.value = ''; field.disabled = !isCode; field.required = isCode; });
        form.querySelector('[data-security-back]').hidden = details;
        form.querySelector('[data-security-resend]').hidden = !isCode;
        form.elements.current_password.value = '';
        form.elements.current_password.type = 'password';
        window.PasswordVisibility?.reset(form);
        updateClock(form);
    }
    function requestError(form, error) {
        if (error.code === 'code_expired') { stage(form, 'expired'); feedback(form, ''); return; }
        if (error.code === 'reauth_required' || error.code === 'code_unavailable') {
            stage(form, 'details');
            feedback(form, 'Confirm your current password to send a new code. Your details are saved.');
            form.elements.current_password.focus(); return;
        }
        if (error.fields) {
            Object.entries(error.fields).forEach(([name, messages]) => showFieldError(form, name, messages));
            feedback(form, (error.fields.__all__ || []).join(' '));
        } else {
            feedback(form, error.message);
            notifyInvitation(form, error.message, 'error');
        }
        form.querySelector('[aria-invalid="true"]')?.focus();
    }
    function resetClosedFlow(form) {
        if (form.dataset.stage === 'code' || form.dataset.stage === 'expired') {
            form.elements.code.value = '';
            codeDigits(form).forEach(field => { field.value = ''; });
            clearFieldErrors(form); feedback(form, '');
            form.elements.current_password.value = '';
            window.PasswordVisibility?.reset(form);
        } else {
            form.reset(); stage(form, 'details'); feedback(form, '');
        }
    }
    function completeEmailVerification(form, result) {
        const dialog = form.closest('[data-email-dialog]');
        if (!dialog || !result.verified_email) return false;
        document.querySelectorAll('[data-admin-email-value]').forEach(node => { node.textContent = result.verified_email; });
        const menuInfo = document.querySelector('.admin-topbar .user-info');
        if (menuInfo && !menuInfo.querySelector('[data-admin-email-value]')) {
            const email = document.createElement('small'); email.dataset.adminEmailValue = ''; email.textContent = result.verified_email; menuInfo.append(email);
        }
        document.querySelectorAll('[data-email-setup-prompt]').forEach(node => { node.hidden = true; });
        document.querySelectorAll('[data-email-required-action],[data-email-verified-message]').forEach(node => { node.hidden = false; });
        codeClocks.delete(form); form.reset(); stage(form, 'details'); feedback(form, '');
        form.dataset.complete = '1';
        const url = new URL(window.location.href); url.searchParams.delete('verify_email');
        if (url.hash === '#admin-email-verification') url.hash = '';
        history.replaceState(history.state, '', url.pathname + url.search + url.hash);
        dialog.close();
        document.querySelector('[data-email-verified-message]')?.focus({preventScroll:true});
        const notice = document.getElementById('apFeedback');
        if (notice) {
            notice.textContent = result.message || 'Your email has been verified and saved.';
            notice.dataset.kind = 'success'; notice.hidden = false;
        }
        window.AdminConfigurationFeedback?.show(result.message || 'Your email has been verified and saved.');
        return true;
    }
    document.querySelectorAll('[data-security-flow]').forEach(form => {
        setClock(form, {server_now:form.dataset.codeServerNow, expires_at:form.dataset.codeExpiresAt, resend_available_at:form.dataset.codeResendAt});
        stage(form, form.dataset.pendingStage || (form.dataset.pendingCode === '1' ? 'code' : 'details'));
        if (form.dataset.stage === 'code') feedback(form, 'Enter the code sent to ' + form.dataset.pendingRecipient + '.', true);
        if (form.dataset.pendingStage === 'details') feedback(form, 'Confirm your current password to continue. Your details are saved.');
        if (form.elements.resend_id) form.elements.email.addEventListener('input', () => { form.elements.resend_id.value = ''; });
        form.querySelector('[data-security-back]').addEventListener('click', () => {
            if (form.dataset.busy) return;
            stage(form, 'details'); feedback(form, '');
            form.elements.email.focus();
        });
        async function sendNewCode() {
            if (form.dataset.busy || remainingTime(form)?.resend > 0) return;
            form.dataset.busy = '1'; form.setAttribute('aria-busy', 'true'); updateClock(form);
            feedback(form, 'Sending a new code...', true);
            try {
                const data = new FormData(); data.set('csrfmiddlewaretoken', csrf(form));
                const result = await post(form.dataset.resendUrl, form, data);
                setClock(form, result); stage(form, 'code'); feedback(form, result.message, true); focusCode(form);
                notifyInvitation(form, result.message);
            } catch (error) { requestError(form, error); }
            finally { delete form.dataset.busy; form.removeAttribute('aria-busy'); updateClock(form); }
        }
        form.querySelector('[data-security-resend]').addEventListener('click', sendNewCode);
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (form.dataset.busy) return;
            if (form.dataset.stage === 'expired') { await sendNewCode(); return; }
            const isCode = form.dataset.stage === 'code';
            const remaining = remainingTime(form);
            if (isCode && remaining?.expires === 0) { stage(form, 'expired'); feedback(form, ''); return; }
            if (!isCode && remaining?.resend > 0) {
                feedback(form, 'You can request another code in ' + formatTime(remaining.resend) + '.');
                return;
            }
            if (!validateForm(form)) return;
            const data = new FormData(form);
            form.dataset.busy = '1';
            const submit = form.querySelector('[type=submit]');
            submit.disabled = true;
            updateClock(form);
            form.setAttribute('aria-busy', 'true');
            feedback(form, isCode ? 'Verifying your code...' : 'Sending your verification code...', true);
            try {
                const result = await post(isCode ? form.dataset.confirmUrl : form.dataset.sendUrl, form, data);
                if (!isCode) {
                    setClock(form, result);
                    stage(form, 'code'); feedback(form, result.message, true); focusCode(form);
                    notifyInvitation(form, result.message);
                } else if (completeEmailVerification(form, result)) {
                    // The profile and its email status update in place.
                } else if (result.redirect_url) {
                    window.location.assign(result.redirect_url);
                } else {
                    codeClocks.delete(form);
                    form.reset();
                    ['first_name','last_name','phone_number','email','resend_id'].forEach(key => { if (form.elements[key]) form.elements[key].value = ''; });
                    stage(form, 'details'); feedback(form, result.message, true);
                    notifyInvitation(form, result.message);
                    await loadInvitations();
                }
            } catch (error) {
                requestError(form, error);
            }
            finally { delete form.dataset.busy; updateClock(form); form.removeAttribute('aria-busy'); }
        });
    });
    const emailDialog = document.querySelector('[data-email-dialog]');
    if (emailDialog) {
        const form = emailDialog.querySelector('[data-security-flow]');
        let previousScrollLock = false;
        const openEmail = () => {
            if (emailDialog.open || form.dataset.complete) return;
            previousScrollLock = document.body.classList.contains('ac-modal-open');
            document.body.classList.add('ac-modal-open');
            emailDialog.showModal();
            if (form.dataset.stage === 'code') focusCode(form);
            else if (form.dataset.stage === 'details') form.elements.email.focus();
        };
        document.querySelectorAll('[data-open-email]').forEach(button => button.addEventListener('click', openEmail));
        emailDialog.querySelectorAll('[data-close-email]').forEach(button => button.addEventListener('click', () => { if (!form.dataset.busy) emailDialog.close(); }));
        emailDialog.addEventListener('cancel', event => { if (form.dataset.busy) event.preventDefault(); });
        emailDialog.addEventListener('close', () => {
            if (!previousScrollLock) document.body.classList.remove('ac-modal-open');
            resetClosedFlow(form);
        });
        if (emailDialog.hasAttribute('data-auto-open')) openEmail();
    }
    async function loadInvitations() {
        if (!modal || listing) return;
        listing = true;
        const list = modal.querySelector('[data-invitation-list]');
        try {
            const response = await fetch(modal.dataset.listUrl, { credentials: 'same-origin', headers: {'Accept': 'application/json'} });
            if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Invitations could not be loaded. Reopen this dialog or sign in again to retry.');
            invitationItems = (await response.json()).invitations;
            list.replaceChildren();
            if (!invitationItems.length) { const empty = document.createElement('p'); empty.className = 'ase-note'; empty.textContent = 'No invitations yet.'; list.append(empty); }
            invitationItems.forEach(item => {
                const row = document.createElement('div'); row.className = 'ase-invitation';
                const details = document.createElement('div'), email = document.createElement('p'), meta = document.createElement('small');
                email.textContent = item.email;
                meta.textContent = item.status.charAt(0).toUpperCase() + item.status.slice(1) + (item.status === 'pending' ? ' \u00b7 Expires ' + new Date(item.expires_at).toLocaleString() : '');
                details.append(email, meta); row.append(details);
                if (item.status === 'pending') {
                    const actions = document.createElement('div'); actions.className = 'ase-actions';
                    if (item.can_resend) {
                        const resend = document.createElement('button'); resend.type = 'button'; resend.className = 'ac-button'; resend.textContent = 'Resend';
                        resend.addEventListener('click', () => {
                            const form = modal.querySelector('[data-security-flow]');
                            if (form.dataset.busy) return;
                            form.reset(); stage(form, 'details');
                            ['first_name','last_name','phone_number','email'].forEach(key => { form.elements[key].value = item[key]; });
                            form.elements.resend_id.value = item.id;
                            feedback(form, 'Confirm your password to authorize a new invitation link.');
                            form.elements.current_password.focus();
                        }); actions.append(resend);
                    }
                    const revoke = document.createElement('button'); revoke.type = 'button'; revoke.className = 'ac-button'; revoke.textContent = 'Revoke';
                    revoke.addEventListener('click', () => {
                        const form = modal.querySelector('.ase-revoke'); if (form.dataset.busy) return;
                        revokeId = item.id; form.hidden = false; form.reset(); feedback(form, '');
                        form.querySelector('[data-revoke-email]').textContent = item.email + ' will no longer be able to use this invitation.';
                        form.elements.current_password.focus();
                    }); actions.append(revoke); row.append(actions);
                }
                list.append(row);
            });
        } catch (error) { list.textContent = error.message; }
        finally { listing = false; }
    }
    if (!modal) return;
    const inviteForm = modal.querySelector('[data-security-flow]'), revokeForm = modal.querySelector('.ase-revoke');
    document.querySelectorAll('[data-open-invite]').forEach(button => button.addEventListener('click', () => {
        modal.showModal(); loadInvitations();
    }));
    const busy = () => Boolean(inviteForm.dataset.busy || revokeForm.dataset.busy);
    modal.querySelectorAll('[data-close-invite]').forEach(button => button.addEventListener('click', () => { if (!busy()) modal.close(); }));
    modal.addEventListener('cancel', event => { if (busy()) event.preventDefault(); });
    modal.addEventListener('close', () => {
        resetClosedFlow(inviteForm);
        revokeForm.reset(); revokeForm.hidden = true; feedback(revokeForm, '');
    });
    modal.querySelector('[data-cancel-revoke]').addEventListener('click', () => { if (!busy()) { revokeForm.reset(); revokeForm.hidden = true; } });
    revokeForm.addEventListener('submit', async event => {
        event.preventDefault(); if (busy() || !validateForm(revokeForm)) return;
        revokeForm.dataset.busy = '1'; const button = revokeForm.querySelector('[type=submit]'); button.disabled = true;
        try {
            const result = await post(modal.dataset.revokePattern.replace('00000000-0000-0000-0000-000000000000', revokeId), revokeForm, new FormData(revokeForm));
            notifyInvitation(revokeForm, result.message);
            if (inviteForm.querySelector('.ase-feedback').hasAttribute('data-success')) feedback(inviteForm, '');
            revokeForm.reset(); revokeForm.hidden = true; await loadInvitations();
        } catch (error) { requestError(revokeForm, error); }
        finally { delete revokeForm.dataset.busy; button.disabled = false; }
    });
})();
