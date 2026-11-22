/* Account-scoped saved-design selection. The server validates every booking. */
(() => {
    'use strict';
    window.DesignBookingSelection = {
        clearCompleted(account, completed) {
            if (!completed.length) return;
            try {
                const storageKey = 'balloorina:design-booking:' + account;
                const stored = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
                const expected = completed.map(String).sort();
                if (Array.isArray(stored) && JSON.stringify(stored.map(String).sort()) === JSON.stringify(expected)) sessionStorage.removeItem(storageKey);
            } catch (_) { /* A completed booking must not fail because storage is unavailable. */ }
        }
    };
    const root = document.querySelector('.design-library-workspace[data-selection-account]');
    if (!root) return;
    document.body.classList.add('has-design-booking-selection');
    const get = id => document.getElementById(id);
    const key = 'balloorina:design-booking:' + root.dataset.selectionAccount;
    const kinds = {package: 'Package', entrance: 'Entrance Arch', stand: 'Welcome Stand'};
    const cents = value => Math.round(Number(value || 0) * 100);
    const money = value => '₱' + (value / 100).toLocaleString('en-PH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    let catalog = new Map(JSON.parse(get('designBookingCatalog').textContent).map(d => [String(d.id), d]));
    let ids = [];
    try { const stored = JSON.parse(sessionStorage.getItem(key) || '[]'); if (Array.isArray(stored)) ids = [...new Set(stored.map(String))].slice(0, 3); } catch (_) { /* Storage is optional. */ }
    const entries = () => ids.map(id => catalog.get(id)).filter(Boolean);
    const selected = kind => entries().find(d => d.kind === kind);
    const hasBase = () => !!(selected('package') || (selected('entrance') && cents(selected('entrance').solo_price) > 0));
    const amount = d => cents(d.kind === 'entrance' && !selected('package') ? d.solo_price : d.price);
    const valid = () => !root.dataset.selectionRefreshing && ids.length > 0 && ids.length === entries().length && hasBase()
        && entries().every(d => d.ready && amount(d) >= 0 && Object.hasOwn(kinds, d.kind))
        && new Set(entries().map(d => d.kind)).size === ids.length;
    const element = (tag, className, text) => { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; };
    function remember() { try { if (ids.length) sessionStorage.setItem(key, JSON.stringify(ids)); else sessionStorage.removeItem(key); } catch (_) { /* Continue in memory. */ } }

    const iconPaths = {
        package: 'm12 3 9 5-9 5-9-5 9-5Zm9 5v9l-9 5-9-5V8m9 5v9M7.5 5.5l9 5',
        entrance: 'M3 21V10a9 9 0 0 1 18 0v11M7 21V10a5 5 0 0 1 10 0v11M1 21h8m6 0h8',
        stand: 'M7 2h10a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm5 15v5m-5 0h10M9 7h6m-6 4h4',
        close: 'm6 6 12 12M18 6 6 18'
    };
    function icon(kind) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(svg.namespaceURI, 'path');
        path.setAttribute('d', iconPaths[kind]); svg.append(path); return svg;
    }
    function render(message = '') {
        const total = entries().reduce((sum, d) => sum + amount(d), 0);
        root.querySelectorAll('[data-design-id]').forEach(card => {
            const d = catalog.get(card.dataset.designId), button = card.querySelector('[data-select-design]');
            if (!d || !button) return;
            const active = ids.includes(String(d.id));
            const duplicate = selected(d.kind) && !active;
            const needsBase = d.kind === 'stand' && !hasBase();
            const needsPackage = d.kind === 'entrance' && !selected('package') && cents(d.solo_price) <= 0;
            card.classList.toggle('is-booking-selected', active);
            button.setAttribute('aria-pressed', String(active));
            button.disabled = !active && (!d.ready || !!duplicate || needsBase || needsPackage);
            const marker = card.querySelector('[data-check-design]');
            if (marker) {marker.disabled = button.disabled; marker.setAttribute('aria-checked', String(active));}
            button.textContent = active ? 'Selected' : duplicate ? (d.kind === 'package' ? 'Package' : d.kind === 'entrance' ? 'Entrance' : 'Stand') + ' already selected' : 'Select for Booking';
            button.setAttribute('aria-label', active ? 'Remove ' + d.name + ' from booking' : 'Select ' + d.name + ' for booking');
            card.querySelector('[data-design-price]').textContent = money(amount(d));
            card.querySelector('[data-design-rate]').textContent = d.kind === 'entrance' ? selected('package') ? 'with package' : 'solo rate' : d.kind === 'stand' ? '' : 'package price';
            get('designSelectionHint' + d.id).textContent = needsBase ? 'Choose a package or entrance arch first.' : needsPackage ? 'Choose a package; this entrance is not available on its own.' : duplicate ? 'Remove your selected ' + d.kind + ' to choose this design.' : active ? 'Included in your booking selection.' : d.kind === 'stand' ? 'Available with your package or entrance.' : 'Select one design in this category.';
        });
        get('designBookingSlots').replaceChildren();
        Object.entries(kinds).forEach(([kind, label]) => {
            const d = selected(kind), slot = element('div', 'design-booking-slot' + (!d ? ' is-empty' : ''));
            const art = element('div', 'design-booking-art');
            if (d?.thumbnail) { const img = element('img'); img.src = d.thumbnail; img.alt = d.name; art.append(img); }
            else art.append(icon(kind));
            slot.append(art);
            const copy = element('div', 'design-booking-slot-copy');
            copy.append(element('span', 'design-booking-kind', label));
            if (d) {
                copy.append(element('strong', '', d.offer_name), element('span', 'design-booking-name', d.name), element('span', 'design-booking-unit', money(amount(d))));
                if (kind === 'entrance') copy.append(element('span', 'design-booking-rate', selected('package') ? 'With package rate' : 'Solo rate'));
                const remove = element('button', 'design-booking-remove'); remove.append(icon('close')); remove.type = 'button'; remove.dataset.removeDesign = String(d.id); remove.setAttribute('aria-label', 'Remove ' + d.offer_name); slot.append(remove);
            } else copy.append(element('span', 'design-booking-empty-copy', kind === 'stand' && !hasBase() ? 'Choose a package or entrance first' : kind === 'package' ? 'Choose a package design' : 'Optional · add a ' + (kind === 'entrance' ? 'entrance' : 'welcome stand')));
            slot.append(copy); get('designBookingSlots').append(slot);
        });
        const missing = ids.length !== entries().length;
        const invalid = missing || entries().some(d => !d.ready || !Number.isFinite(amount(d)) || amount(d) < 0 || (d.kind === 'entrance' && !selected('package') && amount(d) === 0));
        const entrance = selected('entrance');
        const savings = entrance && selected('package') ? cents(entrance.solo_price) - cents(entrance.price) : 0;
        const notice = get('designBookingNotice');
        notice.classList.toggle('has-savings', savings > 0 && !invalid);
        notice.textContent = invalid ? 'A selected design is no longer available or complete. Remove it or clear the selection before continuing.' : (savings > 0 ? money(savings) + ' less on your entrance. With-package rate applied automatically.' : entrance ? 'Your entrance uses its ' + (selected('package') ? 'with-package' : 'solo') + ' rate.' : hasBase() ? 'Entrance arches and welcome stands are optional.' : 'Start with a package or a solo entrance arch. A stand needs either one.');
        get('designBookingCount').textContent = ids.length + '/3';
        get('designBookingTotal').textContent = money(total);
        get('designBookingMobileTotal').textContent = money(total);
        get('designBookingMobileCount').textContent = ids.length ? ids.length + (ids.length === 1 ? ' design selected' : ' designs selected') : 'Choose a package or entrance';
        get('designBookingContinue').disabled = !valid();
        get('designBookingNext').textContent = valid() ? 'Next: event details' : 'Choose a valid package or entrance to continue';
        get('designBookingClear').disabled = !ids.length;
        get('designBookingIds').replaceChildren();
        ids.forEach(id => {const input = element('input'); input.type = 'hidden'; input.name = 'design_id'; input.value = id; get('designBookingIds').append(input);});
        const feedback = get('designSelectionFeedback');
        feedback.hidden = true; feedback.textContent = '';
        if (message) window.AppToast.fire({icon:'info', title:message, timer:3500});
        remember();
    }

    function remove(id) {
        const d = catalog.get(id);
        ids = ids.filter(value => value !== id);
        let message = (d?.offer_name || 'Design') + ' removed from your booking.';
        if (!hasBase() && selected('stand')) {ids = ids.filter(value => catalog.get(value)?.kind !== 'stand'); message += ' Welcome stand also removed: choose a package or entrance first.';}
        else if (d?.kind === 'package' && selected('entrance')) message += ' Your entrance now uses its solo rate.';
        render(message);
    }
    root.addEventListener('click', event => {
        const marker = event.target.closest('[data-check-design]');
        if (marker && !marker.disabled) {
            root.querySelector('[data-select-design="' + marker.dataset.checkDesign + '"]')?.click();
            return;
        }
        const button = event.target.closest('[data-select-design]');
        if (button && !button.disabled) {
            const id = button.dataset.selectDesign, d = catalog.get(id);
            if (ids.includes(id)) remove(id);
            else if (d?.ready && !selected(d.kind) && (d.kind !== 'stand' || hasBase())) { ids.push(id); render(d.offer_name + ' added to your booking.'); }
        }
        const removeButton = event.target.closest('[data-remove-design]');
        if (removeButton) {remove(removeButton.dataset.removeDesign); (ids.length ? get('designBookingClear') : get('designBookingSummaryTitle')).focus();}
    });
    root.addEventListener('design-library-updated', event => {delete root.dataset.selectionRefreshing; catalog = new Map(event.detail.map(d => [String(d.id), d])); render();});
    root.addEventListener('design-selection-deleted', event => {
        const id = String(event.detail.id);
        ids = ids.filter(value => value !== id);
        catalog.delete(id);
        if (!hasBase()) ids = ids.filter(value => catalog.get(value)?.kind !== 'stand');
        render();
    });
    root.addEventListener('design-selection-renamed', event => {const design = catalog.get(String(event.detail.id)); if (design) {design.name = event.detail.name; render();}});
    get('designBookingClear').addEventListener('click', () => {ids = []; render('Selection cleared. Your saved designs are kept.');});
    get('designBookingForm').addEventListener('submit', event => {if (!valid()) {event.preventDefault();render('Choose a complete package or solo entrance before continuing.');}});
    const dialog = get('designBookingDialog'), summary = get('designBookingSummary');
    get('designBookingOpen').addEventListener('click', () => {dialog.append(summary); dialog.showModal(); document.documentElement.classList.add('design-booking-sheet-open'); get('designBookingClose').focus();});
    get('designBookingClose').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {if (event.target === dialog) {const r = dialog.getBoundingClientRect(); if (event.clientY < r.top || event.clientX < r.left || event.clientX > r.right) dialog.close();}});
    dialog.addEventListener('close', () => {get('designBookingSummaryHome').append(summary); document.documentElement.classList.remove('design-booking-sheet-open'); get('designBookingOpen').focus({preventScroll:true});});
    matchMedia('(min-width: 981px)').addEventListener('change', event => {if (event.matches && dialog.open) dialog.close();});
    window.addEventListener('pageshow', event => {
        try {const stored = JSON.parse(sessionStorage.getItem(key) || '[]'); if (Array.isArray(stored)) ids = stored.map(String).slice(0,3);} catch (_) {}
        if (event.persisted) {root.dataset.selectionRefreshing = '1'; root.dispatchEvent(new CustomEvent('design-selection-refresh'));}
        render();
    });
    render();
})();
