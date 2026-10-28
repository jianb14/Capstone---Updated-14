(() => {
    'use strict';
    if (window.PasswordVisibility) return;
    const selector = 'button[data-password-target]';

    function setVisible(button, visible) {
        const input = document.getElementById(button.dataset.passwordTarget);
        if (!input) return;
        input.type = visible ? 'text' : 'password';
        button.setAttribute('aria-pressed', String(visible));
        button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${button.dataset.passwordLabel}`);
    }

    function reset(root = document) {
        root.querySelectorAll(selector).forEach(button => setVisible(button, false));
    }

    document.addEventListener('click', event => {
        const button = event.target.closest(selector);
        if (!button || button.disabled) return;
        const input = document.getElementById(button.dataset.passwordTarget);
        if (input) setVisible(button, input.type === 'password');
    });
    document.addEventListener('reset', event => reset(event.target));
    window.addEventListener('pageshow', () => reset());
    window.PasswordVisibility = { reset };
})();
