/* Shared feedback for async admin actions, without a CDN. */
(() => {
    'use strict';
    if (window.AdminConfigurationFeedback) return;
    const toast = document.createElement('div');
    toast.className = 'ac-workspace cfg-toast'; toast.hidden = true;
    toast.setAttribute('role', 'status'); toast.setAttribute('aria-live', 'polite');
    toast.setAttribute('aria-atomic', 'true');
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>';
    const text = document.createElement('span'); text.className = 'cfg-toast-text';
    const close = document.createElement('button'); close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
    toast.append(icon, text, close); document.body.append(toast);
    const popover = typeof toast.showPopover === 'function';
    if (popover) toast.setAttribute('popover', 'manual');
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
    let timer, exitTimer, deadline = 0, remaining = 0, closing = false;
    const finishHide = () => {
        clearTimeout(timer); clearTimeout(exitTimer);
        if (popover && toast.matches(':popover-open')) toast.hidePopover();
        toast.hidden = true;
        toast.classList.remove('is-visible', 'is-leaving');
        closing = false;
    };
    const hide = () => {
        clearTimeout(timer);
        if (toast.hidden || closing) return;
        if (reducedMotion.matches) { finishHide(); return; }
        const current = getComputedStyle(toast);
        toast.style.setProperty('--cfg-toast-exit-opacity', current.opacity);
        toast.style.setProperty('--cfg-toast-exit-transform', current.transform);
        closing = true;
        toast.classList.remove('is-visible'); toast.classList.add('is-leaving');
        // Keep the popover in the top layer until its exit animation finishes.
        exitTimer = setTimeout(finishHide, 170);
    };
    const pause = () => {
        if (timer) remaining = Math.max(0, deadline - performance.now());
        clearTimeout(timer); timer = null;
    };
    const schedule = () => {
        clearTimeout(timer);
        timer = null;
        if (toast.hidden || closing || document.hidden || toast.matches(':hover,:focus-within')) return;
        deadline = performance.now() + remaining;
        timer = setTimeout(hide, remaining);
    };
    close.addEventListener('click', hide);
    toast.addEventListener('pointerenter', pause);
    toast.addEventListener('pointerleave', schedule);
    toast.addEventListener('focusin', pause);
    toast.addEventListener('focusout', () => requestAnimationFrame(schedule));
    document.addEventListener('visibilitychange', () => document.hidden ? pause() : schedule());
    window.AdminConfigurationFeedback = {
        show(message, kind = 'success') {
            if (!message) return;
            const alreadyVisible = !toast.hidden && !closing;
            clearTimeout(timer); clearTimeout(exitTimer);
            closing = false;
            if (!alreadyVisible) toast.classList.remove('is-visible', 'is-leaving');
            toast.dataset.kind = kind;
            icon.innerHTML = kind === 'error' ? '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/>' :
                '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>';
            toast.hidden = false;
            if (popover && !toast.matches(':popover-open')) toast.showPopover();
            text.textContent = message;
            // Replace an open message without making the whole toast jump again.
            if (!alreadyVisible) {
                void toast.offsetWidth;
                toast.classList.add('is-visible');
            }
            remaining = 3000;
            schedule();
        },
        hide
    };
})();
