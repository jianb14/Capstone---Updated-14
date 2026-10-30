/* Keep existing payment endpoints, CSRF, validation and redirects intact. */
(() => {
    'use strict';
    const root = document.querySelector('[data-payment-workspace]');
    if (!root || root.dataset.mounted) return;
    root.dataset.mounted = 'true';
    const queues = root.querySelector('#pmQueues'), summary = root.querySelector('#pmSummary');
    const filters = root.querySelector('#pmFilters'), notice = root.querySelector('#pmFeedback');
    const detailDialog = root.querySelector('#pmDetailDialog'), detailBody = root.querySelector('#pmDetailBody');
    const confirmDialog = root.querySelector('#pmConfirmDialog'), confirmForm = root.querySelector('#pmConfirmForm');
    const actionNotice = root.querySelector('#pmActionFeedback'), reason = root.querySelector('#pmRejectReason');
    const confirmButton = root.querySelector('#pmConfirmSubmit'), receiptDialog = root.querySelector('#pmReceiptDialog');
    const settingsDialog = root.querySelector('#pmSettingsDialog'), settingsBody = root.querySelector('#pmSettingsBody');
    const settingsSave = root.querySelector('#pmSettingsSave'), reasonError = root.querySelector('#pmReasonError');
    const selects = window.AdminSelects?.create(root);
    let listController, detailController, settingsController, listVersion = 0, timer, action, saving = false, detailURL, detailOrigin;

    function feedback(element, message = '', kind = 'error') {
        element.dataset.kind = kind;
        element.textContent = message;
    }
    function announce(message, kind = 'success') {
        feedback(notice, message, kind);
        if (window.AdminConfigurationFeedback) {
            notice.classList.add('pm-sr-only');
            window.AdminConfigurationFeedback.show(message, kind);
        }
    }
    async function request(url, options = {}) {
        const controller = new AbortController(), abort = () => controller.abort();
        options.signal?.addEventListener('abort', abort, {once: true});
        if (options.signal?.aborted) controller.abort();
        const timeout = setTimeout(abort, options.method === 'POST' ? 45000 : 20000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'text/html'}});
            if (!response.ok) throw new Error(`The request could not be completed (${response.status}). Please refresh and try again.`);
            const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
            if (!doc.querySelector('[data-payment-workspace]')) throw new Error('Your session may have ended. Please refresh the page and sign in again.');
            return doc;
        } catch (error) {
            if (error.name === 'AbortError' && !options.signal?.aborted) throw new Error('The request timed out. Please refresh to check the latest payment status.');
            throw error;
        } finally {
            clearTimeout(timeout);
            options.signal?.removeEventListener('abort', abort);
        }
    }
    function mountFilters() {
        const slot = root.querySelector('#pmHistoryFilterSlot');
        if (slot && filters) slot.append(filters);
    }
    function syncFilters(url) {
        if (!filters) return;
        const params = new URL(url, location.href).searchParams;
        for (const name of ['search', 'status', 'type']) filters.elements[name].value = params.get(name) || '';
        filters.elements.per_page.value = params.get('per_page') === '4' ? '4' : '8';
        if (filters.elements.status.value === 'pending') filters.elements.status.value = '';
        filters.querySelector('.ac-search-clear').hidden = !filters.elements.search.value;
        selects?.sync();
    }
    async function loadQueue(url, push = true) {
        listController?.abort();
        const controller = listController = new AbortController(), version = ++listVersion;
        queues.setAttribute('aria-busy', 'true');
        try {
            const doc = await request(url, {signal: controller.signal});
            if (controller.signal.aborted || version !== listVersion) return false;
            const nextQueues = doc.querySelector('#pmQueues'), nextSummary = doc.querySelector('#pmSummary');
            if (!nextQueues || !nextSummary) throw new Error('Payments could not be loaded. Please refresh the page.');
            // Keep the live controls and their focus while replacing only server-rendered data.
            const focused = filters.contains(document.activeElement) ? document.activeElement : null;
            const selection = focused?.tagName === 'INPUT' ? [focused.selectionStart, focused.selectionEnd] : null;
            root.append(filters);
            selects?.release(queues);
            queues.replaceChildren(...nextQueues.childNodes);
            summary.replaceChildren(...nextSummary.childNodes);
            mountFilters();
            filters.elements.per_page.value = new URL(url, location.href).searchParams.get('per_page') === '4' ? '4' : '8';
            selects?.enhance();
            if (focused) {
                focused.focus({preventScroll: true});
                if (selection) focused.setSelectionRange(...selection);
            }
            if (push && new URL(url, location.href).href !== location.href) history.pushState({}, '', url);
            return true;
        } catch (error) {
            if (!controller.signal.aborted && version === listVersion) {
                notice.classList.remove('pm-sr-only'); feedback(notice, error.message);
                const retry = document.createElement('button');
                retry.type = 'button'; retry.className = 'ac-button'; retry.textContent = 'Try again';
                retry.addEventListener('click', () => { feedback(notice); loadQueue(url, push); }, {once: true});
                notice.append(' ', retry);
            }
            return false;
        } finally {
            if (version === listVersion) queues.removeAttribute('aria-busy');
        }
    }
    function modalState() {
        document.body.classList.toggle('pm-modal-open', !!root.querySelector('dialog[open]'));
    }
    function openDialog(dialog) { if (!dialog.open) dialog.showModal(); modalState(); }
    function closeDialog(dialog) { dialog.close(); modalState(); }
    async function settingsRequest(url, options = {}) {
        const controller = new AbortController(), parent = options.signal;
        const abort = () => controller.abort();
        parent?.addEventListener('abort', abort, {once: true});
        if (parent?.aborted) abort();
        const timeout = setTimeout(abort, 20000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
                headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'}});
            if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Settings could not be loaded. Refresh the page and check that you are signed in.');
            const data = await response.json();
            if (!response.ok && !(response.status === 400 && data.html)) throw new Error('Payment settings could not be saved. Please try again.');
            return data;
        } catch (error) {
            if (error.name === 'AbortError' && !parent?.aborted) throw new Error('The request timed out. Check the current settings before trying again.');
            throw error;
        } finally { clearTimeout(timeout); parent?.removeEventListener('abort', abort); }
    }
    async function openSettings() {
        settingsController?.abort();
        const controller = settingsController = new AbortController();
        settingsSave.disabled = true;
        feedback(settingsBody, 'Loading payment settings…', 'info');
        settingsBody.setAttribute('aria-busy', 'true'); openDialog(settingsDialog);
        try {
            const data = await settingsRequest(settingsDialog.dataset.settingsUrl, {signal: controller.signal});
            if (controller.signal.aborted) return;
            settingsBody.innerHTML = data.html;
            settingsSave.disabled = false;
            settingsBody.querySelector('input:not([type="hidden"])')?.focus({preventScroll: true});
        } catch (error) {
            if (!controller.signal.aborted) {
                feedback(settingsBody, error.message);
                const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'ac-button'; retry.textContent = 'Try again';
                retry.addEventListener('click', openSettings); settingsBody.append(retry);
            }
        } finally { if (settingsController === controller) settingsBody.removeAttribute('aria-busy'); }
    }
    root.addEventListener('submit', async event => {
        if (event.target.id !== 'pmSettingsForm') return;
        event.preventDefault();
        if (saving) return;
        const form = event.target, field = form.elements.downpayment_percent;
        const fieldError = form.querySelector('#pmPercentError'), formError = form.querySelector('#pmSettingsError');
        formError.hidden = true;
        if (!field.checkValidity()) {
            fieldError.textContent = field.value ? 'Enter a whole number from 1 to 100.' : 'Enter the required downpayment percentage.';
            fieldError.hidden = false; field.setAttribute('aria-invalid', 'true'); field.focus(); return;
        }
        const body = new FormData(form), scope = settingsDialog || root.querySelector('.pm-settings-standalone');
        saving = true; settingsSave.disabled = true; settingsSave.textContent = 'Saving…';
        scope.setAttribute('aria-busy', 'true');
        try {
            const data = await settingsRequest(form.action, {method: 'POST', body});
            if (data.ok) {
                if (settingsDialog) closeDialog(settingsDialog);
                announce(data.message);
                if (queues) await loadQueue(location.href, false);
            } else {
                settingsBody.innerHTML = data.html;
                settingsBody.querySelector('[aria-invalid="true"]')?.focus({preventScroll: true});
            }
        } catch (error) {
            formError.textContent = error.message; formError.hidden = false;
        } finally {
            saving = false; settingsSave.disabled = false; settingsSave.textContent = 'Save settings'; scope.removeAttribute('aria-busy');
        }
    });
    root.addEventListener('input', event => {
        if (event.target.name !== 'downpayment_percent') return;
        event.target.removeAttribute('aria-invalid');
        root.querySelector('#pmPercentError').hidden = true;
        root.querySelector('#pmSettingsError').hidden = true;
    });
    async function openDetail(url, origin) {
        detailController?.abort();
        const controller = detailController = new AbortController();
        detailURL = url;
        root.querySelector('#pmDetailTitle').textContent = 'Payment details';
        if (origin) detailOrigin = origin;
        feedback(detailBody, 'Loading payment details…', 'info');
        detailBody.setAttribute('aria-busy', 'true');
        openDialog(detailDialog);
        try {
            const doc = await request(url, {signal: controller.signal});
            if (controller.signal.aborted) return;
            const content = doc.querySelector('#pmPaymentDetail');
            if (!content) throw new Error('Payment details could not be loaded.');
            detailBody.replaceChildren(content);
            root.querySelector('#pmDetailTitle').textContent = content.querySelector('h1')?.textContent || 'Payment details';
        } catch (error) {
            if (!controller.signal.aborted) {
                feedback(detailBody, error.message);
                const link = document.createElement('a'); link.href = url; link.className = 'ac-button'; link.textContent = 'Open payment page';
                detailBody.append(' ', link);
            }
        } finally {
            if (controller === detailController) detailBody.removeAttribute('aria-busy');
        }
    }
    function prepareAction(kind, url, text, origin) {
        if (saving) return;
        clearTimeout(timer);
        action = {kind, url, origin};
        feedback(actionNotice);
        reason.value = ''; reason.setCustomValidity(''); reason.required = kind === 'reject';
        reason.removeAttribute('aria-invalid'); reasonError.hidden = true;
        root.querySelector('#pmReasonField').hidden = kind !== 'reject';
        const titles = {verify: 'Approve this payment?', reject: 'Reject this payment?', reminder: 'Send payment reminder?'};
        root.querySelector('#pmConfirmTitle').textContent = titles[kind];
        root.querySelector('#pmConfirmText').textContent = text;
        confirmButton.textContent = kind === 'verify' ? 'Approve Payment' : kind === 'reject' ? 'Reject Payment' : 'Send Reminder';
        confirmButton.disabled = false;
        openDialog(confirmDialog);
        // Keep accidental Enter presses from confirming a financial action.
        confirmDialog.querySelector('[data-close-dialog]').focus();
    }
    root.addEventListener('click', event => {
        const close = event.target.closest('[data-close-dialog]');
        if (close) { if (!saving) closeDialog(close.closest('dialog')); return; }
        const settings = event.target.closest('[data-payment-settings]');
        if (settings && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault(); if (!saving) openSettings(); return;
        }
        if (event.target.closest('[data-list-reset]')) {
            filters.elements.search.value = ''; filters.elements.status.value = ''; filters.elements.type.value = '';
            filters.querySelector('.ac-search-clear').hidden = true; selects?.sync();
            filters.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return;
        }
        const paymentAction = event.target.closest('[data-payment-action]');
        if (paymentAction) {
            event.preventDefault();
            const kind = paymentAction.dataset.paymentAction;
            prepareAction(kind, paymentAction.dataset.actionUrl || paymentAction.href,
                kind === 'reject' ? 'Please provide a reason for the customer.' : 'This payment will be marked as verified and the customer will be notified.', paymentAction);
            return;
        }
        const receipt = event.target.closest('[data-payment-receipt]');
        if (receipt) { event.preventDefault(); root.querySelector('#pmReceiptImage').src = receipt.href; openDialog(receiptDialog); return; }
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const detail = event.target.closest('[data-payment-detail]');
        if (detail) { event.preventDefault(); openDetail(detail.href, detail); return; }
        const page = event.target.closest('[data-payment-page]');
        if (page && !saving) {
            event.preventDefault(); clearTimeout(timer); feedback(notice);
            const section = page.closest('section').id;
            loadQueue(page.href).then(loaded => {
                if (!loaded) return;
                const current = document.getElementById(section)?.querySelector('[aria-current="page"]');
                if (current) { current.tabIndex = -1; current.focus({preventScroll: true}); }
            });
        }
    });
    root.addEventListener('change', event => {
        const size = event.target.closest('[data-payment-size]');
        if (!size || saving) return;
        clearTimeout(timer); feedback(notice);
        const section = size.closest('section').id, url = new URL(location.href);
        url.searchParams.set('per_page', size.value);
        for (const key of ['page', 'pending_page', 'unpaid_page', 'balance_page', 'paid_page']) url.searchParams.delete(key);
        loadQueue(url.href).then(loaded => {
            if (loaded) document.getElementById(section)?.querySelector('.account-page-size .ac-select-trigger')?.focus({preventScroll: true});
        });
    });
    root.addEventListener('submit', event => {
        const reminder = event.target.closest('[data-payment-reminder]');
        if (!reminder) return;
        event.preventDefault();
        prepareAction('reminder', reminder.action, `Send a payment reminder to ${reminder.dataset.customer} for booking #${reminder.dataset.booking}?`, reminder.querySelector('button'));
    });
    reason.addEventListener('input', () => { reason.setCustomValidity(''); reason.removeAttribute('aria-invalid'); reasonError.hidden = true; });
    confirmForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (saving || !action) return;
        if (action.kind === 'reject' && (!reason.value.trim() || reason.value.trim().length > 2000)) {
            const message = reason.value.trim() ? 'Keep the rejection reason within 2,000 characters.' : 'Enter a reason for rejecting this payment.';
            reason.setCustomValidity(message); reason.setAttribute('aria-invalid', 'true');
            reasonError.textContent = message; reasonError.hidden = false; reason.focus(); return;
        }
        const selected = action, url = new URL(selected.url, location.origin);
        url.searchParams.set('next', 'payments');
        const body = new FormData();
        body.set('csrfmiddlewaretoken', root.querySelector('#pmCsrf input').value);
        if (selected.kind === 'reject') body.set('admin_notes', reason.value.trim());
        saving = true;
        listController?.abort(); ++listVersion;
        queues?.removeAttribute('aria-busy');
        confirmForm.querySelectorAll('button').forEach(button => button.disabled = true);
        reason.disabled = true;
        feedback(actionNotice, 'Saving…', 'info');
        let response;
        try {
            response = await request(url, {method: 'POST', body});
        } catch (error) {
            feedback(actionNotice, `${error.message} Check the latest status before submitting again.`);
            action = null;
        } finally {
            saving = false;
            confirmForm.querySelectorAll('button').forEach(button => button.disabled = false);
            reason.disabled = false;
            confirmButton.disabled = !action;
        }
        if (!response) return;
        const messages = [...response.querySelectorAll('#pmMessages [data-kind]')];
        const kind = messages.some(item => item.dataset.kind.includes('error')) ? 'error'
            : messages.some(item => item.dataset.kind.includes('warning')) ? 'warning' : 'success';
        const message = messages.map(item => item.textContent).join(' ') || 'Request completed. Payment information has been refreshed.';
        action = null;
        closeDialog(confirmDialog);
        announce(message, kind);
        if (queues) {
            await loadQueue(location.href, false);
            if (detailDialog.open) {
                await openDetail(detailURL);
            }
        } else {
            try {
                const doc = await request(location.href), content = doc.querySelector('#pmPaymentDetail');
                if (content) root.querySelector('#pmPaymentDetail').replaceWith(content);
            } catch (error) { feedback(notice, `${message} ${error.message}`, 'warning'); }
        }
    });
    root.querySelectorAll('dialog').forEach(dialog => {
        dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
        dialog.addEventListener('close', () => {
            modalState();
            if (dialog === detailDialog) {
                detailController?.abort();
                if (detailOrigin?.isConnected) detailOrigin.focus({preventScroll: true});
            }
            if (dialog === settingsDialog) settingsController?.abort();
        });
        dialog.addEventListener('click', event => {
            if (event.target !== dialog || saving) return;
            const box = dialog.getBoundingClientRect();
            if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeDialog(dialog);
        });
    });
    if (filters) {
        function applyFilters() {
            if (saving) return;
            clearTimeout(timer); feedback(notice);
            const url = new URL(filters.action);
            for (const [key, value] of new FormData(filters)) if (value) url.searchParams.set(key, value);
            loadQueue(url.href);
        }
        filters.addEventListener('submit', event => { event.preventDefault(); applyFilters(); });
        filters.addEventListener('change', event => { if (event.target.tagName === 'SELECT') applyFilters(); });
        filters.elements.search.addEventListener('input', () => {
            filters.querySelector('.ac-search-clear').hidden = !filters.elements.search.value;
            clearTimeout(timer);
            // Cancel an older response as soon as the user changes the query.
            listController?.abort(); ++listVersion;
            queues.removeAttribute('aria-busy');
            timer = setTimeout(applyFilters, 350);
        });
        filters.querySelector('.ac-search-clear').addEventListener('click', () => {
            filters.elements.search.value = ''; filters.querySelector('.ac-search-clear').hidden = true;
            filters.elements.search.focus(); applyFilters();
        });
        window.addEventListener('popstate', () => { clearTimeout(timer); syncFilters(location.href); loadQueue(location.href, false); });
        mountFilters(); selects?.enhance();
    }
    const initialMessages = [...root.querySelectorAll('#pmMessages [data-kind]')];
    if (initialMessages.length) announce(initialMessages.map(item => item.textContent).join(' '),
        initialMessages.some(item => item.dataset.kind.includes('error')) ? 'error' : 'success');
})();
