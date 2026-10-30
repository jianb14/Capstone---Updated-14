(() => {
    'use strict';
    const root = document.querySelector('[data-booking-workspace]');
    if (!root) return;
    const content = root.querySelector('[data-workspace-content]'), details = root.querySelector('#abDetails'),
        modalContent = details.querySelector('[data-modal-content]'), confirm = root.querySelector('#abConfirm'),
        confirmForm = confirm.querySelector('form'), image = root.querySelector('#abImage'),
        selects = window.AdminSelects.create(root), base = root.dataset.queueUrl;
    let listController, modalController, listSequence = 0, modalSequence = 0, searchTimer, modalURL = '',
        previewURL = '', map, actionTarget, posting = false, errorSequence = 0;
    const headers = {'X-Requested-With': 'XMLHttpRequest'};
    const csrf = () => root.querySelector('[name=csrfmiddlewaretoken]').value;
    const feedback = (message, kind = 'success') => window.AdminConfigurationFeedback.show(message, kind);
    const showError = (node, message) => { node.textContent = message; node.hidden = !message; };
    function queueURL(value = location.href) {
        const url = new URL(value, location.href);
        ['open_booking', 'open_change', 'section', 'from_notif'].forEach(key => url.searchParams.delete(key));
        return url;
    }
    function setURL(url, replace = false) {
        if (url.href !== location.href) history[replace ? 'replaceState' : 'pushState']({}, '', url);
    }
    async function json(url, options = {}) {
        const response = await fetch(url, {...options, credentials: 'same-origin', headers: {...headers, ...options.headers}});
        const loginRedirect = response.redirected && new URL(response.url, location.origin).pathname === '/login/';
        if (response.status === 401 || loginRedirect) {
            throw new Error('Your session has ended. Sign in again to continue.');
        }
        const responseError = response.status === 403 ? 'You do not have permission to complete this action.'
            : response.status === 404 ? 'This record could not be found. Refresh the list and try again.'
            : response.status === 429 ? 'Too many requests. Please wait a moment and try again.'
            : response.status >= 500 ? 'The server could not load this information. Please try again.'
            : 'The server returned an unexpected response. Please try again.';
        if (response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
            throw new Error(responseError);
        }
        let data;
        try { data = await response.json(); }
        catch (error) { if (error.name === 'AbortError') throw error; throw new Error(responseError); }
        if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error(responseError);
        if (!response.ok || data.success === false) {
            const error = new Error(data.message || responseError);
            error.fields = data.errors || {}; throw error;
        }
        return data;
    }
    function enhance() { selects.enhance(); }
    async function loadList(url, mode = 'push') {
        clearTimeout(searchTimer); listController?.abort(); listController = new AbortController();
        const sequence = ++listSequence;
        content.setAttribute('aria-busy', 'true');
        const errorNode = root.querySelector('[data-load-error]'); showError(errorNode, '');
        try {
            const data = await json(url, {signal: listController.signal});
            if (sequence !== listSequence) return;
            const focused = content.contains(document.activeElement) ? document.activeElement : null,
                name = focused?.name, selection = focused?.type === 'search' ? focused.selectionStart : null;
            selects.release(content); content.innerHTML = data.html; enhance();
            if (mode !== 'none') setURL(new URL(url), mode === 'replace');
            if (name && selection !== null) {
                const input = content.querySelector(`input[name="${name}"]`);
                input?.focus({preventScroll: true}); input?.setSelectionRange(selection, selection);
            }
        } catch (error) {
            if (error.name !== 'AbortError') { showError(errorNode, `${error.message} Your last results are still shown.`); }
        } finally { if (sequence === listSequence) content.removeAttribute('aria-busy'); }
    }
    function filtersURL() {
        const form = content.querySelector('[data-booking-filters]'), url = new URL(base, location.origin);
        url.search = new URLSearchParams(new FormData(form)).toString(); return url;
    }
    function applyFilters() {
        const form = content.querySelector('[data-booking-filters]'), from = form.elements.date_from, to = form.elements.date_to;
        if (from?.value && to?.value && from.value > to.value) {
            showError(content.querySelector('[data-filter-error]'), 'The end date must be on or after the start date.');
            to.focus(); return;
        }
        loadList(filtersURL());
    }
    function cleanModal() {
        if (previewURL) URL.revokeObjectURL(previewURL);
        previewURL = ''; map?.destroy(); map = null; selects.release(modalContent);
    }
    function modalState(url) {
        const locationURL = queueURL(), path = url.pathname, booking = path.match(/\/bookings\/(\d+)\//),
            change = path.match(/\/booking-changes\/(\d+)\//);
        if (booking) locationURL.searchParams.set('open_booking', booking[1]);
        if (change) locationURL.searchParams.set('open_change', change[1]);
        if (url.searchParams.get('section') === 'design') locationURL.searchParams.set('section', 'design');
        setURL(locationURL);
    }
    async function openModal(value, updateHistory = true) {
        const url = new URL(value, location.href);
        if (updateHistory) modalState(url);
        modalController?.abort(); modalController = new AbortController(); const sequence = ++modalSequence;
        modalURL = url.href; cleanModal();
        modalContent.innerHTML = '<header class="ab-modal-header"><h2 id="abModalTitle">Loading booking…</h2><button type="button" class="ac-close" data-dialog-close aria-label="Close details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></header><div class="ab-modal-body"><p role="status">Please wait…</p></div>';
        if (!details.open) details.showModal();
        document.body.classList.add('ab-modal-open');
        try {
            const data = await json(url, {signal: modalController.signal});
            if (sequence !== modalSequence || !details.open) return;
            modalContent.innerHTML = data.html;
            modalContent.querySelectorAll('.change-action-form').forEach(form => {
                form.noValidate = true; form.dataset.asyncForm = '';
                form.querySelectorAll('[required]').forEach(input => {
                    const label = form.querySelector(`label[for="${input.id}"]`) || input.closest('label');
                    if (label && !label.querySelector('.ab-required')) {
                        const marker = document.createElement('span'); marker.className = 'ab-required'; marker.textContent = '*'; label.append(marker);
                    }
                });
            });
            modalContent.querySelectorAll('a:has(img)').forEach(link => {
                link.dataset.imageSrc = link.href;
                link.removeAttribute('target');
            });
            const submission = modalContent.querySelector('[data-submission-id]');
            if (submission) submission.value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const venue = modalContent.querySelector('#abVenueMap');
            if (venue && window.BookingLocationMap && window.L) {
                try { map = window.BookingLocationMap.initReadOnly({mapId: venue.id, lat: venue.dataset.lat, lng: venue.dataset.lng, label: venue.dataset.venue, expandable: false}); } catch (_) { venue.textContent = 'Map unavailable. See the venue address above.'; }
            }
            enhance();
            modalContent.querySelector('.ac-close')?.focus({preventScroll: true});
        } catch (error) {
            if (error.name !== 'AbortError' && sequence === modalSequence) {
                modalContent.querySelector('#abModalTitle').textContent = 'Unable to load details';
                const body = modalContent.querySelector('.ab-modal-body'), message = document.createElement('p');
                body.classList.add('ab-modal-error'); message.setAttribute('role', 'alert'); message.textContent = error.message;
                const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'ac-button'; retry.textContent = 'Try again';
                retry.addEventListener('click', () => openModal(url.href, updateHistory)); body.replaceChildren(message, retry);
            }
        }
    }
    function closeDialog(dialog) {
        if (posting && dialog !== image) return;
        dialog.close();
        if (![details, confirm, image].some(item => item.open)) document.body.classList.remove('ab-modal-open');
    }
    details.addEventListener('close', () => {
        // A history navigation can reopen the dialog before its queued close event.
        if (details.open) return;
        modalController?.abort(); ++modalSequence; cleanModal(); document.body.classList.remove('ab-modal-open');
        if (image.open) image.close(); modalURL = ''; setURL(queueURL(), true);
    });
    for (const dialog of [details, confirm, image]) {
        dialog.addEventListener('cancel', event => { if (posting && dialog !== image) event.preventDefault(); });
        dialog.addEventListener('click', event => { if (event.target === dialog) closeDialog(dialog); });
    }
    function clearErrors(form) {
        form.querySelectorAll('.ab-error').forEach(node => { node.hidden = true; node.textContent = ''; });
        form.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
    }
    function fieldError(form, name, message) {
        const input = form.elements.namedItem(name);
        if (!input || !input.tagName) return false;
        input.setAttribute('aria-invalid', 'true');
        let node = form.querySelector(`[data-error-for="${name}"]`);
        if (!node) {
            node = document.createElement('p'); node.className = 'ab-error'; node.dataset.errorFor = name;
            (input.closest('label.change-consent') || input).after(node);
        }
        if (!node.id) node.id = `abError-${name}-${++errorSequence}`;
        input.setAttribute('aria-describedby', node.id); showError(node, message); return true;
    }
    function formError(form, message) {
        let node = form.querySelector('[data-form-error]');
        if (!node) { node = document.createElement('p'); node.className = 'ab-error'; node.dataset.formError = ''; node.setAttribute('role', 'alert'); form.append(node); }
        showError(node, message);
    }
    function focusError(form) {
        const input = form.querySelector('[aria-invalid=true]');
        // The hidden file input must not scroll the dialog's fixed header/form.
        const target = input?.type === 'file' ? form.querySelector('[data-browse]') : input;
        if (target) { target.focus({preventScroll: true}); target.scrollIntoView({block: 'nearest'}); }
    }
    function validate(form) {
        clearErrors(form); let valid = true;
        for (const input of form.querySelectorAll('input,textarea,select')) {
            if (input.type === 'hidden' || input.disabled) continue;
            const empty = input.type === 'checkbox' ? !input.checked : input.type === 'file' ? !input.files.length : !input.value.trim();
            if (input.required && empty) { fieldError(form, input.name, input.type === 'checkbox' ? 'Please acknowledge this before continuing.' : 'This field is required.'); valid = false; }
            else if (!input.validity.valid) { fieldError(form, input.name, input.type === 'number' ? 'Enter a valid amount between 0 and 99,999,999.99, with up to 2 decimal places.' : 'Check this field and try again.'); valid = false; }
        }
        if (!valid) focusError(form); return valid;
    }
    function busy(form, state) {
        form.dataset.busy = state ? 'true' : '';
        form.querySelectorAll('button[type=submit]').forEach(button => { button.disabled = state; });
        form.setAttribute('aria-busy', String(state));
    }
    async function post(form, url, data, options = {}) {
        if (posting || form.dataset.busy === 'true') return;
        posting = true; busy(form, true);
        try {
            const result = await json(url, {method: 'POST', body: data, headers: {'X-CSRFToken': csrf()}});
            feedback(result.message);
            if (options.confirm) confirm.close();
            await loadList(queueURL(), 'none');
            if (details.open && modalURL) await openModal(modalURL, false);
        } catch (error) {
            let inline = false;
            for (const [name, message] of Object.entries(error.fields || {})) inline = fieldError(form, name, message) || inline;
            if (!inline) formError(form, error.message);
            focusError(form);
        } finally { posting = false; busy(form, false); }
    }
    function askAction(button) {
        actionTarget = button;
        const action = button.dataset.action, titles = {'approve': 'Approve booking', 'deny': 'Deny booking', 'complete': 'Mark as completed', 'delete-design': 'Delete design image'},
            copy = {'approve': 'Approve this reservation and notify the customer to pay before the deadline. Overlapping pending bookings may be cancelled.',
                'deny': 'The customer will receive your reason. This only applies to pending bookings.',
                'complete': 'Confirm that this event has been fulfilled. The customer will be invited to leave a review.',
                'delete-design': 'This image will no longer be visible to the customer. Deleting the latest design may reopen the design task.'};
        clearErrors(confirmForm); confirm.querySelector('#abConfirmTitle').textContent = `${titles[action]} · #${button.dataset.booking}`;
        confirm.querySelector('[data-confirm-description]').textContent = copy[action];
        confirm.querySelector('[data-deny-field]').hidden = action !== 'deny';
        confirmForm.elements.deny_reason.required = action === 'deny'; confirmForm.elements.deny_reason.disabled = action !== 'deny'; confirmForm.elements.deny_reason.value = '';
        confirm.querySelector('[data-confirm-submit]').textContent = titles[action]; confirm.showModal();
    }
    function selectedFile(input) {
        const form = input.form, file = input.files[0], preview = form.querySelector('.ab-upload-preview');
        if (previewURL) URL.revokeObjectURL(previewURL); previewURL = ''; preview.hidden = true;
        const node = form.querySelector('[data-error-for=design_image]'); showError(node, ''); input.removeAttribute('aria-invalid');
        if (!file) return;
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || !/\.(jpe?g|png|webp)$/i.test(file.name)) {
            input.value = ''; fieldError(form, input.name, 'Choose a JPG, PNG or WEBP image.'); return;
        }
        if (file.size > 5 * 1024 * 1024) { input.value = ''; fieldError(form, input.name, 'Image must be 5 MB or smaller.'); return; }
        previewURL = URL.createObjectURL(file); preview.querySelector('img').src = previewURL;
        preview.querySelector('span').textContent = file.name; preview.hidden = false;
    }
    root.addEventListener('click', event => {
        const button = event.target.closest('button,a'); if (!button) return;
        if (button.matches('[data-booking-modal]')) {
            if (event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault(); if (!posting) openModal(button.href); return;
        }
        if (button.matches('[data-queue-link],[data-list-page]')) {
            if (event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault(); loadList(new URL(button.href)); return;
        }
        if (button.matches('[data-dialog-close]')) { closeDialog(button.closest('dialog')); return; }
        if (button.matches('[data-history-toggle]')) {
            const expanded = button.getAttribute('aria-expanded') !== 'true';
            modalContent.querySelectorAll('[data-history-extra]').forEach(item => { item.hidden = !expanded; });
            button.setAttribute('aria-expanded', String(expanded)); button.textContent = expanded ? 'Show less' : 'Show more';
            if (!expanded) button.scrollIntoView({block: 'nearest'});
            return;
        }
        if (button.matches('[data-action-url]')) { if (!posting) askAction(button); return; }
        if (button.matches('[data-image-src]')) {
            event.preventDefault();
            image.querySelector('img').src = button.dataset.imageSrc; image.showModal(); return;
        }
        if (button.matches('[data-dates-toggle]')) {
            const dates = content.querySelector('#abDates'); dates.hidden = !dates.hidden; button.setAttribute('aria-expanded', String(!dates.hidden));
        }
        if (button.matches('[data-search-clear]')) {
            const search = button.parentNode.querySelector('input'); search.value = ''; button.hidden = true; search.focus(); applyFilters();
        }
        if (button.matches('[data-dates-reset]')) { ['date_from', 'date_to'].forEach(name => content.querySelector(`[name=${name}]`).value = ''); applyFilters(); }
        if (button.matches('[data-list-reset]')) {
            const url = new URL(base, location.origin), tab = content.querySelector('[name=tab]').value;
            url.searchParams.set('tab', tab); if (tab === 'requests') url.searchParams.set('scope', content.querySelector('[name=scope]').value);
            loadList(url);
        }
        if (button.matches('[data-browse]')) button.closest('form').querySelector('[data-design-file]').click();
        if (button.matches('[data-remove-file]')) { const file = button.closest('form').querySelector('[data-design-file]'); file.value = ''; selectedFile(file); }
    });
    root.addEventListener('input', event => {
        if (event.target.matches('.ac-search input')) {
            // Invalidate immediately, before the next debounced request starts.
            // An older response must never overwrite freshly typed text.
            listController?.abort(); ++listSequence; content.removeAttribute('aria-busy');
            event.target.parentNode.querySelector('[data-search-clear]').hidden = !event.target.value;
            clearTimeout(searchTimer); searchTimer = setTimeout(applyFilters, 300);
        }
        if (event.target.form?.hasAttribute('data-async-form')) {
            const node = event.target.form.querySelector(`[data-error-for="${event.target.name}"]`);
            if (node) showError(node, ''); event.target.removeAttribute('aria-invalid');
            if (event.target.name === 'caption') {
                event.target.form.querySelector('[data-caption-count]').textContent = `${event.target.value.length}/255`;
            }
        }
    });
    root.addEventListener('change', event => {
        if (event.target.matches('[data-list-size]')) { content.querySelector('[name=per_page]').value = event.target.value; applyFilters(); }
        else if (event.target.closest('[data-booking-filters]') && event.target.matches('select')) applyFilters();
        if (event.target.matches('[data-design-file]')) selectedFile(event.target);
    });
    root.addEventListener('submit', event => {
        const form = event.target;
        if (form.matches('[data-booking-filters]')) { event.preventDefault(); applyFilters(); }
        if (form.matches('[data-async-form], [data-confirm-form]')) {
            event.preventDefault(); if (!validate(form)) return;
            const url = form === confirmForm ? actionTarget.dataset.actionUrl : form.action;
            post(form, url, new FormData(form), {confirm: form === confirmForm});
        }
    });
    for (const name of ['dragover', 'dragleave', 'drop']) root.addEventListener(name, event => {
        const zone = event.target.closest('[data-dropzone]'); if (!zone) return;
        event.preventDefault(); zone.classList.toggle('is-over', name === 'dragover');
        if (name === 'drop' && !posting) {
            const input = zone.querySelector('input');
            if (event.dataTransfer.files.length !== 1) { fieldError(input.form, input.name, 'Choose one image at a time.'); return; }
            input.files = event.dataTransfer.files; selectedFile(input);
        }
    });
    function fromLocation() {
        const url = new URL(location.href), booking = url.searchParams.get('open_booking'), change = url.searchParams.get('open_change');
        let target;
        if (/^\d+$/.test(booking || '')) {
            target = root.dataset.detailPattern.replace('/0/', `/${booking}/`);
            if (url.searchParams.get('section') === 'design') target += '?section=design';
        } else if (/^\d+$/.test(change || '')) target = root.dataset.changePattern.replace('/0/', `/${change}/`);
        if (target) openModal(target, false); else if (details.open) details.close();
    }
    addEventListener('popstate', () => { fromLocation(); loadList(queueURL(), 'none'); });
    enhance(); fromLocation();
})();
