/* Customer-only booking dialogs. HTML comes from the owner-checked modal endpoint. */
AccountPages.enhance('customer_profile', 'customer_booking_details.js', function(scope) {
    'use strict';
    scope.capture(['CustomerBookingModals', 'closeBookingModal', 'openBookingModal', 'openEventDesignModal']);
    let active = null;
    let request = null;
    let sequence = 0;
    let closing = false;
    let suppressed = [];
    const legacyClosers = {editBookingModal: 'closeEditModal', deleteBookingModal: 'closeDeleteModal', reviewModal: 'closeReviewModal'};

    function cleanLink() {
        const url = new URL(window.location.href);
        ['booking_id', 'modal', 'from_notif', 'open_edit'].forEach(key => url.searchParams.delete(key));
        if (url.hash === '#event-design') url.hash = '';
        window.history.replaceState({}, '', url);
    }
    function restoreBackground() {
        suppressed.forEach(item => { item.element.inert = item.inert; });
        suppressed = [];
    }
    function restrictBackground(root) {
        restoreBackground();
        let branch = root;
        while (branch && branch !== document.body) {
            const parent = branch.parentElement;
            if (!parent) break;
            Array.from(parent.children).forEach(element => {
                if (element !== branch && !['SCRIPT', 'STYLE', 'LINK'].includes(element.tagName)) {
                    suppressed.push({element, inert: element.inert});
                    element.inert = true;
                }
            });
            branch = parent;
        }
    }
    function disposeMap(root) {
        const context = root.querySelector('#booking_modal_map')?.__bookingMapCtx;
        if (context?.destroy) context.destroy();
        else if (context?.map) context.map.remove();
    }
    function finish(restoreFocus) {
        if (!active) return;
        const previous = active;
        active = null;
        sequence += 1;
        if (request) request.abort();
        request = null;
        disposeMap(previous.root);
        previous.root.classList.remove('show');
        previous.root.removeAttribute('aria-busy');
        const content = previous.root.querySelector('.customer-booking-content');
        if (content) content.replaceChildren();
        document.body.classList.remove('customer-booking-scroll-locked');
        restoreBackground();
        if (restoreFocus) {
            cleanLink();
            if (previous.trigger?.isConnected && previous.trigger.getClientRects().length) previous.trigger.focus();
            else document.querySelector('.bookings-table a, .bookings-table button, #searchFilterInput')?.focus();
        }
    }
    function close(restoreFocus = true) {
        if (!active || closing) return;
        closing = true;
        const callback = legacyClosers[active.root.id];
        try { if (callback && typeof window[callback] === 'function') window[callback](); }
        finally { finish(restoreFocus); closing = false; }
    }
    function activate(root) {
        const trigger = active?.trigger || document.activeElement;
        close(false);
        active = {root, trigger};
        root.classList.add('show');
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        if (!root.hasAttribute('aria-labelledby')) {
            const heading = root.querySelector('h2');
            if (heading) { heading.id ||= root.id + 'Title'; root.setAttribute('aria-labelledby', heading.id); }
        }
        document.body.classList.add('customer-booking-scroll-locked');
        restrictBackground(root);
        const card = root.querySelector('.modal-card, .booking-modal-box');
        if (card) { card.tabIndex = -1; card.focus(); }
        return active;
    }
    function setMessage(content, message, retry) {
        content.replaceChildren();
        const box = document.createElement('div');
        box.className = 'booking-dialog-message';
        if (!retry) {
            const spinner = document.createElement('span');
            spinner.className = 'booking-loading-ring'; spinner.setAttribute('aria-hidden', 'true'); box.append(spinner);
        }
        const text = document.createElement('p'); text.textContent = message; box.append(text);
        if (retry) {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'booking-secondary-button';
            button.textContent = 'Retry'; button.addEventListener('click', retry); box.append(button);
        }
        content.append(box);
    }
    async function open(id, section) {
        id = String(id);
        if (!/^\d+$/.test(id)) return;
        const mode = section === 'design' || section === 'event-design' ? 'design' : 'details';
        const root = document.getElementById(mode === 'design' ? 'eventDesignModal' : 'bookingModal');
        const session = activate(root);
        const content = root.querySelector('.customer-booking-content');
        root.querySelector('.booking-dialog-id').textContent = 'Booking #' + id;
        const url = new URL(window.location.href);
        url.searchParams.set('booking_id', id); url.searchParams.set('modal', mode);
        window.history.replaceState({}, '', url);
        root.setAttribute('aria-busy', 'true');
        setMessage(content, mode === 'design' ? 'Loading your event design…' : 'Loading booking details…');
        const token = ++sequence;
        const controller = new AbortController();
        request = controller;
        const timeout = setTimeout(() => controller.abort(), 20000);
        try {
            const endpoint = document.getElementById('bookingModal').dataset.contentUrl.replace('/0/', '/' + id + '/');
            const response = await fetch(endpoint + '?section=' + mode, {signal: controller.signal, headers: {'X-Requested-With': 'XMLHttpRequest'}, cache: 'no-store'});
            if (response.redirected) throw new Error('Your session may have expired. Please sign in again.');
            if (!response.ok) throw new Error(response.status === 403 || response.status === 404 ? 'This booking is unavailable or you do not have access to it.' : 'Could not load this booking. Please try again.');
            const html = await response.text();
            if (active !== session || token !== sequence) return;
            const fragment = document.createElement('template'); fragment.innerHTML = html;
            // Reuse the same edit data partial for off-page details actions; never duplicate IDs.
            const editData = fragment.content.querySelector('[id^="booking-data-"]');
            if (editData) {
                document.getElementById(editData.id)?.remove();
                let stash = document.getElementById('booking-modal-edit-cache');
                if (!stash) { stash = document.createElement('div'); stash.id = 'booking-modal-edit-cache'; stash.hidden = true; document.body.append(stash); }
                stash.append(editData);
            }
            content.replaceChildren(fragment.content);
            content.scrollTop = 0;
            const map = content.querySelector('#booking_modal_map');
            if (map && window.BookingLocationMap) window.BookingLocationMap.initReadOnly({mapId: map.id, lat: map.dataset.lat, lng: map.dataset.lng, expandable: false, label: content.querySelector('#modalLocation')?.textContent || 'Event venue'});
            content.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
                const note = document.createElement('span'); note.className = 'booking-muted'; note.textContent = 'Image unavailable'; img.replaceWith(note);
            }, {once: true}));
        } catch (error) {
            if (active !== session || token !== sequence) return;
            const message = error.name === 'AbortError' ? 'Loading took too long. Please try again.' : error.message;
            setMessage(content, message, () => open(id, mode));
        } finally {
            clearTimeout(timeout);
            if (active === session) root.removeAttribute('aria-busy');
        }
    }
    AccountPages.listen(document, 'click', event => {
        const button = event.target.closest('[data-booking-close], [data-view-design], [data-edit-booking], [data-cancel-booking]');
        if (!button) {
            if (active && event.target === active.root && active.root.classList.contains('customer-booking-modal')) close();
            return;
        }
        if (button.hasAttribute('data-booking-close')) close();
        else if (button.dataset.viewDesign) open(button.dataset.viewDesign, 'design');
        else if (button.dataset.editBooking) window.openEditModal(button.dataset.editBooking);
        else if (button.dataset.cancelBooking) window.openDeleteModal(button.dataset.cancelBooking);
    });
    AccountPages.listen(document, 'keydown', event => {
        if (event.key === 'Escape') event.bookingPickerWasOpen = Array.from(document.querySelectorAll('.booking-picker-pop')).some(pop => pop.getClientRects().length);
    }, true);
    AccountPages.listen(document, 'keydown', event => {
        if (!active || document.querySelector('.client-feedback-dialog[open]')) return;
        // Nested date/time picker popovers handle their own Escape/Tab first.
        if (event.bookingPickerWasOpen) return;
        if (event.key === 'Escape') { event.preventDefault(); close(); return; }
        if (event.key !== 'Tab') return;
        const focusable = Array.from(active.root.querySelectorAll('a[href], button, input, select, textarea, [tabindex="0"]')).filter(el => !el.disabled && el.getClientRects().length && !el.closest('[hidden]'));
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement))) { event.preventDefault(); first.focus(); }
    });
    scope.ready(() => {
        const params = new URLSearchParams(window.location.search);
        if (params.has('open_edit')) return; // Existing edit initializer uses owner-checked pre-rendered data.
        const id = params.get('booking_id');
        if (id) open(id, params.get('modal') === 'design' || window.location.hash === '#event-design' ? 'design' : 'details');
    });
    window.CustomerBookingModals = {
        activateExisting(id) { const root = document.getElementById(id); if (root) activate(root); },
        closed(id) { if (!closing && active?.root.id === id) finish(true); },
        close
    };
    window.openBookingModal = (id, section) => open(id, section);
    window.openEventDesignModal = id => open(id, 'design');
    window.closeBookingModal = () => close();

    scope.cleanup(() => { request?.abort(); close(false); });

}, -20);
