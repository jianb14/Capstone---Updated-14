AccountPages.register('report_concern', 'concern', function(scope) {
    'use strict';
    const form = document.getElementById('concernForm');
    if (!form) return;
    const submit = document.getElementById('concernSubmit');
    const feedback = document.getElementById('concernSubmitStatus');
    const historyFeedback = document.getElementById('concernHistoryFeedback');
    const category = document.getElementById('category');
    const dropdown = document.getElementById('categoryDropdown');
    const trigger = dropdown.querySelector('.dropdown-trigger');
    const options = Array.from(dropdown.querySelectorAll('.dropdown-options li'));
    const other = document.getElementById('other_category');
    const otherWrap = document.getElementById('otherCategoryWrap');
    const subject = document.getElementById('subject');
    const subjectCount = document.getElementById('concernSubjectCount');
    const message = document.getElementById('message');
    const imageInput = document.getElementById('concern_images');
    const previews = document.getElementById('concernImagePreview');
    const uploadZone = document.getElementById('concernUploadZone');
    const uploadFeedback = document.getElementById('concernUploadFeedback');
    const detail = document.getElementById('concernDetailModal');
    const confirm = document.getElementById('concernCancelModal');
    const cancelForm = document.getElementById('cancelConcernForm');
    const cancelSubmit = document.getElementById('confirmCancelConcern');
    const cancelFeedback = document.getElementById('cancelConcernFeedback');
    const lightbox = document.getElementById('concernImageLightbox');
    const tickets = new Map();
    function syncTickets() {
        tickets.clear();
        JSON.parse(document.getElementById('concern-ticket-data').textContent).forEach(ticket=>tickets.set(String(ticket.id),ticket));
    }
    syncTickets();
    AccountPages.listen(scope.root,'account:list-updated',syncTickets);
    let submitting = false;
    let cancelling = false;
    let attempted = false;
    let activeTicket = null;
    let cancelTicket = null;
    let files = [];

    function announce(element, text, error = false) {
        if (!element) return;
        element.textContent = text;
        element.classList.toggle('is-error', error);
    }
    function fieldError(id, text) {
        const element = document.getElementById(id + '_error');
        if (element) { element.textContent = text; element.classList.toggle('show', !!text); }
        const input = document.getElementById(id);
        if (input) { input.classList.toggle('has-error', !!text); input.setAttribute('aria-invalid', String(!!text)); }
        if (id === 'category') dropdown.classList.toggle('has-error', !!text);
    }
    function validate() {
        const errors = {
            category: category.value ? '' : 'Please select a category.',
            other_category: category.value === 'other' && !other.value.trim() ? 'Please specify the concern type.' : '',
            subject: subject.value.trim() ? '' : 'Please enter a subject.',
            message: message.value.trim() ? '' : 'Please enter your message.'
        };
        Object.entries(errors).forEach(([id, text]) => fieldError(id, text));
        return Object.keys(errors).find(id => errors[id]);
    }
    function toggleMenu(open) {
        dropdown.classList.toggle('open', open);
        trigger.setAttribute('aria-expanded', String(open));
    }
    function syncCategory() {
        document.getElementById('categoryDropdownText').textContent = category.selectedOptions[0].textContent;
        options.forEach(option => {
            const selected = option.dataset.value === category.value;
            option.classList.toggle('selected', selected);
            option.setAttribute('aria-selected', String(selected));
        });
        otherWrap.style.display = category.value === 'other' ? 'block' : 'none';
        if (category.value !== 'other') other.value = '';
        if (attempted) validate();
    }
    trigger.tabIndex = 0;
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-label', 'Choose concern category');
    dropdown.querySelector('.dropdown-options').setAttribute('role', 'listbox');
    trigger.addEventListener('click', () => toggleMenu(!dropdown.classList.contains('open')));
    trigger.addEventListener('keydown', event => {
        if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
            event.preventDefault(); toggleMenu(true); options[0].focus();
        }
    });
    options.forEach((option, index) => {
        option.tabIndex = -1;
        option.setAttribute('role', 'option');
        const choose = () => { category.value = option.dataset.value; syncCategory(); toggleMenu(false); trigger.focus(); };
        option.addEventListener('click', choose);
        option.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); options[(index + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length].focus();
            }
            if (event.key === 'Escape') { toggleMenu(false); trigger.focus(); }
        });
    });
    category.addEventListener('change', syncCategory);
    [other, subject, message].forEach(input => input.addEventListener('input', () => { if (attempted) validate(); }));
    const syncSubjectCount = () => { subjectCount.textContent = subject.value.length + '/150'; };
    subject.addEventListener('input', syncSubjectCount);
    syncSubjectCount();
    AccountPages.listen(document, 'click', event => { if (!dropdown.contains(event.target)) toggleMenu(false); });
    toggleMenu(false);
    syncCategory();

    function syncFiles() {
        const transfer = new DataTransfer();
        previews.replaceChildren();
        files.forEach((file, index) => {
            transfer.items.add(file);
            const item = document.createElement('div');
            item.className = 'preview-item';
            const image = document.createElement('img');
            image.className = 'preview-thumb';
            image.alt = file.name;
            const url = URL.createObjectURL(file);
            image.src = url;
            image.addEventListener('load', () => URL.revokeObjectURL(url), { once: true });
            image.addEventListener('error', () => URL.revokeObjectURL(url), { once: true });
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn-remove-preview';
            remove.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
            remove.setAttribute('aria-label', 'Remove ' + file.name);
            remove.addEventListener('click', () => { files.splice(index, 1); syncFiles(); });
            item.append(image, remove);
            previews.append(item);
        });
        imageInput.files = transfer.files;
    }
    function addFiles(incoming) {
        if (incoming.some(file => !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
            announce(uploadFeedback, 'Please choose JPG, PNG or WEBP images.', true);
        } else if (incoming.some(file => file.size > 5 * 1024 * 1024)) {
            announce(uploadFeedback, 'Each image must be 5MB or smaller.', true);
        } else if (files.length + incoming.length > 4) {
            announce(uploadFeedback, 'You can attach up to 4 images.', true);
        } else {
            files.push(...incoming);
            announce(uploadFeedback, '');
        }
        syncFiles();
    }
    imageInput.addEventListener('change', () => addFiles(Array.from(imageInput.files)));
    document.getElementById('concernBrowse').addEventListener('click', () => imageInput.click());
    let dragDepth = 0;
    uploadZone.addEventListener('dragenter', event => {
        event.preventDefault(); dragDepth++; uploadZone.classList.add('is-dragging');
    });
    uploadZone.addEventListener('dragover', event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
    uploadZone.addEventListener('dragleave', () => {
        dragDepth = Math.max(0, dragDepth - 1);
        if (!dragDepth) uploadZone.classList.remove('is-dragging');
    });
    uploadZone.addEventListener('drop', event => {
        event.preventDefault(); dragDepth = 0; uploadZone.classList.remove('is-dragging');
        addFiles(Array.from(event.dataTransfer.files));
    });

    async function post(url, body) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 30000);
        try {
            const response = await fetch(url, {
                method: 'POST', body, credentials: 'same-origin', signal: controller.signal,
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
            });
            if (!response.headers.get('Content-Type')?.includes('application/json')) {
                throw new Error(response.redirected ? 'Please sign in again in another tab, then retry. Your form is still here.' : 'We could not confirm the request. Please try again.');
            }
            return { response, data: await response.json() };
        } finally { clearTimeout(timeout); }
    }
    function requestError(error) {
        return error.name === 'AbortError' || error instanceof TypeError
            ? 'We could not confirm the request. Check your connection and try again. Your details are still here.'
            : error.message;
    }
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (submitting) return;
        attempted = true;
        const invalid = validate();
        if (invalid) { (invalid === 'category' ? trigger : document.getElementById(invalid)).focus(); return; }
        submitting = true;
        submit.disabled = true;
        submit.textContent = 'Submitting…';
        form.setAttribute('aria-busy', 'true');
        announce(feedback, 'Submitting your concern. Please wait.');
        try {
            const { response, data } = await post(form.action, new FormData(form));
            if (!scope.active) return;
            if (!response.ok || !data.success) throw new Error(data.message || data.error || 'Please review your details and try again.');
            announce(feedback, data.message);
            // Retain the submission key until the server confirms success, including after a lost response.
            if (window.AccountNavigation) window.AccountNavigation.navigate(data.redirect_url,{force:true});
            else window.location.assign(data.redirect_url);
        } catch (error) {
            announce(feedback, requestError(error), true);
            submitting = false;
            submit.disabled = false;
            submit.textContent = 'Try again';
            form.setAttribute('aria-busy', 'false');
        }
    });
    AccountPages.listen(window, 'pageshow', () => {
        submitting = false; submit.disabled = false; submit.textContent = 'Submit Concern';
        form.setAttribute('aria-busy', 'false');
    });

    function renderTicket(ticket) {
        document.getElementById('modalSubject').textContent = ticket.subject;
        document.getElementById('modalTicket').textContent = ticket.number;
        const status = document.getElementById('modalStatus');
        status.textContent = ticket.status_label;
        status.className = 'concern-detail-status status-' + ticket.status;
        document.getElementById('modalCategory').textContent = ticket.category;
        document.getElementById('modalCreated').textContent = ticket.created;
        document.getElementById('modalUpdated').textContent = ticket.updated;
        document.getElementById('modalMessage').textContent = ticket.message;
        const notes = document.getElementById('modalAdminNotes');
        notes.textContent = ticket.admin_notes || (ticket.status === 'cancelled' ? 'This concern was cancelled before review.' : 'Our team has not responded yet.');
        notes.classList.toggle('is-empty', !ticket.admin_notes);
        const images = document.getElementById('modalImages');
        images.replaceChildren();
        document.getElementById('modalImagesBlock').hidden = !ticket.images.length;
        ticket.images.forEach((url, index) => {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'concern-attachment';
            button.setAttribute('aria-label', 'View attachment ' + (index + 1));
            const image = document.createElement('img');
            image.src = url; image.alt = 'Concern attachment ' + (index + 1);
            button.append(image);
            button.addEventListener('click', () => {
                document.getElementById('concernLightboxImg').src = url;
                lightbox.showModal();
            });
            images.append(button);
        });
        document.getElementById('modalCancel').hidden = !ticket.can_cancel;
        document.getElementById('modalCancelHelp').textContent = ticket.can_cancel
            ? 'You can cancel this concern before our team starts handling it.'
            : ticket.status === 'cancelled' ? 'Your concern is cancelled and remains in your history.'
                : 'Cancellation is unavailable once our team has started handling a concern.';
    }
    function openCancel(id) {
        const ticket = tickets.get(String(id));
        if (!ticket || !ticket.can_cancel || cancelling) return;
        cancelTicket = ticket;
        cancelForm.action = ticket.cancel_url;
        document.getElementById('cancelConcernTicket').textContent = ticket.number + ' · ' + ticket.subject;
        announce(cancelFeedback, '');
        confirm.showModal();
    }
    function updateTicket(ticket) {
        tickets.set(String(ticket.id), ticket);
        const row = document.querySelector('[data-concern-id="' + ticket.id + '"]');
        if (row) {
            const status = row.querySelector('.concern-row-status');
            status.textContent = ticket.status_label;
            status.className = 'status concern-row-status status-' + ticket.status;
            if (!ticket.can_cancel) row.querySelector('[data-cancel-id]')?.remove();
        }
        if (activeTicket === String(ticket.id) && detail.open) renderTicket(ticket);
    }
    function openDetails(id) {
        const ticket=tickets.get(String(id));
        if (!ticket) return;
        activeTicket=String(id);
        renderTicket(ticket);
        if (!detail.open) detail.showModal();
    }
    AccountPages.listen(document, 'click', event => {
        const view = event.target.closest('[data-view-id]');
        const cancel = event.target.closest('[data-cancel-id]');
        const close = event.target.closest('[data-close-dialog]');
        if (view) {
            openDetails(view.dataset.viewId);
        }
        if (cancel) openCancel(cancel.dataset.cancelId);
        if (close && !(close.dataset.closeDialog === 'concernCancelModal' && cancelling)) {
            document.getElementById(close.dataset.closeDialog).close();
        }
    });
    document.getElementById('modalCancel').addEventListener('click', () => openCancel(activeTicket));
    cancelForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (cancelling || !cancelTicket) return;
        cancelling = true; cancelSubmit.disabled = true; cancelSubmit.textContent = 'Cancelling…';
        announce(cancelFeedback, '');
        try {
            const { response, data } = await post(cancelForm.action, new FormData(cancelForm));
            if (!scope.active) return;
            if (data.ticket) updateTicket(data.ticket);
            if (!response.ok || !data.success) throw new Error(data.message || 'We could not cancel this concern. Please try again.');
            confirm.close();
            announce(historyFeedback, data.message);
            if (detail.open) detail.querySelector('[data-close-dialog]').focus();
            else document.querySelector('[data-view-id="' + cancelTicket.id + '"]')?.focus();
        } catch (error) { announce(cancelFeedback, requestError(error), true); }
        finally { cancelling = false; cancelSubmit.disabled = false; cancelSubmit.textContent = 'Cancel concern'; }
    });
    [detail, confirm, lightbox].forEach(dialog => {
        dialog.addEventListener('click', event => {
            if (dialog === confirm && cancelling) return;
            if (event.target !== dialog) return;
            const bounds = dialog.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
        });
    });
    confirm.addEventListener('cancel', event => { if (cancelling) event.preventDefault(); });
    lightbox.addEventListener('close', () => document.getElementById('concernLightboxImg').removeAttribute('src'));
    scope.ready(()=>{
        const url=new URL(location.href), id=url.searchParams.get('concern_id');
        if (!id) return;
        openDetails(id);
        url.searchParams.delete('concern_id'); url.searchParams.delete('from_notif');
        // The server selected the correct history page, including older tickets.
        const page=scope.root.querySelector('[data-concerns-page]')?.dataset.concernsPage;
        if (page) url.searchParams.set('page',page);
        history.replaceState(history.state,'',url);
    });
});
