(() => {
    'use strict';
    const dialog = document.getElementById('adminPasswordModal');
    if (!dialog) return;
    const passwordForm = document.getElementById('adminChangePasswordForm');
    const codeForm = document.getElementById('apPasswordCodeForm');
    const submit = document.getElementById('btnSavePassword');
    const feedback = document.getElementById('apPasswordFeedback');
    const digits = [...codeForm.querySelectorAll('.ap-otp-digit')];
    const resend = document.getElementById('apResendCode');
    const edit = document.getElementById('apEditPassword');
    const expiry = document.getElementById('apCodeExpiry');
    let stage = 'password', busy = false, codePending = dialog.dataset.pendingCode === 'true';
    let expiresAt = 0, resendAt = 0, verifyAt = 0, timer = null, opener = null;
    const time = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    const remaining = at => Math.max(0, Math.ceil((at - Date.now()) / 1000));
    const tell = text => { feedback.textContent = text; feedback.hidden = !text; };
    const fieldError = (name, text) => {
        const node = dialog.querySelector(`[data-error-for="${name}"]`);
        if (node) node.textContent = text;
        const inputs = name === 'code' ? digits : [passwordForm.elements.namedItem(name)];
        inputs.filter(Boolean).forEach(input => {
            if (text) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
        });
    };
    const clearErrors = () => {
        ['old_password', 'new_password1', 'new_password2', 'code'].forEach(name => fieldError(name, ''));
        tell('');
    };
    const checklist = () => {
        const value = passwordForm.elements.new_password1.value;
        const rules = {length: value.length >= 8, uppercase: /[A-Z]/.test(value), number: /\d/.test(value), special: /[^A-Za-z0-9]/.test(value)};
        Object.entries(rules).forEach(([name, valid]) => {
            const row = document.getElementById(`ap-rule-${name}`);
            row.classList.toggle('is-valid', valid);
            row.querySelector('.password-rule-status').textContent = valid ? 'Met: ' : 'Not met: ';
        });
    };
    const tick = () => {
        const isCode = stage === 'code', expired = isCode && remaining(expiresAt) === 0;
        document.getElementById('apCodeExpired').hidden = !expired;
        codeForm.querySelector('[data-password-code-fields]').hidden = expired;
        submit.disabled = busy || (isCode && (expired || remaining(verifyAt) > 0));
        submit.textContent = busy ? (isCode ? 'Verifying…' : 'Sending code…') : isCode ?
            (remaining(verifyAt) ? `Try again in ${time(remaining(verifyAt))}` : 'Verify and change password') : 'Send Verification Code';
        submit.setAttribute('form', isCode ? codeForm.id : passwordForm.id);
        resend.disabled = busy || remaining(resendAt) > 0;
        resend.textContent = remaining(resendAt) ? `Resend in ${time(remaining(resendAt))}` : expired ? 'Send new code' : 'Resend code';
        edit.disabled = busy;
        expiry.textContent = `Code expires in ${time(remaining(expiresAt))}.`;
        dialog.setAttribute('aria-busy', String(busy));
    };
    const setStage = next => {
        stage = next; passwordForm.hidden = next !== 'password'; codeForm.hidden = next !== 'code';
        clearInterval(timer); timer = null;
        if (next === 'code' && dialog.open) timer = setInterval(tick, 1000);
        tick();
    };
    const applyState = result => {
        const now = Date.now();
        if (typeof result.expiry_seconds === 'number') expiresAt = now + result.expiry_seconds * 1000;
        if (typeof result.resend_wait === 'number') resendAt = now + result.resend_wait * 1000;
        if (typeof result.verify_wait === 'number') verifyAt = now + result.verify_wait * 1000;
        document.getElementById('apCodeRecipient').textContent = `Enter the code sent to ${result.masked_email || 'your verified email'}.`;
        tick();
    };
    const request = async (url, data) => {
        const response = await fetch(url, {method:data ? 'POST' : 'GET', ...(data ? {body:data} : {}), credentials:'same-origin',
            headers:{'Accept':'application/json', 'X-Requested-With':'XMLHttpRequest'}});
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Sign in again to continue.');
        return response.json();
    };
    const resetPasswords = () => { passwordForm.reset(); window.PasswordVisibility?.reset(passwordForm); checklist(); };
    const clearDigits = () => digits.forEach(input => { input.value = ''; input.removeAttribute('aria-invalid'); });
    window.openPasswordModal = async () => {
        if (dialog.open || busy) return;
        opener = document.activeElement;
        dialog.showModal(); document.body.classList.add('ac-modal-open');
        clearErrors(); setStage(codePending ? 'code' : 'password');
        if (!codePending) { passwordForm.elements.old_password.focus(); return; }
        busy = true; tick();
        try {
            const result = await request(codeForm.action);
            if (result.restart || !result.success) { codePending = false; setStage('password'); tell(result.message || 'Start your password change again.'); }
            else { applyState(result); digits[0].focus(); }
        } catch (error) { tell(error.message); }
        finally { busy = false; tick(); }
    };
    const close = () => {
        dialog.close();
    };
    dialog.querySelectorAll('[data-close-password]').forEach(button => button.addEventListener('click', close));
    dialog.addEventListener('click', event => { if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
    }});
    dialog.addEventListener('close', () => {
        clearInterval(timer); timer = null; resetPasswords(); clearDigits(); clearErrors();
        if (!document.querySelector('dialog[open]')) document.body.classList.remove('ac-modal-open');
        opener?.focus();
    });
    passwordForm.addEventListener('input', event => { fieldError(event.target.name, ''); tell(''); checklist(); });
    passwordForm.addEventListener('submit', async event => {
        event.preventDefault(); if (busy) return;
        clearErrors(); let first = null;
        const labels = {old_password:'Current password', new_password1:'New password', new_password2:'Confirm new password'};
        Object.entries(labels).forEach(([name,label]) => {
            if (!passwordForm.elements[name].value) { fieldError(name, `${label} is required.`); first ||= passwordForm.elements[name]; }
        });
        if (first) { first.focus(); return; }
        const data = new FormData(passwordForm); busy = true; tick();
        try {
            const result = await request(passwordForm.action, data);
            if (!result.success) {
                Object.entries(result.errors || {}).forEach(([name, errors]) => fieldError(name, errors.join(' ')));
                if (result.errors?.__all__ || !Object.keys(result.errors || {}).length) tell(result.errors?.__all__?.join(' ') || result.message || result.error || 'Unable to send a code. Please try again.');
                passwordForm.querySelector('[aria-invalid=true]')?.focus();
                return;
            }
            resetPasswords(); codePending = true; clearDigits(); setStage('code');
            const state = await request(codeForm.action);
            if (state.restart || !state.success) { codePending = false; setStage('password'); tell(state.message); }
            else { applyState(state); if (dialog.open) digits[0].focus(); }
        } catch (error) { tell(error.message); }
        finally { busy = false; tick(); }
    });
    const submitCode = async action => {
        if (busy) return;
        clearErrors();
        const code = digits.map(el => el.value).join('');
        if (action === 'verify' && !/^[0-9]{6}$/.test(code)) { fieldError('code', 'Enter all 6 digits from your email.'); digits.find(el => !el.value)?.focus(); return; }
        const data = new FormData(codeForm); data.set('action', action); data.set('code', code);
        busy = true; tick();
        try {
            const result = await request(codeForm.action, data); applyState(result);
            if (result.verified) {
                codePending = false; setStage('password'); resetPasswords(); clearDigits(); close();
                const notice = document.getElementById('apFeedback'); notice.textContent = result.message; notice.dataset.kind = 'success'; notice.hidden = false;
                window.AdminConfigurationFeedback?.show(result.message || 'Your password has been updated successfully.');
                return;
            }
            if (result.restart) { codePending = false; setStage('password'); tell(result.message); return; }
            if (!result.success) {
                if (action === 'verify' && !result.verify_wait && remaining(expiresAt)) fieldError('code', result.message || 'Check the code and try again.');
                else tell(result.message || 'Unable to send a new code. Please try again.');
            } else if (action === 'resend') { clearDigits(); if (dialog.open) digits[0].focus(); }
        } catch (error) { tell(error.message); }
        finally { busy = false; tick(); }
    };
    codeForm.addEventListener('submit', event => { event.preventDefault(); submitCode('verify'); });
    resend.addEventListener('click', () => submitCode('resend'));
    edit.addEventListener('click', () => { codePending = false; resetPasswords(); clearDigits(); clearErrors(); setStage('password'); passwordForm.elements.old_password.focus(); });
    const insert = (index, text) => {
        const code = text.replace(/[^0-9]/g, ''); if (!code) return;
        const start = code.length >= 6 ? 0 : index;
        code.slice(0, 6 - start).split('').forEach((value, i) => { digits[start + i].value = value; });
        digits[Math.min(start + code.length, 5)].focus(); fieldError('code', ''); tell('');
    };
    digits.forEach((input, index) => {
        input.addEventListener('paste', event => { event.preventDefault(); insert(index, event.clipboardData.getData('text')); });
        input.addEventListener('input', () => {
            const value = input.value.replace(/[^0-9]/g, ''); input.value = value.slice(-1);
            fieldError('code', ''); tell(''); if (value) digits[Math.min(index + 1, 5)].focus();
        });
        input.addEventListener('keydown', event => {
            if (event.key === 'Backspace' && !input.value && index) { event.preventDefault(); digits[index - 1].value = ''; digits[index - 1].focus(); }
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); digits[Math.max(0, Math.min(5, index + (event.key === 'ArrowLeft' ? -1 : 1)))].focus(); }
        });
        input.addEventListener('focus', () => input.select());
    });
    checklist();
})();
