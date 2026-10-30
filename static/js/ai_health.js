/* Read-only AI Health filters. Never call the AI provider from this page. */
(() => {
    'use strict';
    const root = document.querySelector('[data-health-url]');
    if (!root) return;
    const periodForm = root.querySelector('#ahPeriodForm');
    const filterForm = root.querySelector('#ahRequestFilters');
    const summary = root.querySelector('#ahSummary');
    const results = root.querySelector('#ahRequests');
    const search = filterForm.elements.q;
    const state = filterForm.elements.state;
    const days = periodForm.elements.days;
    const clear = root.querySelector('.ac-search-clear');
    const refresh = root.querySelector('#ahRefresh');
    const notice = root.querySelector('.ah-load-error');
    const status = root.querySelector('#ahUpdateStatus');
    const selects = window.AdminSelects?.create(root);
    let controller, sequence = 0, debounce, lastAttempt, disposed = false;
    let applied = readURL(new URL(location.href));
    let desired = {...applied};

    function readURL(url) {
        const p = url.searchParams;
        return {days: ['1', '7', '30'].includes(p.get('days')) ? p.get('days') : '7',
            state: ['queued', 'running', 'succeeded', 'failed'].includes(p.get('state')) ? p.get('state') : '',
            q: (p.get('q') || '').trim().slice(0, 80), per_page: p.get('per_page') === '4' ? '4' : '8', page: p.get('page') || '1'};
    }
    function urlFor(filters) {
        const url = new URL(root.dataset.healthUrl, location.origin);
        Object.entries(filters).forEach(([key, value]) => {if (value !== '') url.searchParams.set(key, value);});
        return url;
    }
    function sync(filters) {
        days.value = filters.days;
        filterForm.elements.days.value = filters.days;
        state.value = filters.state;
        search.value = filters.q;
        clear.hidden = !search.value;
        selects?.sync();
    }
    function cancelPending() {
        clearTimeout(debounce);
        controller?.abort();
        sequence++;
        root.classList.remove('is-loading', 'is-refreshing');
        root.removeAttribute('aria-busy');
        refresh.disabled = false;
    }
    async function load(filters, {historyMode = 'push', refreshSummary = false} = {}) {
        cancelPending();
        desired = {...filters};
        const id = sequence;
        const updateSummary = refreshSummary || filters.days !== applied.days;
        lastAttempt = {filters: {...filters}, historyMode, refreshSummary: updateSummary};
        const request = new AbortController();
        controller = request;
        const timeout = setTimeout(() => request.abort(), 15000);
        root.classList.add('is-loading');
        if (updateSummary) root.classList.add('is-refreshing');
        root.setAttribute('aria-busy', 'true');
        refresh.disabled = true;
        notice.hidden = true;
        status.textContent = 'Updating AI health…';
        try {
            const response = await fetch(urlFor(filters), {headers: {'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json'},
                credentials: 'same-origin', cache: 'no-store', signal: request.signal});
            if (response.redirected || response.status === 401 || response.status === 403) throw new Error('auth');
            if (!response.ok) throw new Error('network');
            const data = await response.json();
            if (!data.filters || typeof data.results_html !== 'string' || typeof data.summary_html !== 'string') throw new Error('network');
            if (id !== sequence || disposed) return;
            // Preserve keyboard focus when pagination replaces its triggering link.
            const focused = results.contains(document.activeElement);
            const activityOpen = summary.querySelector('.ah-data')?.open;
            selects?.release(results);
            results.innerHTML = data.results_html;
            if (updateSummary) {
                summary.innerHTML = data.summary_html;
                if (activityOpen && summary.querySelector('.ah-data')) summary.querySelector('.ah-data').open = true;
                summary.classList.remove('ah-content-enter');
                void summary.offsetWidth;
                summary.classList.add('ah-content-enter');
            }
            results.classList.remove('ah-content-enter');
            void results.offsetWidth;
            results.classList.add('ah-content-enter');
            selects?.enhance();
            applied = {...data.filters};
            desired = {...applied};
            sync(applied);
            if (historyMode !== 'none') {
                const url = urlFor(applied);
                if (historyMode === 'replace' || url.href === location.href) history.replaceState(null, '', url);
                else history.pushState(null, '', url);
            }
            if (focused) {
                results.querySelector('[aria-current="page"]')?.setAttribute('tabindex', '-1');
                results.querySelector('[aria-current="page"]')?.focus({preventScroll: true});
            }
            status.textContent = `${updateSummary ? 'AI health' : 'Request history'} updated. ${data.checked_at}, Philippine time.`;
        } catch (error) {
            if (id !== sequence || disposed) return;
            notice.querySelector('span').textContent = error.message === 'auth'
                ? 'Your session may have expired or access has changed. Sign in again to refresh this report.'
                : 'Could not update AI health. The last loaded figures are still shown. Try again.';
            notice.hidden = false;
            status.textContent = 'Update failed. The last loaded figures are still shown.';
        } finally {
            clearTimeout(timeout);
            if (id === sequence && !disposed) {
                root.classList.remove('is-loading', 'is-refreshing');
                root.removeAttribute('aria-busy');
                refresh.disabled = false;
            }
        }
    }
    function fromControls() {
        return {...desired, days: days.value, state: state.value, q: search.value.trim().slice(0, 80), page: '1'};
    }
    periodForm.addEventListener('submit', event => {event.preventDefault();load(fromControls(), {refreshSummary: true});});
    days.addEventListener('change', () => load(fromControls(), {refreshSummary: true}));
    filterForm.addEventListener('submit', event => {event.preventDefault();load(fromControls());});
    state.addEventListener('change', () => load(fromControls()));
    search.addEventListener('input', () => {
        cancelPending(); // An earlier response must never overwrite newly typed text.
        clear.hidden = !search.value;
        desired = fromControls();
        debounce = setTimeout(() => load(desired), 280);
    });
    search.addEventListener('search', () => {if (!search.value) load(fromControls());});
    clear.addEventListener('click', () => {search.value = '';search.focus();load(fromControls());});
    root.addEventListener('change', event => {
        if (event.target.matches('[data-list-size]')) load({...fromControls(), per_page: event.target.value});
    });
    root.addEventListener('click', event => {
        const link = event.target.closest('[data-list-page]');
        if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0) {
            event.preventDefault();
            load({...fromControls(), page: new URL(link.href).searchParams.get('page') || '1'});
        }
        if (event.target.closest('[data-list-reset]')) {search.value = '';state.value = '';load(fromControls());}
        if (event.target.closest('[data-health-retry]') && lastAttempt) load(lastAttempt.filters, lastAttempt);
    });
    window.addEventListener('popstate', () => {const filters = readURL(new URL(location.href));sync(filters);load(filters, {historyMode: 'none', refreshSummary: true});});
    window.addEventListener('pagehide', () => {disposed = true;cancelPending();});
    window.addEventListener('pageshow', () => {disposed = false;});
    selects?.enhance();
})();
