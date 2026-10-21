/* Keep the server's request queue, filters and pagination in sync without reloading. */
(() => {
    'use strict';
    const form = document.querySelector('.request-filter-form');
    if (!form) return;
    const search = form.querySelector('[type=search]');
    const status = form.querySelector('#requestStatus');
    const results = document.getElementById('requestResults');
    const feedback = document.querySelector('.request-filter-feedback');
    const clear = form.querySelector('.request-clear-link');
    const dropdown = form.querySelector('.request-status-dropdown');
    const trigger = dropdown.querySelector('.dropdown-trigger');
    const text = dropdown.querySelector('#requestStatusText');
    const options = [...dropdown.querySelectorAll('[role=option]')];
    let timer, controller, latestUrl;

    function syncStatus() {
        text.textContent = status.selectedOptions[0].textContent;
        options.forEach(option => {
            const selected = option.dataset.value === status.value;
            option.classList.toggle('selected', selected);
            option.setAttribute('aria-selected', String(selected));
        });
        clear.hidden = !search.value && !status.value;
    }
    function closeMenu(restoreFocus = false) {
        dropdown.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
        if (restoreFocus) trigger.focus();
    }
    function openMenu() {
        dropdown.classList.add('open');
        trigger.setAttribute('aria-expanded', 'true');
        (options.find(option => option.dataset.value === status.value) || options[0]).focus();
    }
    function filterUrl() {
        const url = new URL(form.action);
        for (const [key, value] of new FormData(form)) if (value) url.searchParams.set(key, value);
        return url;
    }
    async function load(url, historyMode = 'replace') {
        controller?.abort();
        const active = new AbortController(); controller = active; latestUrl = url;
        results.setAttribute('aria-busy', 'true'); feedback.hidden = true;
        try {
            const response = await fetch(url, { signal: active.signal, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!response.ok) throw new Error('Request failed');
            const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
            const next = doc.getElementById('requestResults');
            if (!next) throw new Error('Request list unavailable');
            if (active.signal.aborted) return;
            results.innerHTML = next.innerHTML;
            clear.hidden = !search.value && !status.value;
            if (historyMode !== 'none') history[historyMode === 'push' ? 'pushState' : 'replaceState']({}, '', url);
        } catch (error) {
            if (error.name === 'AbortError' || active.signal.aborted) return;
            feedback.replaceChildren(document.createTextNode('Could not update requests. '));
            const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry';
            retry.addEventListener('click', () => load(latestUrl, historyMode));
            feedback.append(retry); feedback.hidden = false;
        } finally {
            if (controller === active) results.setAttribute('aria-busy', 'false');
        }
    }
    function apply() { clearTimeout(timer); syncStatus(); load(filterUrl()); }
    search.addEventListener('input', () => {
        clearTimeout(timer); controller?.abort(); syncStatus();
        timer = setTimeout(apply, 300);
    });
    status.addEventListener('change', apply);
    form.addEventListener('submit', event => { event.preventDefault(); apply(); });
    results.addEventListener('click', event => {
        const link = event.target.closest('.request-pagination a');
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
        event.preventDefault(); clearTimeout(timer); load(new URL(link.href), 'push');
    });
    trigger.hidden = false; dropdown.classList.add('is-enhanced'); syncStatus();
    trigger.addEventListener('click', () => dropdown.classList.contains('open') ? closeMenu() : openMenu());
    trigger.addEventListener('keydown', event => {
        if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); openMenu(); }
    });
    options.forEach(option => option.addEventListener('click', () => {
        status.value = option.dataset.value; closeMenu(true); apply();
    }));
    dropdown.addEventListener('keydown', event => {
        const current = options.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
        if (event.key === 'Tab') closeMenu();
        if (current < 0) return;
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
            options[next].focus();
        }
        if (['Enter', ' '].includes(event.key)) { event.preventDefault(); options[current].click(); }
    });
    document.addEventListener('click', event => { if (!dropdown.contains(event.target)) closeMenu(); });
    window.addEventListener('popstate', () => {
        clearTimeout(timer);
        const url = new URL(location.href);
        if (url.searchParams.get('scope') !== form.elements.scope.value) { location.reload(); return; }
        search.value = url.searchParams.get('request_search') || '';
        status.value = url.searchParams.get('request_status') || '';
        syncStatus(); load(url, 'none');
    });
})();
