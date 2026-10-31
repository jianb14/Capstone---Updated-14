/* Design library controls share the admin selectors and compact account footer. */
(() => {
    'use strict';
    const root = document.querySelector('.design-library-workspace');
    if (!root) return;
    const filter = document.getElementById('designsFilterForm');
    const search = filter.querySelector('[name="q"]');
    const clear = document.getElementById('designSearchClear');
    const selects = window.AdminSelects.create(root);
    selects.enhance();
    let results = document.getElementById('designLibraryResults');
    const status = document.getElementById('designSearchStatus');
    let searchTimer, searchRequest, searchVersion = 0;
    function filterURL() {
        const url = new URL(filter.action);
        for (const [key,value] of new FormData(filter)) if (value) url.searchParams.set(key,value);
        return url;
    }
    function cancelSearch() {
        clearTimeout(searchTimer); searchRequest?.abort(); searchVersion++;
        results.removeAttribute('aria-busy');
    }
    async function refresh(url, {pop = false} = {}) {
        cancelSearch();
        const version = searchVersion, controller = new AbortController();
        searchRequest = controller;
        results.setAttribute('aria-busy','true'); status.hidden = true;
        try {
            const response = await fetch(url, {credentials:'same-origin', signal:controller.signal,
                headers:{Accept:'text/html','X-Requested-With':'XMLHttpRequest'}});
            if (response.redirected && new URL(response.url).pathname !== location.pathname) {
                location.assign(response.url); return;
            }
            if (!response.ok) throw new Error('Search is unavailable. Please try again.');
            const doc = new DOMParser().parseFromString(await response.text(),'text/html');
            const next = doc.getElementById('designLibraryResults');
            if (!next) throw new Error('Search is unavailable. Please try again.');
            if (version !== searchVersion) return;
            closeMenus(); selects.release(results); results.replaceWith(next); results = next;
            prepareMenus(); selects.enhance();
            if (!pop) history.pushState({},'',url);
            status.replaceChildren();
            status.hidden = true;
        } catch (error) {
            if (error.name === 'AbortError' || version !== searchVersion) return;
            status.replaceChildren(document.createTextNode('Could not update designs. Your previous results are still here. '));
            const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Try again';
            retry.addEventListener('click', () => refresh(url)); status.append(retry); status.hidden = false;
        } finally { if (version === searchVersion) results.removeAttribute('aria-busy'); }
    }
    search.addEventListener('input', () => {
        clear.hidden = !search.value; cancelSearch();
        if (!search.matches(':focus')) search.focus({preventScroll:true});
        searchTimer = setTimeout(() => refresh(filterURL()), 250);
    });
    function clearSearch() { search.value = ''; clear.hidden = true; search.focus(); refresh(filterURL()); }
    clear.addEventListener('click', clearSearch);
    filter.addEventListener('submit', event => { event.preventDefault(); refresh(filterURL()); });
    document.getElementById('sort-filter').addEventListener('change', () => refresh(filterURL()));
    root.addEventListener('change', event => {
        if (!event.target.matches('[data-list-size]')) return;
        document.getElementById('designPageSize').value = event.target.value;
        refresh(filterURL());
    });
    root.addEventListener('click', event => {
        if (event.target.closest('[data-clear-design-search]')) clearSearch();
        const link = event.target.closest('[data-list-page]');
        if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); refresh(link.href);
    });
    window.addEventListener('popstate', () => {
        const params = new URL(location.href).searchParams;
        search.value = params.get('q') || ''; clear.hidden = !search.value;
        document.getElementById('sort-filter').value = params.get('sort') || 'newest';
        document.getElementById('designPageSize').value = params.get('per_page') === '4' ? '4' : '8';
        selects.sync(); refresh(location.href, {pop:true});
    });

    let activeMenu, menuTrigger, menuAnchor;
    const popovers = typeof HTMLElement.prototype.showPopover === 'function';
    function prepareMenus() {
        root.querySelectorAll('.design-dropdown-menu').forEach(menu => {
            if (popovers) menu.setAttribute('popover', 'manual');
        });
    }
    prepareMenus();
    function closeMenus(returnFocus = false) {
        if (!activeMenu) return;
        if (popovers && activeMenu.matches(':popover-open')) activeMenu.hidePopover();
        activeMenu.classList.remove('show'); activeMenu.hidden = true;
        menuTrigger.setAttribute('aria-expanded', 'false');
        if (returnFocus) menuTrigger.focus({preventScroll:true});
        activeMenu = null; menuTrigger = null;
    }
    function toggleMenu(id, event) {
        event.preventDefault(); event.stopPropagation();
        const menu = document.getElementById(id), wasOpen = activeMenu === menu;
        closeMenus(); selects.close();
        if (wasOpen) return;
        activeMenu = menu; menuTrigger = root.querySelector('[aria-controls="' + id + '"]');
        menu.hidden = false; menu.classList.add('show');
        menuTrigger.setAttribute('aria-expanded', 'true');
        if (popovers) menu.showPopover();
        const anchor = menuTrigger.getBoundingClientRect(), box = menu.getBoundingClientRect();
        menuAnchor = anchor;
        menu.style.left = Math.max(8, Math.min(anchor.right - box.width, innerWidth - box.width - 8)) + 'px';
        menu.style.top = Math.max(8, Math.min(anchor.bottom + 6, innerHeight - box.height - 8)) + 'px';
        menu.querySelector('[role="menuitem"]')?.focus({preventScroll:true});
    }
    document.addEventListener('click', event => {
        if (!event.target.closest('.design-menu-wrapper')) closeMenus();
        else if (event.target.closest('.design-dropdown-menu [download]')) closeMenus(true);
    });
    root.addEventListener('keydown', event => {
        const dots = event.target.closest('.menu-dots-btn');
        if (dots && ['ArrowDown','ArrowUp'].includes(event.key)) {
            toggleMenu(dots.getAttribute('aria-controls'), event);
            if (event.key === 'ArrowUp') activeMenu?.querySelector('[role="menuitem"]:last-child')?.focus();
            return;
        }
        const menu = event.target.closest('.design-dropdown-menu');
        if (!menu) return;
        const items = [...menu.querySelectorAll('[role="menuitem"]')], index = items.indexOf(document.activeElement);
        if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
            event.preventDefault();
            items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
        } else if (event.key === 'Escape') { event.preventDefault(); closeMenus(true); }
        else if (event.key === 'Tab') closeMenus(true);
        else if (event.key === ' ' && event.target.matches('a[role="menuitem"]')) { event.preventDefault(); event.target.click(); }
    });
    window.addEventListener('resize', () => closeMenus());
    document.addEventListener('scroll', event => {
        if (!activeMenu || activeMenu.contains(event.target)) return;
        const anchor = menuTrigger.getBoundingClientRect();
        if (Math.abs(anchor.top - menuAnchor.top) > .5 || Math.abs(anchor.left - menuAnchor.left) > .5) closeMenus();
    }, {capture:true, passive:true});

    const openers = new Map();
    let currentDesignId, renaming = false;
    const rename = document.getElementById('renameModal');
    const form = document.getElementById('renameDesignForm');
    const name = document.getElementById('renameInput');
    const nameError = document.getElementById('renameNameError');
    const requestError = document.getElementById('renameRequestError');
    const save = document.getElementById('renameSave');
    const csrf = () => form.querySelector('[name="csrfmiddlewaretoken"]').value;
    function openModal(id) {
        const modal = document.getElementById(id);
        closeMenus(true); selects.close();
        openers.set(id, document.activeElement);
        modal.classList.add('show'); document.documentElement.classList.add('design-modal-open');
        (modal.querySelector('input:not([type="hidden"]), button, [tabindex]') || modal).focus({preventScroll:true});
    }
    function closeModal(id, force = false) {
        if (id === 'renameModal' && renaming && !force) return;
        const modal = document.getElementById(id);
        modal.querySelector('dialog[open]')?.close(); modal.classList.remove('show');
        if (!document.querySelector('.modal-overlay.show, .dl-offer-dialog[open]')) document.documentElement.classList.remove('design-modal-open');
        openers.get(id)?.focus({preventScroll:true});
    }
    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.addEventListener('click', event => { if (event.target === modal) closeModal(modal.id); });
        modal.addEventListener('keydown', event => {
            if (modal.querySelector('dialog[open]') || event.target.closest('.client-feedback-dialog')) return;
            if (event.key === 'Escape') { event.preventDefault(); closeModal(modal.id); }
            if (event.key !== 'Tab') return;
            const targets = [...modal.querySelectorAll('a[href],button,input,[tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
            const first = targets[0], last = targets.at(-1);
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        });
    });
    function validateName() {
        const text = name.value.trim() ? '' : 'Please enter a design name.';
        nameError.textContent = text; nameError.hidden = !text;
        name.setAttribute('aria-invalid', String(!!text));
        return !text;
    }
    function openRenameModal(id) {
        currentDesignId = id;
        name.value = document.getElementById('title-' + id).textContent.trim();
        name.removeAttribute('aria-invalid'); nameError.hidden = true; requestError.hidden = true;
        openModal('renameModal'); name.focus({preventScroll:true}); name.select();
    }
    name.addEventListener('input', () => { validateName(); requestError.hidden = true; });
    async function submitRename(event) {
        event?.preventDefault();
        if (renaming || !currentDesignId) return;
        if (!validateName()) { name.focus(); return; }
        renaming = true; form.setAttribute('aria-busy','true'); requestError.hidden = true;
        const newName = name.value.trim(), id = currentDesignId;
        rename.querySelectorAll('button,input:not([type="hidden"])').forEach(control => control.disabled = true);
        save.textContent = 'Saving…';
        try {
            const response = await fetch('/my-designs/rename/' + id + '/', {
                method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf()}, body:JSON.stringify({name:newName})
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Could not rename this design. Please try again.');
            document.getElementById('title-' + id).textContent = data.name;
            root.querySelector('[aria-controls="menu-' + id + '"]').setAttribute('aria-label','Design options for ' + data.name);
            const download = document.getElementById('menu-' + id).querySelector('[download]');
            if (download) download.download = data.name + '.png';
            closeModal('renameModal', true);
            AppToast.fire({icon:'success',title:'Design renamed successfully.'});
        } catch (error) {
            requestError.textContent = error.message || 'Could not rename this design. Please try again.';
            requestError.hidden = false; AppToast.fire({icon:'error',title:requestError.textContent});
        } finally {
            renaming = false; form.setAttribute('aria-busy','false'); save.textContent = 'Save Name';
            rename.querySelectorAll('button,input:not([type="hidden"])').forEach(control => control.disabled = false);
        }
    }
    form.addEventListener('submit', submitRename);
    const deleting = new Set();
    async function openDeleteModal(id) {
        if (deleting.has(id)) return;
        deleting.add(id); closeMenus(true);
        try {
            const result = await AppToast.confirm({title:'Delete this design?',text:'This action cannot be undone.',danger:true,confirmText:'Delete design'});
            if (!result.isConfirmed) return;
            const response = await fetch('/my-designs/delete/' + id + '/', {method:'POST',headers:{'X-CSRFToken':csrf()}});
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Could not delete this design. Please try again.');
            AppToast.onNextPage({icon:'success',title:data.message || 'Design deleted successfully.'}); location.reload();
        } catch (error) { AppToast.fire({icon:'error',title:error.message || 'Could not delete this design. Please try again.'}); }
        finally { deleting.delete(id); }
    }
    Object.assign(window, {toggleMenu,openModal,closeModal,openRenameModal,submitRename,openDeleteModal});
})();
