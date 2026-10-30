/* Admin calendar: existing event/filter rules, async block/unblock and safe text rendering. */
(() => {
    'use strict';
    const root = document.querySelector('.admin-calendar-page');
    if (!root) return;
    const $ = selector => root.querySelector(selector);
    const readJSON = id => JSON.parse(document.getElementById(id)?.textContent || '{}');
    let allEvents = readJSON('admin-calendar-events'), conflicts = readJSON('admin-booking-conflict-counts');
    let today = root.dataset.today, activeFilter = 'all', calendar = null, busy = false, pickerYear;
    let dayRefreshTimer, serverClockOffset = Date.parse(root.dataset.serverNow) - Date.now();
    let nextDayAt = Date.parse(root.dataset.nextDayAt);
    const mount = $('#admin-calendar-mount'), popover = $('#calPopover'), picker = $('#custom-month-year-picker');
    const blockForm = $('.blocked-form'), dateInput = $('#blockedDate'), reasonInput = $('#blockedReason');
    const feedback = $('#cal-feedback'), confirmation = $('#calConfirm');
    const csrf = blockForm.querySelector('[name=csrfmiddlewaretoken]').value;
    const pinIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/></svg>';
    const calendarIcon = $('.cal-block-date-icon')?.innerHTML || $('.cal-section-icon').innerHTML;
    let blockedDates = new Set(allEvents.filter(event => event.status_raw === 'blocked').map(event => event.start.slice(0,10)));

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }
    function prettyDate(iso, short = false) {
        return new Date(iso.slice(0,10) + 'T12:00:00').toLocaleDateString('en-US', {
            year:'numeric', month:short ? 'short' : 'long', day:'numeric', ...(short ? {weekday:'short'} : {})
        });
    }
    function isoLocal(date) {
        return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    }
    function statusLabel(event) {
        return event.status || event.status_raw.replaceAll('_',' ').replace(/^./, letter => letter.toUpperCase());
    }
    function eventColor(event) {
        return ({confirmed:'var(--cal-blue)',pending:'var(--cal-amber)',pending_payment:'var(--cal-amber)',completed:'var(--cal-green)',cancelled:'var(--cal-red)',expired:'var(--ac-muted)',blocked:'var(--ac-muted)',temporary_hold:'var(--cal-amber)'})[event.status_raw] || 'var(--cal-blue)';
    }
    function closePopover() { popover.hidden = true; }
    function closePicker(restoreFocus = false) {
        picker.hidden = true; $('#cal-title').setAttribute('aria-expanded','false');
        if (restoreFocus) $('#cal-title').focus({preventScroll:true});
    }
    function notify(message, kind = 'success') {
        if (window.AdminConfigurationFeedback) window.AdminConfigurationFeedback.show(message, kind);
        else { feedback.textContent = message; feedback.dataset.kind = kind; feedback.hidden = false; }
    }
    function clearErrors() {
        blockForm.querySelectorAll('[data-error-for],#blocked-form-error').forEach(element => { element.hidden = true; element.textContent = ''; });
        blockForm.querySelectorAll('[aria-invalid]').forEach(element => element.removeAttribute('aria-invalid'));
        feedback.hidden = true;
    }
    function fieldError(field, message) {
        const error = blockForm.querySelector(`[data-error-for="${field}"]`);
        if (error) { error.textContent = message; error.hidden = false; blockForm.elements[field].setAttribute('aria-invalid','true'); }
        else { $('#blocked-form-error').textContent = message; $('#blocked-form-error').hidden = false; }
    }
    function updateHint() {
        const count = Number(conflicts[dateInput.value] || 0), hint = $('#blockedConflictHint');
        hint.hidden = !count;
        hint.textContent = count ? `${prettyDate(dateInput.value)} already has ${count} booking${count === 1 ? '' : 's'}. Blocking prevents new bookings — existing ones stay visible.` : '';
    }
    function ask(title, message, label) {
        return new Promise(resolve => {
            $('#calConfirmTitle').textContent = title; $('#calConfirmMessage').textContent = message;
            $('#calConfirmSubmit').textContent = label; confirmation.returnValue = '';
            confirmation.addEventListener('close', () => resolve(confirmation.returnValue === 'confirm'), {once:true});
            confirmation.showModal();
            confirmation.querySelector('[data-cancel-confirm]').focus({preventScroll:true});
        });
    }
    function openBlockModal(count, iso) {
        return ask('Date already has bookings', `${prettyDate(iso)} already has ${count} booking${count === 1 ? '' : 's'}. Blocking prevents new customer bookings. The existing bookings stay visible on the calendar.`, 'Block Anyway');
    }
    confirmation.querySelectorAll('[data-cancel-confirm]').forEach(button => button.addEventListener('click', () => confirmation.close('cancel')));
    confirmation.addEventListener('click', event => { if (event.target === confirmation) { const box = confirmation.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) confirmation.close('cancel'); } });

    async function request(url, options = {}) {
        const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
        try {
            const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options,
                headers:{'X-Requested-With':'XMLHttpRequest',...(options.method === 'POST' ? {'X-CSRFToken':csrf} : {})}, signal:controller.signal});
            if (response.redirected || response.status === 401) throw new Error('Your session may have expired. Refresh the page and sign in again.');
            if (response.status === 403) throw new Error('This action could not be authorized. Refresh the page before trying again.');
            if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('The calendar could not be updated. Please try again.');
            const data = await response.json();
            if (!response.ok && !data.message) throw new Error('The calendar could not be updated. Please try again.');
            return {...data, httpOK:response.ok};
        } catch (error) {
            if (error.name === 'AbortError') throw new Error('The request timed out. Refresh the calendar to check its latest state before trying again.');
            throw error;
        } finally { clearTimeout(timer); }
    }
    function renderBlockedList(items, archived = false) {
        const list = $(archived ? '#pastBlockedDatesList' : '#blockedDatesList'); list.replaceChildren();
        $(archived ? '#past-blocked-date-count' : '#blocked-date-count').textContent = archived ? `(${items.length})` : items.length;
        if (archived) {
            $('#pastBlockedDates').hidden = !items.length;
            if (!items.length) $('#pastBlockedDates').open = false;
        }
        if (!items.length && !archived) {
            const empty = node('div','blocked-empty'), icon = node('span','cal-empty-icon'); icon.innerHTML = calendarIcon;
            empty.append(icon,node('h3',null,'No blocked dates'),node('p',null,'Today and future dates you block will appear here.')); list.append(empty); return;
        }
        items.forEach(item => {
            const row = node('div','blocked-item'), icon = node('span','cal-block-date-icon'), copy = node('div','blocked-item-copy');
            row.dataset.blockedDate = item.date; icon.innerHTML = calendarIcon;
            copy.append(node('div','blocked-item-date',prettyDate(item.date,true)));
            if (item.reason) copy.append(node('div','blocked-item-reason',item.reason));
            row.append(icon,copy);
            if (!archived) {
                const form = node('form','js-unblock-form'); form.method = 'post'; form.action = item.delete_url; form.dataset.unblockDate = item.date;
                const token = node('input'); token.type = 'hidden'; token.name = 'csrfmiddlewaretoken'; token.value = csrf;
                const button = node('button','ac-button blocked-unblock-btn','Unblock'); button.type = 'submit'; form.append(token,button);
                row.append(form);
            }
            list.append(row);
        });
    }
    async function loadState() {
        const data = await request(root.dataset.calendarUrl);
        if (!data.httpOK || !Array.isArray(data.events) || !Array.isArray(data.blocked_dates) || !Array.isArray(data.past_blocked_dates)) throw new Error('The calendar returned an incomplete update. Please refresh it.');
        allEvents = data.events; conflicts = data.conflict_counts; today = data.today_iso; dateInput.min = today;
        root.dataset.today = today;
        serverClockOffset = Date.parse(data.server_now) - Date.now(); nextDayAt = Date.parse(data.next_day_at);
        blockedDates = new Set(allEvents.filter(isBlockedFlagEvent).map(item => item.start.slice(0,10)));
        renderBlockedList(data.blocked_dates); renderBlockedList(data.past_blocked_dates, true);
        calendar?.setOption('now',today); refreshEvents(); updateHint(); updateToolbar(); scheduleDayRefresh();
    }
    // Use server time so browser timezone/clock settings cannot archive today early.
    function scheduleDayRefresh(delay) {
        clearTimeout(dayRefreshTimer);
        if (!Number.isFinite(nextDayAt) || !Number.isFinite(serverClockOffset)) return;
        dayRefreshTimer = setTimeout(refreshAfterMidnight, delay ?? Math.max(1000, nextDayAt - (Date.now() + serverClockOffset) + 250));
    }
    async function refreshAfterMidnight() {
        if (Date.now() + serverClockOffset < nextDayAt) { scheduleDayRefresh(); return; }
        if (busy || document.hidden) { scheduleDayRefresh(60000); return; }
        setBusy(true);
        try { await loadState(); }
        catch (_) { scheduleDayRefresh(60000); }
        finally { setBusy(false); }
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshAfterMidnight(); });
    window.addEventListener('focus',refreshAfterMidnight);
    function setBusy(value) {
        busy = value; blockForm.querySelector('[type=submit]').disabled = value;
        $('#cal-refresh').disabled = value; $('#blockedDatesList').querySelectorAll('button').forEach(button => button.disabled = value);
        root.setAttribute('aria-busy',String(value));
    }
    async function postAction(form, body) {
        const result = await request(form.action, {method:'POST', body});
        if (result.ok) {
            if (form === blockForm) { blockForm.reset(); $('#blocked-reason-count').textContent = '0/255'; }
            notify(result.message, result.kind || 'success');
            try { await loadState(); }
            catch (error) { feedback.hidden = false; feedback.dataset.kind = 'error'; feedback.textContent = `Your change was saved. ${error.message}`; }
        }
        return result;
    }
    blockForm.addEventListener('submit', async event => {
        event.preventDefault(); if (busy) return; clearErrors();
        if (!dateInput.value) { fieldError('date','Please choose a date to block.'); dateInput.focus(); return; }
        if (dateInput.value < today) { fieldError('date','Cannot block a date in the past.'); dateInput.focus(); return; }
        const body = new FormData(blockForm), iso = body.get('date'); body.set('confirm_conflicts','');
        const count = Number(conflicts[iso] || 0);
        setBusy(true);
        try {
            if (count && !await openBlockModal(count, iso)) return;
            if (count) body.set('confirm_conflicts','1');
            let result = await postAction(blockForm, body);
            // A booking may have arrived since the page loaded: the server still requires confirmation.
            if (result.requires_confirmation && !body.get('confirm_conflicts') && await openBlockModal(result.conflict_count,iso)) {
                body.set('confirm_conflicts','1'); result = await postAction(blockForm,body);
            }
            if (!result.ok && !result.requires_confirmation) {
                if (Object.keys(result.errors || {}).length) Object.entries(result.errors).forEach(([field,message]) => fieldError(field,message));
                else fieldError(null,result.message);
                blockForm.querySelector('[aria-invalid]')?.focus({preventScroll:true});
            }
        } catch (error) { fieldError(null,error.message); notify(error.message,'error'); }
        finally { setBusy(false); }
    });
    $('#blockedDatesList').addEventListener('submit', async event => {
        const form = event.target.closest('.js-unblock-form'); if (!form) return;
        event.preventDefault(); if (busy) return; setBusy(true);
        try {
            if (!await ask('Unblock this date?', `${prettyDate(form.dataset.unblockDate)} will no longer be blocked. Existing bookings are not affected.`, 'Unblock')) return;
            const result = await postAction(form,new FormData(form));
            if (!result.ok) notify(result.message,'error');
        } catch (error) { notify(error.message,'error'); }
        finally { setBusy(false); }
    });
    dateInput.addEventListener('input', () => { $('#blockDateConfirmConflicts').value = ''; clearErrors(); updateHint(); });
    reasonInput.addEventListener('input', () => $('#blocked-reason-count').textContent = `${reasonInput.value.length}/255`);
    $('#cal-refresh').addEventListener('click', async () => {
        if (busy) return; setBusy(true); feedback.hidden = true;
        try { await loadState(); notify('Calendar updated.'); }
        catch (error) { notify(error.message,'error'); }
        finally { setBusy(false); }
    });

    function isBlockedFlagEvent(event) { return event.status_raw === 'blocked'; }
    function eventsForFilter() {
        return allEvents.filter(event => activeFilter === 'all' || event.status_raw === activeFilter || isBlockedFlagEvent(event)).map(event => ({
            title:event.title, start:event.start, end:event.end || undefined,
            backgroundColor:event.color, borderColor:event.color, textColor:'#fff', extendedProps:event
        }));
    }
    function usesCompactEvents() { return matchMedia('(max-width:768px)').matches || mount.clientWidth < 620; }
    function applyEventMode() {
        mount.querySelectorAll('.fc-event').forEach(element => {
            const compact = usesCompactEvents() && !element.closest('.fc-timegrid,.fc-popover') && !element.classList.contains('blocked-flag-event');
            element.classList.toggle('cal-event-bar', compact);
        });
    }
    function decorateDays() {
        // Week view already has a clickable all-day blocked event; do not add a second label.
        mount.querySelectorAll('.fc-dayGridMonth-view .fc-daygrid-day[data-date]').forEach(cell => {
            const iso = cell.dataset.date, blocked = blockedDates.has(iso);
            cell.classList.toggle('booking-day-blocked',blocked); cell.classList.toggle('admin-past-day',iso < today);
            cell.querySelector('.booking-day-blocked-label')?.remove(); cell.classList.remove('booking-day-empty');
            if (!blocked) { cell.removeAttribute('title'); return; }
            const count = allEvents.filter(event => event.start.slice(0,10) === iso && !isBlockedFlagEvent(event)).length;
            cell.title = 'Unavailable — blocked date' + (count ? ` (${count} existing booking(s) remain)` : '');
            const label = node('div','booking-day-blocked-label'); label.innerHTML = pinIcon;
            label.append(node('span',null,'Blocked' + (count ? ` (${count})` : '')));
            cell.classList.toggle('booking-day-empty',!count);
            (count ? cell.querySelector('.fc-daygrid-day-top') : cell.querySelector('.fc-daygrid-day-frame')).append(label);
        });
    }
    function refreshEvents() {
        closePopover(); if (!calendar) return;
        calendar.batchRendering(() => { calendar.getEventSources().forEach(source => source.remove()); calendar.addEventSource(eventsForFilter()); });
        decorateDays(); applyEventMode();
    }
    function showEvents(events, label, anchor) {
        const body = $('#calPopBody'); body.replaceChildren(); $('#calPopDate').textContent = label;
        if (!events.length) {
            const empty = node('div','cal-pop-empty'), icon = node('span','cal-empty-icon'); icon.innerHTML = calendarIcon;
            empty.append(icon,node('p',null,'No bookings on this date.')); body.append(empty);
        }
        const actual = events.filter(event => !isBlockedFlagEvent(event));
        if (events.some(isBlockedFlagEvent) && actual.length) body.append(node('div','cal-pop-blocked-warning',`Blocked date — ${actual.length} existing booking(s) remain on this date.`));
        events.forEach(event => {
            const card = node('article','cal-pop-event'); card.style.setProperty('--cal-event-color',eventColor(event));
            // User-provided names, event types and reasons must stay plain text.
            if (isBlockedFlagEvent(event)) {
                card.append(node('div','cal-pop-name','Blocked date'),node('div','cal-pop-detail',event.reason || 'Unavailable for new bookings.'));
            } else {
                card.append(node('div','cal-pop-name',event.client_name),node('div','cal-pop-detail',event.event_type),node('div','cal-pop-detail',event.time_range),node('div','cal-pop-detail',statusLabel(event)));
            }
            body.append(card);
        });
        popover.hidden = false;
        const rect = anchor?.getBoundingClientRect(), margin = 12;
        popover.style.maxHeight = `${innerHeight - margin*2}px`;
        const box = popover.getBoundingClientRect();
        let top = rect ? rect.bottom + 6 : margin, left = rect ? rect.left : margin;
        if (top + box.height > innerHeight - margin) top = rect && rect.top - box.height - 6 >= margin ? rect.top - box.height - 6 : Math.max(margin,innerHeight - box.height - margin);
        left = Math.max(margin,Math.min(left,innerWidth - box.width - margin));
        popover.style.top = `${top}px`; popover.style.left = `${left}px`;
        popover.focus({preventScroll:true});
    }
    function updateToolbar() {
        if (!calendar) return;
        $('#cal-title-text').textContent = calendar.view.title;
        const week = calendar.view.type === 'timeGridWeek';
        $('#cal-prev').setAttribute('aria-label',week ? 'Previous week' : 'Previous month');
        $('#cal-next').setAttribute('aria-label',week ? 'Next week' : 'Next month');
        root.querySelectorAll('[data-view]').forEach(button => { const active = button.dataset.view === calendar.view.type; button.classList.toggle('active',active); button.setAttribute('aria-pressed',String(active)); });
        const now = new Date(today + 'T00:00:00');
        $('#cal-today').disabled = now >= calendar.view.activeStart && now < calendar.view.activeEnd;
        decorateDays(); applyEventMode();
    }
    try {
        if (!window.FullCalendar) throw new Error('Calendar library unavailable');
        calendar = new FullCalendar.Calendar(mount, {
            initialView:'dayGridMonth', now:today, showNonCurrentDates:false, fixedWeekCount:false,
            headerToolbar:false, eventDisplay:'block', displayEventTime:false, dayMaxEvents:usesCompactEvents() ? 3 : false,
            height:'auto', events:eventsForFilter(),
            eventClassNames:info => info.event.extendedProps.status_raw === 'blocked' ? ['blocked-flag-event'] : [],
            eventContent:info => {
                if (info.view.type !== 'timeGridWeek' || !isBlockedFlagEvent(info.event.extendedProps)) return true;
                const label = node('div','cal-week-blocked'); label.innerHTML = pinIcon;
                label.append(node('span',null,'Blocked'));
                return {domNodes:[label]};
            },
            dayCellClassNames:info => blockedDates.has(isoLocal(info.date)) ? ['booking-day-blocked'] : [],
            eventDidMount:info => {
                const color = eventColor(info.event.extendedProps);
                info.el.style.backgroundColor = `color-mix(in srgb, ${color} 13%, var(--ac-bg))`;
                info.el.style.color = color; info.el.style.setProperty('--cal-event-color',color);
                info.el.setAttribute('aria-label',`${info.event.title}, ${statusLabel(info.event.extendedProps)}`);
                info.el.tabIndex = 0;
                info.el.addEventListener('keydown',event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); showEvents([info.event.extendedProps],info.event.extendedProps.event_date,info.el); } });
                applyEventMode();
            },
            datesSet:() => { closePopover(); closePicker(); updateToolbar(); },
            windowResize:() => { if (!calendar) return; calendar.setOption('dayMaxEvents',usesCompactEvents() ? 3 : false); decorateDays(); applyEventMode(); },
            dateClick:info => showEvents(allEvents.filter(event => event.start.slice(0,10) === info.dateStr.slice(0,10)),prettyDate(info.dateStr),info.dayEl),
            eventClick:info => { info.jsEvent.preventDefault(); info.jsEvent.stopPropagation(); showEvents([info.event.extendedProps],info.event.extendedProps.event_date,info.el); },
            eventTimeFormat:{hour:'2-digit',minute:'2-digit',meridiem:false}
        });
        calendar.render(); updateToolbar();
    } catch (_) {
        calendar = null;
        window.showBookingCalendarLoadError?.('Calendar library could not be loaded.');
        root.querySelectorAll('[data-view],#cal-prev,#cal-next,#cal-title,#cal-today').forEach(button => button.disabled = true);
    }
    $('#cal-prev').addEventListener('click', () => calendar?.prev());
    $('#cal-next').addEventListener('click', () => calendar?.next());
    $('#cal-today').addEventListener('click', () => calendar?.gotoDate(today));
    root.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => calendar?.changeView(button.dataset.view)));
    $('#cal-title').addEventListener('click', () => {
        if (!calendar) return;
        if (!picker.hidden) { closePicker(true); return; }
        pickerYear = calendar.getDate().getFullYear(); $('#myp-year-display').textContent = pickerYear;
        picker.querySelectorAll('[data-month]').forEach(button => button.classList.toggle('active-month',Number(button.dataset.month) === calendar.getDate().getMonth()));
        picker.hidden = false; $('#cal-title').setAttribute('aria-expanded','true'); picker.querySelector('.active-month')?.focus({preventScroll:true});
    });
    $('#myp-prev-year').addEventListener('click', () => $('#myp-year-display').textContent = --pickerYear);
    $('#myp-next-year').addEventListener('click', () => $('#myp-year-display').textContent = ++pickerYear);
    picker.querySelectorAll('[data-month]').forEach(button => button.addEventListener('click', () => { calendar?.gotoDate(new Date(pickerYear,Number(button.dataset.month),1)); closePicker(true); }));
    root.querySelectorAll('.legend-filter').forEach(button => button.addEventListener('click', () => {
        activeFilter = activeFilter === button.dataset.status ? 'all' : button.dataset.status;
        root.querySelectorAll('.legend-filter').forEach(chip => { const active = chip.dataset.status === activeFilter; chip.classList.toggle('active',active); chip.setAttribute('aria-pressed',String(active)); });
        const note = $('#cal-filter-note'); note.hidden = activeFilter === 'all'; note.textContent = note.hidden ? '' : `Showing ${button.querySelector('span:nth-child(2)').textContent.toLowerCase()} bookings`;
        refreshEvents();
    }));
    $('#calPopClose').addEventListener('click',closePopover);
    document.addEventListener('click',event => {
        if (!picker.contains(event.target) && !event.target.closest('#cal-title')) closePicker();
        if (!popover.contains(event.target) && !event.target.closest('.fc-event,.fc-daygrid-day,.fc-timegrid-col')) closePopover();
    });
    document.addEventListener('keydown',event => { if (event.key === 'Escape' && !confirmation.open) { if (!popover.hidden) { closePopover(); $('#cal-title').focus({preventScroll:true}); } if (!picker.hidden) closePicker(true); } });
    window.addEventListener('resize',() => { closePopover(); closePicker(); });
    // Collapsing the admin sidebar changes calendar width without a window resize.
    let lastWidth = mount.clientWidth;
    new ResizeObserver(() => { const width = mount.clientWidth; if (!calendar || width === lastWidth) return; lastWidth = width; requestAnimationFrame(() => { calendar.updateSize(); calendar.setOption('dayMaxEvents',usesCompactEvents() ? 3 : false); decorateDays(); applyEventMode(); }); }).observe(mount);
    updateHint(); scheduleDayRefresh();
})();
