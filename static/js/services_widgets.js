/* Service tools share booking prices, date rules, and a resumable booking URL. */
(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const data = JSON.parse(byId('services-widget-data')?.textContent || '{}');
    const resumeKey = 'balloorina.service-quiz-resume', aiDraftKey = 'balloorina.service-ai-booking';
    const peso = value => '₱' + Number(value || 0).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const escape = text => {
        const el = document.createElement('span'); el.textContent = String(text || ''); return el.innerHTML;
    };
    function readStored(key) {
        try { return JSON.parse(sessionStorage.getItem(key) || '{}'); } catch (_) { return {}; }
    }
    function store(key, value) {
        try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* Storage may be disabled. */ }
    }
    function csrf() {
        const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.slice(10)) : '';
    }
    const selected = name => document.querySelector(`input[name="${name}"]:checked`)?.value || '';
    const quizFields = ['quizEventType', 'quizEventTypeOther', 'quizVibe', 'quizVibeOther', 'quizColors'];
    // A normal visit starts fresh. Only an explicit interrupted AI login resumes once.
    const resume = readStored(resumeKey);
    try {
        sessionStorage.removeItem('balloorina.service-tools');
        sessionStorage.removeItem(resumeKey);
    } catch (_) {}
    [...quizFields, 'estimatorPackage', 'availabilityDate'].forEach(id => { if (byId(id)) byId(id).value = ''; });
    document.querySelectorAll('.estimator-addons input').forEach(input => { input.checked = false; });
    if (location.hash === '#style-quiz' && resume && Date.now() - resume.createdAt < 10 * 60 * 1000) {
        quizFields.forEach(id => { if (byId(id) && typeof resume[id] === 'string') byId(id).value = resume[id]; });
    }
    function closeSelects() {
        document.querySelectorAll('.tool-field .custom-select-container').forEach(container => {
            container.classList.remove('open');
            container.querySelector('.custom-select-trigger')?.setAttribute('aria-expanded', 'false');
        });
    }
    document.querySelectorAll('.tool-field .custom-select-container').forEach(container => {
        const trigger = container.querySelector('.custom-select-trigger'), input = container.querySelector('input[type="hidden"]');
        const options = [...container.querySelectorAll('li')];
        if (!trigger || !input) return;
        const placeholder = trigger.querySelector('span').textContent;
        trigger.setAttribute('aria-expanded', 'false');
        trigger.setAttribute('aria-label', container.closest('.tool-field').querySelector('label').textContent);
        function sync() {
            const chosen = input.value ? options.find(option => option.dataset.value === input.value) : null;
            trigger.querySelector('span').textContent = chosen ? chosen.textContent : placeholder;
            trigger.querySelector('span').classList.toggle('has-value', !!input.value);
            options.forEach(option => option.setAttribute('aria-selected', String(option === chosen)));
        }
        sync();
        trigger.addEventListener('click', event => {
            event.stopPropagation();
            const opening = !container.classList.contains('open'); closeSelects();
            container.classList.toggle('open', opening); trigger.setAttribute('aria-expanded', String(opening));
        });
        trigger.addEventListener('keydown', event => {
            if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
                event.preventDefault(); if (!container.classList.contains('open')) trigger.click(); options[0]?.focus();
            } else if (event.key === 'Escape') closeSelects();
        });
        options.forEach((option, index) => {
            option.tabIndex = -1; option.setAttribute('role', 'option');
            option.addEventListener('click', event => {
                event.stopPropagation(); input.value = option.dataset.value || ''; sync(); closeSelects(); trigger.focus();
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
            option.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); option.click(); }
                if (event.key === 'Escape') { closeSelects(); trigger.focus(); }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault(); options[(index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length].focus();
                }
            });
        });
        input.addEventListener('change', sync);
    });
    document.addEventListener('click', closeSelects);
    ['quizEventType', 'quizVibe'].forEach(id => {
        const input = byId(id), other = byId(id + 'Other'), field = byId(id + 'OtherField');
        if (!input || !field) return;
        function sync(focus) { field.hidden = input.value !== 'Other'; other.required = !field.hidden; if (focus && !field.hidden) other.focus(); }
        sync(false); input.addEventListener('change', () => sync(true));
    });
    function bookingUrl(source, preferences) {
        const url = new URL(data.bookingUrl || '/booking/', location.origin); url.searchParams.set('from', source);
        const values = { package_id: byId('estimatorPackage')?.value, addon_id: selected('estimatorAddon'), additional_id: selected('estimatorAdditional') };
        const date = byId('availabilityDate')?.value;
        if (date && window.BookingAvailability && !window.BookingAvailability.isDateUnavailable(date, window.BookingAvailability.readData())) values.event_date = date;
        Object.assign(values, preferences || {});
        Object.entries(values).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
        return url.pathname + url.search;
    }
    const find = (items, id) => (items || []).find(item => String(item.id) === String(id));
    function recalc() {
        const pkg = find(data.packages, byId('estimatorPackage')?.value);
        document.querySelectorAll('#estimatorAddons .addon-check').forEach(row => {
            const input = row.querySelector('input'), item = find(data.addons, input.value); if (!item) return;
            input.disabled = !pkg && !(Number(item.solo_price) > 0); if (input.disabled) input.checked = false;
            row.classList.toggle('is-disabled', input.disabled);
            row.querySelector('.addon-label').textContent = item.name + (pkg ? ` (+${peso(item.price)})` : Number(item.solo_price) > 0 ? ` (Solo ${peso(item.solo_price)})` : ' (requires a package)');
        });
        const addon = find(data.addons, selected('estimatorAddon')), hasBase = !!pkg || !!addon;
        document.querySelectorAll('#estimatorAdditionals .addon-check').forEach(row => {
            const input = row.querySelector('input'); input.disabled = !hasBase; if (input.disabled) input.checked = false;
            row.classList.toggle('is-disabled', input.disabled);
        });
        const additional = find(data.additionals, selected('estimatorAdditional'));
        const subtotal = (pkg ? Number(pkg.price) + Number(addon?.price || 0) : Number(addon?.solo_price || 0)) + Number(additional?.price || 0);
        if (byId('estimatorTotal')) {
            byId('estimatorTotal').hidden = !hasBase; byId('estimatorSubtotal').textContent = peso(subtotal);
            byId('estimatorServiceCharge').textContent = peso(data.serviceCharge); byId('estimatorGrand').textContent = peso(subtotal + Number(data.serviceCharge || 0));
        }
        if (byId('estimatorContinue')) byId('estimatorContinue').href = bookingUrl('estimate');
    }
    document.querySelectorAll('.estimator-addons').forEach(group => group.addEventListener('change', event => {
        if (event.target.checked) group.querySelectorAll('input').forEach(input => { if (input !== event.target) input.checked = false; }); recalc();
    }));
    byId('estimatorPackage')?.addEventListener('change', recalc); recalc();
    function message(target, title, body, kind) {
        target.hidden = false; target.dataset.state = kind;
        target.className = target.id === 'quizResult' ? 'quiz-result' : 'availability-result';
        const icon = kind === 'error' ? 'fa-circle-exclamation' : kind === 'success' ? (target.id === 'quizResult' ? 'fa-lightbulb' : 'fa-circle-check') : 'fa-clock';
        const iconStyle = kind === 'error' ? 'fa-solid' : 'fa-regular';
        target.innerHTML = `<div class="tool-message"><i class="${iconStyle} ${icon}" aria-hidden="true"></i><div><strong>${escape(title)}</strong><p>${escape(body)}</p></div></div>`;
        target.setAttribute('aria-busy', String(kind === 'loading'));
    }
    const quiz = byId('quizForm'), quizResult = byId('quizResult');
    let quizVersion = 0;
    function quizValue(id) { return (byId(id)?.value === 'Other' ? byId(id + 'Other')?.value : byId(id)?.value)?.trim() || ''; }
    // Model text is escaped; only HTTP image sources survive the HTML response.
    function renderTheme(text, target) {
        const parsed = new DOMParser().parseFromString(String(text), 'text/html'), images = [];
        parsed.querySelectorAll('img').forEach(img => {
            try {
                const source = img.getAttribute('src');
                if (source) {
                    const url = new URL(source, location.origin);
                    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) images.push(url.href);
                }
            } catch (_) { /* Ignore invalid URLs. */ }
            img.remove();
        });
        parsed.querySelectorAll('script, style, iframe, object').forEach(el => el.remove());
        const plain = parsed.body.textContent || '', escaped = escape(plain);
        target.innerHTML = window.renderAiMarkdown ? window.renderAiMarkdown(escaped) : escaped.replace(/\n/g, '<br>');
        images.forEach((url, index) => {
            const figure = document.createElement('figure'); figure.className = 'quiz-image';
            const img = document.createElement('img'); img.src = url; img.alt = 'Balloorina AI theme concept'; img.loading = 'lazy';
            const download = document.createElement('button'); download.type = 'button'; download.className = 'quiz-image-download';
            download.setAttribute('aria-label', 'Download theme image');
            download.title = 'Download theme image';
            download.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/></svg>';
            download.addEventListener('click', async () => {
                download.disabled = true;
                try {
                    const response = await fetch(url); if (!response.ok) throw new Error('Image unavailable');
                    const blob = await response.blob(); if (!blob.type.startsWith('image/')) throw new Error('Invalid image');
                    const objectUrl = URL.createObjectURL(blob), link = document.createElement('a'); link.href = objectUrl;
                    const extension = blob.type === 'image/jpeg' ? 'jpg' : blob.type === 'image/webp' ? 'webp' : 'png';
                    link.download = `balloorina-theme-${index + 1}.${extension}`; document.body.appendChild(link); link.click(); link.remove();
                    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
                } catch (_) {
                    if (!figure.querySelector('.quiz-download-error')) {
                        const note = document.createElement('p'); note.className = 'quiz-download-error'; note.setAttribute('role', 'alert');
                        note.textContent = 'Download failed. Please try again.'; figure.appendChild(note);
                    }
                } finally { download.disabled = false; }
            });
            figure.append(img, download); target.appendChild(figure);
        });
        return { plain, images };
    }
    quiz?.addEventListener('submit', async event => {
        event.preventDefault();
        const preferences = { event_type: quizValue('quizEventType'), vibe: quizValue('quizVibe'), colors: byId('quizColors').value.trim() };
        if (!preferences.event_type || !preferences.vibe) {
            message(quizResult, 'A little more detail', 'Choose an event type and a vibe. If you select Other, please describe it in the field below.', 'error');
            const missing = !preferences.event_type ? 'quizEventType' : 'quizVibe';
            if (byId(missing).value === 'Other') byId(missing + 'Other').focus();
            else byId(missing).closest('.custom-select-container').querySelector('.custom-select-trigger').focus(); return;
        }
        const version = ++quizVersion;
        const button = byId('quizSubmit'); button.disabled = true; button.textContent = 'Styling your theme…';
        message(quizResult, 'Creating your theme', 'Your event details are with our AI stylist. This may take a moment.', 'loading');
        try {
            const response = await fetch(data.quizUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(preferences) });
            const result = await response.json();
            if (version !== quizVersion) return;
            if (!response.ok || !result.success) {
                message(quizResult, 'Unable to create your theme', result.error || 'The AI stylist is unavailable right now. Please try again.', 'error');
                if (response.status === 403 && /log in/i.test(result.error || '')) {
                    const login = document.createElement('a'); login.className = 'btn btn-primary';
                    login.href = data.loginUrl + '?next=' + encodeURIComponent(location.pathname + '#style-quiz'); login.textContent = 'Log In and Continue'; quizResult.appendChild(login);
                    login.addEventListener('click', () => {
                        const values = { createdAt: Date.now() };
                        quizFields.forEach(id => { values[id] = byId(id)?.value || ''; });
                        store(resumeKey, values);
                    });
                }
                return;
            }
            message(quizResult, 'Your AI Theme Suggestion', 'A starting point for your celebration. You can refine it during booking.', 'success');
            const body = document.createElement('div'); body.className = 'quiz-result-body'; const rendered = renderTheme(result.response, body);
            const book = document.createElement('a'); book.className = 'btn btn-primary btn-sm'; book.href = bookingUrl('ai', preferences); book.textContent = 'Book This Style';
            book.addEventListener('click', () => {
                book.href = bookingUrl('ai', preferences);
                store(aiDraftKey, { ...preferences, notes: rendered.plain.slice(0, 3000), images: rendered.images });
            });
            quizResult.append(body, book);
        } catch (_) {
            if (version === quizVersion) message(quizResult, 'Connection interrupted', 'We could not reach the AI stylist. Check your connection and try again.', 'error');
        } finally {
            if (version === quizVersion) { button.disabled = false; button.innerHTML = '<span>Get My AI Theme</span>'; quizResult.setAttribute('aria-busy', 'false'); }
        }
    });
    const dateInput = byId('availabilityDate'), availability = byId('availabilityResult'), check = byId('availabilityCheck');
    if (dateInput && window.BookingPickers && window.BookingAvailability) {
        dateInput.min = window.BookingAvailability.getMinBookableDate(window.BookingAvailability.readData());
        window.BookingPickers.init({ dateId: 'availabilityDate' });
        const icon = dateInput.parentElement.querySelector('.booking-picker-icon');
        if (icon) icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 11h16"/></svg>';
    }
    let requestVersion = 0;
    dateInput?.addEventListener('change', () => {
        requestVersion++; availability.hidden = true; check.disabled = false; check.innerHTML = '<span>Check Availability</span>'; recalc();
    });
    check?.addEventListener('click', async () => {
        const value = dateInput.value;
        if (!value) { message(availability, 'Choose your event date', 'Open the calendar and select an available date to check.', 'error'); dateInput.focus(); return; }
        const version = ++requestVersion; check.disabled = true; check.textContent = 'Checking…';
        message(availability, 'Checking your date', 'Looking for open time slots for your event.', 'loading');
        try {
            const response = await fetch(data.availabilityUrl + '?date=' + encodeURIComponent(value)), result = await response.json();
            if (version !== requestVersion) return;
            if (!response.ok || !result.success) { message(availability, 'Unable to check this date', result.error || 'Please try again.', 'error'); return; }
            const label = new Date(value + 'T00:00:00').toLocaleDateString('en-PH', { month: 'long', day: 'numeric', year: 'numeric' });
            message(availability, result.available ? 'Time slots available' : 'Choose another date', `${label}. ${result.message}`, result.available ? 'success' : 'error');
            if (!result.available && result.suggestions?.length) {
                const chips = document.createElement('div'); chips.className = 'availability-suggestions';
                result.suggestions.forEach(date => {
                    const chip = document.createElement('button'); chip.type = 'button'; chip.className = 'availability-chip';
                    chip.textContent = new Date(date + 'T00:00:00').toLocaleDateString('en-PH', { month: 'short', day: 'numeric' });
                    chip.addEventListener('click', () => { dateInput.value = date; dateInput.dispatchEvent(new Event('change', { bubbles: true })); check.click(); }); chips.appendChild(chip);
                });
                availability.appendChild(chips);
            }
            if (result.available) {
                const book = document.createElement('a'); book.className = 'btn btn-primary btn-sm availability-book';
                book.href = bookingUrl('availability'); book.textContent = 'Continue with This Date'; availability.appendChild(book);
                book.addEventListener('click', () => { book.href = bookingUrl('availability'); });
            }
        } catch (_) {
            if (version === requestVersion) message(availability, 'Connection interrupted', 'Check your connection and try again.', 'error');
        } finally {
            if (version === requestVersion) { check.disabled = false; check.innerHTML = '<span>Check Availability</span>'; availability.setAttribute('aria-busy', 'false'); }
        }
    });
    function clearTool(tool) {
        closeSelects();
        if (tool === 'estimate') {
            if (byId('estimatorPackage')) {
                byId('estimatorPackage').value = '';
                byId('estimatorPackage').dispatchEvent(new Event('change', { bubbles: true }));
            }
            document.querySelectorAll('.estimator-addons input').forEach(input => { input.checked = false; });
            recalc();
        } else if (tool === 'quiz') {
            quizVersion++;
            quizFields.forEach(id => { if (byId(id)) { byId(id).value = ''; byId(id).dispatchEvent(new Event('change', { bubbles: true })); } });
            if (quizResult) { quizResult.hidden = true; quizResult.replaceChildren(); quizResult.setAttribute('aria-busy', 'false'); }
            if (byId('quizSubmit')) { byId('quizSubmit').disabled = false; byId('quizSubmit').innerHTML = '<span>Get My AI Theme</span>'; }
            try { sessionStorage.removeItem(resumeKey); sessionStorage.removeItem(aiDraftKey); } catch (_) {}
        } else if (tool === 'date' && dateInput) {
            dateInput.value = '';
            dateInput.dispatchEvent(new Event('change', { bubbles: true }));
            availability.replaceChildren();
            availability.setAttribute('aria-busy', 'false');
            window.BookingPickers?.refreshAll();
        }
    }
    document.querySelectorAll('[data-clear-tool]').forEach(button => button.addEventListener('click', () => clearTool(button.dataset.clearTool)));
    window.addEventListener('pageshow', event => {
        if (event.persisted) ['estimate', 'quiz', 'date'].forEach(clearTool);
    });
})();
