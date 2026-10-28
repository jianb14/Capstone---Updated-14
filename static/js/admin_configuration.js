(() => {
    'use strict';
    const form = document.getElementById('ss_form');
    if (!form) return;
    const save = document.getElementById('ss_btn_save'), reset = document.getElementById('ss_reset');
    const feedback = document.getElementById('ss_feedback'), state = document.getElementById('ss_save_state');
    const recipients = window.AdminEmailRecipients?.init(document.getElementById('ss_admin_emails'));
    const controls = [...form.elements].filter(el => el.name && el.name !== 'csrfmiddlewaretoken');
    const snapshot = () => controls.map(el => ({el, value: el.value, checked: el.checked}));
    const equal = (a, b) => a.every((item, i) => item.value === b[i].value && item.checked === b[i].checked);
    let saved = snapshot(), saving = false, locationMap = null, savedMessage = '';
    const dirty = () => !equal(saved, snapshot());
    const update = () => {
        save.disabled = saving || !dirty(); reset.disabled = saving || !dirty();
        state.textContent = saving ? 'Saving your changes…' : dirty() ? 'You have unsaved changes' : savedMessage || 'No unsaved changes';
        state.dataset.kind = !saving && !dirty() && savedMessage ? 'success' : '';
        form.setAttribute('aria-busy', String(saving));
    };
    const message = (text, kind = 'error') => {
        feedback.textContent = text; feedback.dataset.kind = kind; feedback.hidden = !text;
    };
    const clearErrors = () => {
        form.querySelectorAll('[data-error-for]').forEach(el => { el.textContent = ''; });
        form.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
    };
    form.addEventListener('input', event => {
        const el = event.target;
        const name = el.name || el.dataset.fieldName;
        if (name) {
            form.querySelectorAll('[data-error-for]').forEach(error => { if (error.dataset.errorFor === name) error.textContent = ''; });
            el.removeAttribute('aria-invalid');
            if (name === recipients?.field.name) recipients.input.removeAttribute('aria-invalid');
        }
        savedMessage = ''; message(''); update();
    });
    form.addEventListener('change', update);
    reset.addEventListener('click', () => {
        saved.forEach(item => { item.el.value = item.value; item.el.checked = item.checked; });
        recipients?.restore();
        savedMessage = ''; clearErrors(); message('');
        const lat = document.getElementById('ss_shop_lat').value, lng = document.getElementById('ss_shop_lng').value;
        if (locationMap) {
            if (lat && lng) locationMap.placePin(lat, lng, undefined, false);
            else locationMap.clear();
        }
        update();
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (saving) return;
        if (recipients && !recipients.commit()) return;
        const submitted = snapshot(), data = new FormData(form);
        saving = true; clearErrors(); message(''); update();
        try {
            const response = await fetch(form.action || location.href, {
                method: 'POST', body: data, credentials: 'same-origin',
                headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}
            });
            if (!response.headers.get('content-type')?.includes('application/json')) {
                throw new Error(response.redirected || response.status === 401 || response.status === 403 ?
                    'Your session may have expired. Sign in again before saving.' :
                    'Unable to save right now. Your changes are still here. Please try again.');
            }
            const result = await response.json();
            if (!response.ok || !result.success) {
                Object.entries(result.errors || {}).forEach(([name, errors]) => {
                    form.querySelectorAll('[data-error-for]').forEach(el => { if (el.dataset.errorFor === name) el.textContent = errors.join(' '); });
                    const input = name === recipients?.field.name ? recipients.input : form.elements.namedItem(name);
                    if (input?.setAttribute) input.setAttribute('aria-invalid', 'true');
                });
                message(result.message || 'Unable to save your changes. Please try again.');
                const invalid = form.querySelector('[aria-invalid="true"]:not([type="hidden"])');
                if (invalid) { invalid.focus(); invalid.scrollIntoView({block: 'center', behavior: 'smooth'}); }
                else { feedback.focus(); feedback.scrollIntoView({block: 'center'}); }
                return;
            }
            saved = submitted;
            document.getElementById('ss_updated_at').textContent = result.updated_at;
            document.getElementById('ss_updated_by').textContent = `by ${result.updated_by}`;
            message(result.message, 'success');
            savedMessage = 'Settings saved successfully';
            window.AdminConfigurationFeedback?.show(dirty() ?
                'Submitted changes saved. You still have unsaved changes.' : result.message || 'Site settings saved successfully.');
        } catch (error) {
            const detail = error instanceof TypeError ? 'Connection failed. Your changes are still here. Please try again.' :
                (error.message || 'Unable to save right now. Your changes are still here. Please try again.');
            message(detail);
            window.AdminConfigurationFeedback?.show(detail, 'error');
        }
        finally { saving = false; update(); }
    });
    window.addEventListener('beforeunload', event => {
        if (dirty()) { event.preventDefault(); event.returnValue = ''; }
    });
    const links = [...form.querySelectorAll('.cfg-section-nav a')];
    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => {
            const visible = entries.filter(entry => entry.isIntersecting).sort((a,b) => a.boundingClientRect.top - b.boundingClientRect.top);
            if (!visible.length) return;
            links.forEach(link => {
                if (link.hash === `#${visible[0].target.id}`) link.setAttribute('aria-current', 'location');
                else link.removeAttribute('aria-current');
            });
        }, {rootMargin: '-100px 0px -55% 0px'});
        form.querySelectorAll('.cfg-panel').forEach(panel => observer.observe(panel));
    }
    locationMap = window.BookingLocationMap?.init({mapId:'ss_shop_map', latId:'ss_shop_lat', lngId:'ss_shop_lng',
        addressId:'ss_address', searchId:'ss_address', suggestionsId:'ss_address_suggestions', statusId:'ss_shop_map_status',
        initialLat:document.getElementById('ss_shop_lat').value, initialLng:document.getElementById('ss_shop_lng').value,
        searchUrl:form.dataset.searchUrl, reverseUrl:form.dataset.reverseUrl});
    // An address entered while maps are unavailable must not keep the old shop pin.
    if (!locationMap) document.getElementById('ss_address').addEventListener('input', () => {
        document.getElementById('ss_shop_lat').value = '';
        document.getElementById('ss_shop_lng').value = '';
        update();
    });
    if (!locationMap) document.getElementById('ss_shop_map_status').textContent = 'Map unavailable. You can still save the business address; pin the shop when maps are available.';
    saved = snapshot();
    update();
})();
