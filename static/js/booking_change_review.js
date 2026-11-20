/* Draft review uses the same server proposal and payment rules as the final quote. */
AccountPages.enhance('customer_profile', 'booking_change_review.js', function(scope) {
    'use strict';
    scope.capture(['BookingChangeReview']);
    const form = document.getElementById('editBookingForm');
    const step = document.getElementById('edit-step-4');
    const submit = form.querySelector('button[type="submit"]');
    const status = document.getElementById('changeReviewStatus');
    const retry = document.getElementById('changeReviewRetry');
    const noChanges = document.getElementById('changeReviewNoChanges');
    const money = value => new Intl.NumberFormat('en-PH', {style: 'currency', currency: 'PHP'}).format(Number(value));
    let original = null, result = null, request = null, generation = 0, pendingMode = false;
    let objectUrls = [];
    const active = () => form.dataset.changeMode === '1' && original;
    const value = id => document.getElementById(id)?.value?.trim() || '';
    const clean = value => String(value ?? '').trim();
    const pin = (lat, lng) => lat === null || lat === '' || lng === null || lng === ''
        ? '' : `${Number(lat).toFixed(6)},${Number(lng).toFixed(6)}`;
    const escape = value => { const el = document.createElement('span'); el.textContent = value; return el.innerHTML; };
    const time = value => {
        if (!value) return '';
        const [hour, minute] = value.split(':').map(Number);
        return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`;
    };
    function releaseUrls() { objectUrls.forEach(url => URL.revokeObjectURL(url)); objectUrls = []; }
    function badge(label) { return `<span class="change-review-badge">${label}</span>`; }
    function row(label, before, after, equal = clean(before) === clean(after)) {
        if (!clean(before) && !clean(after)) return '';
        const change = !equal ? (!clean(before) ? 'Added' : !clean(after) ? 'Removed' : 'Changed') : '';
        const icons = {'Package / Items': 'fa-square-check', 'Event Type': 'fa-clipboard', 'Event Date': 'fa-calendar-days',
            'Event Duration': 'fa-clock', 'Location': 'fa-map', 'Landmark': 'fa-map-pin', 'Map Pin': 'fa-map-pin',
            'Theme': 'fa-wand-magic-sparkles', 'Color Palette': 'fa-palette', 'Motto': 'fa-font', 'Design Notes': 'fa-comment'};
        return `<div class="summary-row">
            <div class="row-info change-review-field-label"><span class="row-label"><i class="far ${icons[label]}"></i> ${escape(label)}</span>${change ? badge(change) : ''}</div>
            <span class="row-value">${escape(after || 'None')}${change && clean(before)
                ? `<small class="change-review-before">Previously: ${escape(before)}</small>` : ''}</span></div>`;
    }
    function details() {
        const before = original.fields, after = result.proposed;
        const duration = fields => `${time(fields.event_time)} – ${time(fields.event_end_time)}`
            + (fields.event_end_date > fields.event_date ? ` (${fields.event_end_date})` : '')
            + ` · ${Math.floor(fields.duration_minutes / 60)}h ${fields.duration_minutes % 60}m`;
        const pairs = [['Package / Items', 'package_type'], ['Event Type', 'event_type'], ['Event Date', 'event_date']];
        let html = pairs.map(([label, key]) => row(label, before[key], after[key])).join('');
        html += row('Event Duration', duration(before), duration(after));
        html += row('Location', before.event_location, after.event_location);
        html += row('Landmark', before.venue_landmark, after.venue_landmark);
        html += row('Theme', before.design_theme, after.design_theme);
        const palette = value => clean(value).split(',').map(color => color.trim().toLowerCase()).filter(Boolean).sort().join(',');
        html += row('Color Palette', before.color_palette, after.color_palette, palette(before.color_palette) === palette(after.color_palette));
        html += row('Motto', before.motto_text, after.motto_text);
        html += row('Design Notes', before.special_requests, after.special_requests);
        const removals = new Set(new FormData(form).getAll('remove_images[]'));
        releaseUrls();
        const images = original.images.map(image => ({src: image.url, label: removals.has(image.id) ? 'Removed' : 'Retained'}));
        for (const design of original.design_images || []) images.push({src: design.url, label: 'Custom Design'});
        for (const file of Array.from(window.editAccumulatedFiles?.files || [])) {
            const src = URL.createObjectURL(file); objectUrls.push(src); images.push({src, label: 'Added'});
        }
        for (const state of ['Retained', 'Custom Design', 'Added', 'Removed']) {
            const group = images.filter(image => image.label === state);
            if (!group.length) continue;
            html += `<div class="summary-row"><div class="row-info change-review-field-label"><span class="row-label"><i class="far fa-images"></i> Reference Pictures</span>
                ${state === 'Retained' ? '' : badge(state + (group.length > 1 ? ` (${group.length})` : ''))}</div>
                <span class="row-value"><span class="booking-summary-image-list">${group.map((image, index) =>
                    `<img class="booking-summary-thumb" src="${escape(image.src)}" alt="${state} reference picture ${index + 1}">`).join('')}</span></span></div>`;
        }
        document.getElementById('edit-booking-details-list').innerHTML = html;
    }
    const amountChanged = (before, after) => before !== null && after !== null
        && Math.round(Number(before)*100) !== Math.round(Number(after)*100);
    function feeLabel(rowId, label, previous, current) {
        const row = document.getElementById(rowId);
        row.querySelector('.row-label').innerHTML = escape(label) + (amountChanged(previous, current) ? ' ' + badge('Changed') : '');
        row.querySelector('.change-review-fee-before')?.remove();
        if (amountChanged(previous, current)) row.querySelector('.row-label').insertAdjacentHTML('afterend',
            `<small class="change-review-before change-review-fee-before">Previously: ${money(previous)}</small>`);
    }
    function render() {
        if ((!active() && !pendingMode) || !result) return;
        step.classList.remove('change-review-unavailable');
        details();
        window.BookingFormUI.updateReviewMap({
            rowId: 'editBookingReviewMapRow', mapId: 'edit_booking_review_map',
            lat: result.proposed.event_lat, lng: result.proposed.event_lng, label: result.proposed.event_location,
            change: pin(original.fields.event_lat, original.fields.event_lng) === pin(result.proposed.event_lat, result.proposed.event_lng)
                ? '' : pin(original.fields.event_lat, original.fields.event_lng) ? 'Changed' : 'Added'
        });
        const oldItems = new Map(original.items.map(item => [item.label, item]));
        const selectedLabels = new Set(result.items.map(item => item.label));
        const itemRole = item => /\(Add-on\)$/i.test(item.label) ? 'addon'
            : /\(Additional\)$/i.test(item.label) ? 'additional' : 'base';
        document.getElementById('edit-booking-item-list').innerHTML = result.items.map(item => {
            const saved = oldItems.get(item.label);
            const changed = !saved || amountChanged(saved.amount, item.amount);
            // Replaced items compare within their slot; an added extra has no predecessor.
            const previous = saved ? [saved] : original.items.filter(old => itemRole(old) === itemRole(item) && !selectedLabels.has(old.label));
            const previousText = previous.length ? previous.map(old => `${old.label} — ${old.amount === null ? 'price unavailable' : money(old.amount)}`).join(' + ') : 'None';
            return `<div class="summary-row"><div class="row-info"><span class="row-label">${escape(item.label)}${changed ? ' ' + badge(previous.length ? 'Changed' : 'Added') : ''}</span>
                ${changed && previous.length ? `<small class="change-review-before">Previously: ${escape(previousText)}</small>` : ''}</div>
                <span class="row-value">${item.amount === null ? '—' : money(item.amount)}</span></div>`;
        }).join('')
            + (result.items.some(item => item.amount === null) ? '<p class="row-note">Saved item price breakdown unavailable.</p>' : '');
        feeLabel('editServiceChargeRow', 'Service & Logistics Fee', original.logistics, result.logistics);
        feeLabel('editOvertimeRow', 'Overtime', original.overtime, result.overtime);
        document.getElementById('editServiceChargeRow').style.display = Number(result.logistics) > 0 || amountChanged(original.logistics, result.logistics) ? 'flex' : 'none';
        document.getElementById('edit_service_charge_display').textContent = money(result.logistics);
        document.getElementById('edit_service_charge_note_text').textContent = result.logistics_note;
        document.getElementById('editOvertimeRow').style.display = 'flex';
        document.getElementById('edit_overtime_display').textContent = money(result.overtime);
        document.getElementById('edit_overtime_row_note').textContent = result.overtime_note;
        document.getElementById('edit_price_display').textContent = money(result.proposed.total_price);
        document.getElementById('edit_total_price_input').value = result.proposed.total_price;
        document.getElementById('editChangeCurrentTotal').textContent = money(original.fields.total_price);
        const delta = Math.round(Number(result.proposed.total_price)*100) - Math.round(Number(original.fields.total_price)*100);
        document.getElementById('editChangeTotals').hidden = delta === 0;
        document.getElementById('editChangePriceDifference').hidden = delta === 0;
        document.getElementById('editChangePriceDifference').textContent = `Estimated ${delta > 0 ? 'increase' : 'decrease'}: ${money(Math.abs(delta)/100)}`;
        if (pendingMode) {
            document.getElementById('editChangePaymentSummary').hidden = true;
            status.textContent = '';
            submit.disabled = false;
            return;
        }
        const payment = result.payment;
        for (const el of step.querySelectorAll('[data-review-money]')) el.textContent = money(payment[el.dataset.reviewMoney]);
        let paymentNote;
        if (result.payment_review_required) paymentNote = 'Team review required: existing credits exceed your current total.';
        else if (Number(payment.verified_paid) === 0) paymentNote = 'Full amount unpaid; existing payment terms still apply.';
        else if (Number(payment.additional) > 0) paymentNote = Number(payment.balance_after_additional) > 0
            ? `Includes ${money(payment.additional)} for this change and ${money(payment.balance_after_additional)} booking balance. Pay the change amount after accepting the final quote.`
            : `The ${money(payment.additional)} change payment follows final quote acceptance.`;
        else paymentNote = Number(payment.remaining) > 0 ? 'No additional charge for changes; your booking balance remains.' : 'No additional payment estimated.';
        document.getElementById('editChangePaymentNote').textContent = paymentNote;
        document.getElementById('editChangeExcess').hidden = Number(payment.excess) === 0;
        document.getElementById('editChangePaymentSummary').hidden = false;
        status.textContent = '';
        submit.disabled = !result.has_changes;
        noChanges.hidden = result.has_changes;
        if (!result.has_changes) window.AppToast.fire({icon:'info',
            text:'No changes yet. Go back and update at least one detail to submit your request.', timer:5500});
    }
    function invalidate() {
        noChanges.hidden = true;
        if (pendingMode) { result = null; releaseUrls(); return; }
        if (!active()) return;
        generation++;
        request?.abort(); request = null; result = null;
        submit.disabled = true;
        step.classList.add('change-review-unavailable');
        releaseUrls();
    }
    function reset() {
        generation++; request?.abort(); request = null; result = null; original = null; pendingMode = false; releaseUrls();
        step.classList.remove('change-review-unavailable');
        status.textContent = ''; retry.hidden = true; noChanges.hidden = true;
        submit.disabled = false;
        for (const id of ['editChangePaymentSummary', 'editChangeTotals', 'editChangePriceDifference']) document.getElementById(id).hidden = true;
        for (const [id, label] of [['editServiceChargeRow', 'Service & Logistics Fee'], ['editOvertimeRow', 'Overtime']]) {
            document.querySelector('#' + id + ' .row-label').textContent = label;
            document.querySelector('#' + id + ' .change-review-fee-before')?.remove();
        }
        document.getElementById('editOvertimeRow').style.display = 'flex';
        document.getElementById('editReviewTotalLabel').textContent = 'Total Price';
    }
    function configure(data, directEdit = false) {
        reset(); original = data; pendingMode = Boolean(data && directEdit);
        const input = document.getElementById('edit_original_version');
        input.disabled = !data || pendingMode; input.value = data?.version || '';
        if (data && !pendingMode) {
            submit.disabled = true;
        }
    }
    async function loadPending(url, isCurrent = () => true) {
        const endpoint = new URL(url, window.location.href);
        endpoint.searchParams.set('review_original', '1');
        try {
            const response = await fetch(endpoint, {credentials:'same-origin', cache:'no-store', signal:scope.controller.signal,
                headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
            const payload = await response.json();
            if (!isCurrent()) return null;
            if (!response.ok || !payload.success) throw AppErrors.create(AppErrors.text(payload.message, 'Unable to load your saved booking. Please try again.'));
            return scope.active ? payload : null;
        } catch (error) {
            if (scope.active && isCurrent()) window.AppToast.fire({icon:'error', title:AppErrors.message(error, 'Unable to load your saved booking. Please try again.')});
            return null;
        }
    }
    function pendingResult() {
        const data = new FormData(form);
        const fields = {...original.fields};
        for (const name of ['event_type','event_date','event_location','event_lat','event_lng','venue_landmark',
            'package_type','design_theme','color_palette','motto_text','special_requests']) fields[name] = clean(data.get(name));
        fields.event_time = value('edit_start_time'); fields.event_end_time = value('edit_end_time');
        const endDate = new Date(fields.event_date + 'T00:00:00Z');
        if (fields.event_end_time <= fields.event_time) endDate.setUTCDate(endDate.getUTCDate()+1);
        fields.event_end_date = endDate.toISOString().slice(0,10);
        fields.duration_minutes = window.getEditOvertimeInfo().duration;
        fields.total_price = value('edit_total_price_input');
        const items = Array.from(document.querySelectorAll('#edit-booking-item-list .summary-row')).map(row => ({
            label:row.querySelector('.row-label').textContent.trim(),
            amount:row.querySelector('.row-value').textContent.replace(/[^0-9.-]/g,'')
        }));
        return {proposed:fields, items:items.length ? items : original.design_images?.length ? original.items : [], logistics:window.getEditLogisticsQuote().total,
            overtime:window.getEditOvertimeInfo().fee,
            logistics_note:document.getElementById('edit_service_charge_note_text').textContent,
            overtime_note:document.getElementById('edit_overtime_row_note').textContent};
    }
    async function review() {
        if (pendingMode) { result = pendingResult(); render(); return true; }
        if (!active()) return true;
        invalidate(); const token = generation;
        status.textContent = 'Checking your changes and current payments…'; retry.hidden = true;
        request = new AbortController();
        const controller = request;
        const timeout = setTimeout(() => controller.abort(), 20000);
        const data = new FormData(form);
        // Previews need only the upload count; files are uploaded with the actual request.
        for (const [name, entry] of [...data]) if (entry instanceof File) data.delete(name);
        data.set('new_image_count', String(window.editAccumulatedFiles?.files.length || 0));
        data.set('review_only', '1');
        try {
            const response = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin', cache: 'no-store',
                signal: controller.signal, headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}});
            const payload = await response.json();
            if (!scope.active || token !== generation) return false;
            if (response.redirected || !response.ok || !payload.success) throw AppErrors.create(AppErrors.text(payload.message, 'Unable to check your changes. Please try again.'));
            result = payload;
            form.dataset.verifiedPaidCents = String(Math.round(Number(result.payment.verified_paid)*100));
            if (!await window.confirmBookingChangePrice(Number(result.proposed.total_price))) {
                if (scope.active && token === generation) {
                    result = null;
                    status.textContent = 'Please go back and review your selection before continuing.';
                    retry.hidden = false;
                }
                return false;
            }
            if (!scope.active || token !== generation) return false;
            render();
            return true;
        } catch (error) {
            if (scope.active && token === generation) {
                status.textContent = error.name === 'AbortError' ? 'The review check timed out. Please try again.'
                    : AppErrors.message(error, 'Unable to check your changes. Please try again.');
                retry.hidden = false;
            }
            return false;
        } finally { clearTimeout(timeout); if (request === controller) request = null; }
    }
    function prefill(dataDiv, data) {
        const fields = data.fields;
        const mapping = {'raw-type': 'event_type', 'raw-date': 'event_date', 'raw-time': 'event_time', 'raw-end-time': 'event_end_time',
            'raw-location': 'event_location', 'raw-package': 'package_type', 'raw-price': 'total_price', 'raw-requests': 'special_requests',
            'raw-lat': 'event_lat', 'raw-lng': 'event_lng', 'raw-landmark': 'venue_landmark', 'raw-theme': 'design_theme',
            'raw-palette': 'color_palette', 'raw-motto': 'motto_text', 'raw-logistics-override': 'logistics_fee_override'};
        for (const [selector, key] of Object.entries(mapping)) dataDiv.querySelector('.' + selector).textContent = fields[key] ?? '';
        dataDiv.querySelector('.raw-image-url').textContent = data.images.find(image => image.id === 'legacy')?.url || '';
        const multi = dataDiv.querySelector('.raw-multi-images'); multi.replaceChildren();
        for (const image of data.images.filter(image => image.id !== 'legacy')) {
            const span = document.createElement('span'); span.className = 'multi-img-url'; span.dataset.id = image.id; span.textContent = image.url; multi.append(span);
        }
        const designs = dataDiv.querySelector('.raw-design-images'); designs.replaceChildren();
        for (const image of data.design_images || []) {
            const span = document.createElement('span'); span.className = 'design-img-url'; span.dataset.id = image.id; span.textContent = image.url; designs.append(span);
        }
    }
    function sameSchedule() { return active() && value('edit_event_date') === original.fields.event_date
        && value('edit_start_time') === original.fields.event_time && value('edit_end_time') === original.fields.event_end_time; }
    function sameVenue() { return active() && value('edit_event_location') === clean(original.fields.event_location)
        && pin(value('edit_event_lat_input'), value('edit_event_lng_input')) === pin(original.fields.event_lat, original.fields.event_lng); }
    function estimate(items, logistics, overtime) {
        if (!active() && !(pendingMode && original.design_images?.length && !items.length)) return null;
        const selected = items.map(item => item.label.replace(/ \((Add-on|Additional)\)$/, '')).join(' + ');
        const subtotal = selectionString(selected) === original.fields.package_type
            ? Number(original.fields.total_price) - Number(original.logistics) - Number(original.overtime)
            : items.reduce((sum, item) => sum + Number(original.items.find(old => old.label === item.label)?.amount ?? item.amount), 0);
        return subtotal + (sameVenue() ? Number(original.logistics) : logistics) + (sameSchedule() ? Number(original.overtime) : overtime);
    }
    function selectionString(selected) {
        if (!original) return selected;
        if (!selected && original.design_images?.length) return original.fields.package_type;
        const key = text => text.split('+').map(part => part.trim().replace(/\s*\((Add-on|Additional)\)$/i, '')).sort().join('+');
        return key(selected) === key(original.fields.package_type) ? original.fields.package_type : selected;
    }
    scope.ready(() => {
        retry.addEventListener('click', review);
        for (const type of ['input', 'change']) form.addEventListener(type, invalidate);
        form.addEventListener('submit', event => {
            if (active() && (!result || !result.has_changes)) {
                event.preventDefault(); status.textContent = 'Please review your changes before submitting.';
            }
        });
    });
    scope.cleanup(reset);
    window.BookingChangeReview = {configure, reset, review, invalidate, prefill, estimate, sameVenue, selectionString, loadPending};
}, -20);
