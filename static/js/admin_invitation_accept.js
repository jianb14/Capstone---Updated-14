/* A token-free invitation form above the existing login page. */
(() => {
    'use strict';
    const dialog = document.querySelector('[data-admin-accept-modal]');
    if (!dialog) return;
    const form = dialog.querySelector('[data-invitation-accept]');
    const feedback = form?.querySelector('[data-invitation-feedback]');
    const closeButtons = [...dialog.querySelectorAll('[data-close-accept]')];
    let busy = false, navigating = false;
    function syncPasswordRequirements() {
        const value = form.elements.password.value;
        const rules = {length:value.length >= 8, uppercase:/[A-Z]/.test(value), number:/\d/.test(value), special:/[^A-Za-z0-9]/.test(value)};
        Object.entries(rules).forEach(([name, met]) => {
            const node = form.querySelector('#invite-rule-' + name);
            if (!node) return;
            node.classList.toggle('is-valid', met);
            const status = node.querySelector('.password-rule-status');
            const description = met ? 'Met: ' : 'Not met: ';
            if (status && status.textContent !== description) status.textContent = description;
        });
        return rules;
    }
    function fieldError(name, message) {
        const field = form.elements.namedItem(name);
        const node = form.querySelector('[data-invitation-error="' + name + '"]');
        if (!field || !node) return;
        node.textContent = message; node.hidden = !message;
        field.toggleAttribute('aria-invalid', Boolean(message));
        if (message) field.setAttribute('aria-invalid', 'true');
        const describedBy = new Set((field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
        if (message) describedBy.add(node.id); else describedBy.delete(node.id);
        if (describedBy.size) field.setAttribute('aria-describedby', [...describedBy].join(' '));
        else field.removeAttribute('aria-describedby');
    }
    function validate() {
        feedback.textContent = '';
        ['password', 'confirm_password'].forEach(name => fieldError(name, ''));
        const password = form.elements.password.value, confirmation = form.elements.confirm_password.value;
        if (!password) fieldError('password', 'Create a password.');
        else if (!Object.values(syncPasswordRequirements()).every(Boolean)) {
            fieldError('password', 'Password must be at least 8 characters and include 1 uppercase letter, 1 number, and 1 special character.');
        }
        if (!confirmation) fieldError('confirm_password', 'Confirm your password.');
        else if (password && password !== confirmation) fieldError('confirm_password', 'Passwords do not match.');
        const first = form.querySelector('[aria-invalid="true"]');
        if (first) first.focus();
        return !first;
    }
    function setBusy(value) {
        busy = value;
        closeButtons.forEach(button => { button.disabled = value; });
        if (!form) return;
        form.toggleAttribute('aria-busy', value);
        if (value) form.setAttribute('aria-busy', 'true');
        const submit = form.querySelector('[type=submit]'); submit.disabled = value;
        submit.textContent = value ? 'Creating your account...' : 'Create my admin account';
    }
    closeButtons.forEach(button => button.addEventListener('click', () => { if (!busy) dialog.close(); }));
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => {
        document.body.classList.remove('ac-modal-open');
        form?.reset(); window.PasswordVisibility?.reset(dialog);
        history.replaceState(history.state, '', dialog.dataset.loginUrl);
        document.querySelector('#email')?.focus({preventScroll:true});
    });
    if (form) {
        syncPasswordRequirements();
        form.addEventListener('reset', () => { requestAnimationFrame(syncPasswordRequirements); });
        form.addEventListener('input', event => {
            if (event.target.name === 'password') syncPasswordRequirements();
            if (['password', 'confirm_password'].includes(event.target.name)) {
                fieldError(event.target.name, ''); feedback.textContent = '';
            }
        });
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (busy || !validate()) return;
            setBusy(true);
            try {
                const response = await fetch(form.action, {method:'POST', body:new FormData(form), credentials:'same-origin',
                    headers:{'X-Requested-With':'XMLHttpRequest', 'X-CSRFToken':form.elements.csrfmiddlewaretoken.value, 'Accept':'application/json'}});
                if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session could not be confirmed. Reopen the invitation from your email.');
                const result = await response.json();
                if (response.ok && result.success) {
                    navigating = true; form.reset(); window.PasswordVisibility?.reset(form);
                    window.location.assign(result.redirect_url); return;
                }
                Object.entries(result.errors || {}).forEach(([name, messages]) => fieldError(name, messages.join(' ')));
                feedback.textContent = result.message || (result.errors?.__all__ || []).join(' ');
                if (!feedback.textContent && !form.querySelector('[aria-invalid="true"]')) feedback.textContent = 'Your account could not be created. Please try again.';
                form.querySelector('[aria-invalid="true"]')?.focus();
            } catch (error) { feedback.textContent = error.message || 'Unable to connect. Please try again.'; }
            finally { if (!navigating) setBusy(false); }
        });
    }
    document.body.classList.add('ac-modal-open'); dialog.showModal();
    (form?.querySelector('[aria-invalid="true"]') || form?.elements.password)?.focus();
})();
