/* Client feedback: local, accessible toasts and confirmation dialogs. */
(function (global) {
    'use strict';
    if (global.AppToast) return;
    const DEDUPE_WINDOW_MS = 1500;
    const toastQueue = [], recent = new Map();
    let activeToast = null, dialogQueue = Promise.resolve(), dialogId = 0;
    const reducedMotion = () => global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }
    function icon(paths) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
        // Only fixed, application-owned SVG paths enter this markup.
        svg.innerHTML = paths;
        return svg;
    }
    function dismissButton(label, className) {
        const button = element('button', className);
        button.type = 'button'; button.setAttribute('aria-label', label);
        button.append(icon('<path d="m6 6 12 12M18 6 6 18"/>'));
        return button;
    }
    function afterBody(callback) {
        if (document.body) callback();
        else document.addEventListener('DOMContentLoaded', callback, {once: true});
    }
    function promoteToast(toast, parent) {
        if (toast.matches(':popover-open')) toast.hidePopover();
        (parent || Array.from(document.querySelectorAll('dialog:modal')).pop() || document.body).append(toast);
        if (typeof toast.showPopover === 'function') toast.showPopover();
        const owner = toast.parentElement;
        if (owner.tagName === 'DIALOG') owner.addEventListener('close', () => {
            if (toast.isConnected && toast.parentElement === owner) promoteToast(toast);
        }, {once: true});
    }
    function nextToast() {
        if (activeToast || !toastQueue.length) return;
        const {options, resolve, key} = toastQueue.shift();
        const kind = ['success', 'error', 'warning', 'info'].includes(options.icon) ? options.icon : 'info';
        const toast = element('div', 'ac-workspace cfg-toast client-feedback-toast');
        toast.dataset.kind = kind;
        toast.setAttribute('role', 'status'); toast.setAttribute('aria-live', 'polite'); toast.setAttribute('aria-atomic', 'true');
        toast.setAttribute('popover', 'manual');
        const paths = kind === 'success'
            ? '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>'
            : '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/>';
        toast.append(icon(paths), element('span', 'cfg-toast-text', options.message));
        const close = dismissButton('Dismiss notification', 'client-feedback-dismiss');
        toast.append(close); document.body.append(toast);
        let timer, startedAt, leaving = false;
        let remaining = options.timer === 0 ? 0 : Math.max(1500, Number(options.timer) || 3000);
        function pause() {
            if (timer) { clearTimeout(timer); timer = null; remaining = Math.max(0, remaining - (Date.now() - startedAt)); }
        }
        function resume() {
            if (leaving || options.timer === 0 || document.hidden || toast.matches(':hover') || toast.contains(document.activeElement)) return;
            if (timer) clearTimeout(timer);
            startedAt = Date.now(); timer = setTimeout(() => hide('timer'), remaining);
        }
        function onVisibility() { document.hidden ? pause() : resume(); }
        function hide(dismiss) {
            if (leaving) return;
            leaving = true; pause();
            toast.classList.remove('is-visible'); toast.classList.add('is-leaving');
            document.removeEventListener('visibilitychange', onVisibility);
            setTimeout(() => {
                toast.remove(); activeToast = null;
                resolve({isDismissed: true, dismiss}); nextToast();
            }, reducedMotion() ? 0 : 160);
        }
        activeToast = {node: toast, hide, key};
        close.addEventListener('click', () => hide('close'));
        toast.addEventListener('pointerenter', pause); toast.addEventListener('pointerleave', resume);
        toast.addEventListener('focusin', pause); toast.addEventListener('focusout', () => setTimeout(resume, 0));
        document.addEventListener('visibilitychange', onVisibility);
        promoteToast(toast);
        toast.classList.add('is-visible'); resume();
    }
    function fire(options = {}) {
        const message = String(options.text || options.titleText || options.title || '');
        if (!message) return Promise.resolve({isDismissed: true});
        const now = Date.now(), key = (options.icon || 'info') + '|' + message;
        for (const [id, time] of recent) if (now - time >= DEDUPE_WINDOW_MS) recent.delete(id);
        if (recent.has(key) || toastQueue.some(item => item.key === key) || activeToast?.key === key) {
            return Promise.resolve({isDismissed: true, dismiss: 'duplicate'});
        }
        recent.set(key, now);
        return new Promise(resolve => {
            toastQueue.push({options: {...options, message}, key, resolve}); afterBody(nextToast);
        });
    }
    function showConfirmation(options) {
        return new Promise(resolve => afterBody(() => {
            const opener = document.activeElement, id = 'client-confirm-' + (++dialogId);
            const previousOverflow = document.documentElement.style.overflow;
            const dialog = element('dialog', 'client-feedback-dialog');
            dialog.setAttribute('aria-labelledby', id + '-title');
            const header = element('header', 'client-feedback-header');
            const heading = element('h2', 'client-feedback-title', options.title || 'Continue?');
            heading.id = id + '-title';
            const close = dismissButton('Close confirmation', 'client-feedback-close');
            header.append(heading, close); dialog.append(header);
            if (options.text) {
                const message = element('p', 'client-feedback-message', options.text);
                message.id = id + '-message'; dialog.setAttribute('aria-describedby', message.id); dialog.append(message);
            }
            let input, error;
            if (options.input) {
                const group = element('div', 'client-feedback-field');
                const label = element('label', '', options.inputLabel || 'Reason'); label.htmlFor = id + '-input';
                input = element(options.input === 'textarea' ? 'textarea' : 'input', 'client-feedback-input'); input.id = label.htmlFor;
                if (input.tagName === 'INPUT') input.type = ['text', 'email', 'password', 'tel'].includes(options.input) ? options.input : 'text';
                input.placeholder = options.inputPlaceholder || ''; input.value = options.inputValue || '';
                if (input.tagName === 'TEXTAREA') input.rows = 4;
                for (const [name, value] of Object.entries(options.inputAttributes || {})) {
                    if (['maxlength', 'minlength', 'rows', 'inputmode', 'autocomplete'].includes(name.toLowerCase())) input.setAttribute(name, value);
                }
                error = element('p', 'client-feedback-field-error'); error.id = id + '-error'; error.hidden = true;
                error.setAttribute('aria-live', 'polite'); input.setAttribute('aria-describedby', error.id);
                input.addEventListener('input', () => { error.hidden = true; error.textContent = ''; input.removeAttribute('aria-invalid'); });
                group.append(label, input, error); dialog.append(group);
            }
            const actions = element('footer', 'client-feedback-actions');
            const cancel = element('button', 'client-feedback-button', options.cancelText || 'Cancel');
            const approve = element('button', 'client-feedback-button ' + (options.danger ? 'client-feedback-danger' : 'client-feedback-primary'), options.confirmText || 'Continue');
            cancel.type = approve.type = 'button'; actions.append(cancel, approve); dialog.append(actions);
            let finished = false;
            function finish(confirmed, dismiss = 'cancel') {
                if (finished) return;
                finished = true;
                dialog.close();
                document.documentElement.style.overflow = previousOverflow;
                if (activeToast?.node.parentElement === dialog) promoteToast(activeToast.node);
                dialog.remove();
                if (options.returnFocus !== false && opener?.isConnected) opener.focus({preventScroll: true});
                resolve({isConfirmed: confirmed, isDismissed: !confirmed, value: confirmed ? input?.value : undefined, dismiss: confirmed ? undefined : dismiss});
            }
            close.addEventListener('click', () => finish(false, 'close')); cancel.addEventListener('click', () => finish(false));
            dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false, 'esc'); });
            // A click outside the dialog closes it; clicks in its padding do not.
            let outside = false;
            const isOutside = event => { const r = dialog.getBoundingClientRect(); return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom; };
            dialog.addEventListener('pointerdown', event => { outside = event.target === dialog && isOutside(event); });
            dialog.addEventListener('click', event => { if (outside && event.target === dialog && isOutside(event)) finish(false, 'backdrop'); outside = false; });
            // Underlying custom modal key handlers must not handle this dialog.
            dialog.addEventListener('keydown', event => event.stopPropagation());
            approve.addEventListener('click', async () => {
                if (approve.disabled) return;
                approve.disabled = true;
                try {
                    const message = input && options.inputValidator ? await options.inputValidator(input.value) : '';
                    if (finished) return;
                    if (message) {
                        error.textContent = String(message); error.hidden = false;
                        input.setAttribute('aria-invalid', 'true'); input.focus({preventScroll: true});
                    } else finish(true);
                } catch (_) {
                    if (error && !finished) { error.textContent = 'Unable to validate this field. Please try again.'; error.hidden = false; }
                } finally { approve.disabled = false; }
            });
            document.body.append(dialog); dialog.showModal();
            document.documentElement.style.overflow = 'hidden';
            (input || cancel).focus({preventScroll: true});
            // Re-promote any visible toast above the newly opened modal.
            if (activeToast) promoteToast(activeToast.node, dialog);
        }));
    }
    global.AppToast = {
        fire,
        mixin: (defaults = {}) => ({fire: (options = {}) => fire({...defaults, ...options})}),
        confirm: (options = {}) => {
            const result = dialogQueue.then(() => showConfirmation(options));
            dialogQueue = result.catch(() => {}); return result;
        },
        close: () => activeToast?.hide('close'), DEDUPE_WINDOW_MS
    };
    // Preserve feedback after the existing design-library refresh, never on an unrelated page.
    global.AppToast.onNextPage = options => {
        try { sessionStorage.setItem('client-feedback-next', JSON.stringify({options, path: location.pathname, until: Date.now() + 15000})); } catch (_) {}
    };
    afterBody(() => {
        try {
            const saved = JSON.parse(sessionStorage.getItem('client-feedback-next') || 'null');
            sessionStorage.removeItem('client-feedback-next');
            if (saved?.path === location.pathname && saved.until > Date.now()) fire(saved.options);
        } catch (_) {}
    });
})(window);
