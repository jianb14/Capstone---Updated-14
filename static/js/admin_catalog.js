/* Catalog tables and dialogs share one document. Validation never opens native bubbles. */
(() => {
    'use strict';
    const root = document.querySelector('[data-catalog-root]');
    if (!root) return;
    const workspace = root.querySelector('[data-catalog-workspace]');
    const dialog = root.querySelector('[data-catalog-dialog]'), content = root.querySelector('[data-catalog-content]');
    const dialogFooter = dialog.querySelector('.ac-dialog-footer');
    const defaultFooter = dialogFooter.innerHTML;
    const dialogFeedback = root.querySelector('[data-dialog-feedback]'), confirmation = root.querySelector('[data-delete-dialog]');
    const imageDialog = root.querySelector('[data-catalog-image]');
    const selects = window.AdminSelects.create(root);
    let listRequest, modalRequest, listVersion = 0, modalVersion = 0, timer, saving = false;
    let editorCleanup, uploadCleanup, origin, deleteState, appliedURL = new URL(location.href);
    let size = workspace.querySelector('[data-list-size]')?.value || appliedURL.searchParams.get('per_page') || '8';
    const feedback = (node, message = '') => {node.textContent = message;};
    const toast = (message, kind = 'success') => window.AdminConfigurationFeedback?.show(message, kind);
    async function request(url, options = {}) {
        const controller = new AbortController(), abort = () => controller.abort();
        options.signal?.addEventListener('abort', abort, {once:true});
        if (options.signal?.aborted) abort();
        const timeout = setTimeout(abort, 30000);
        try {
        const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options, signal:controller.signal,
            headers:{Accept:'application/json', 'X-Requested-With':'XMLHttpRequest', ...options.headers}});
        if (response.redirected) throw new Error('Your session ended. Please sign in again.');
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.message || 'This action could not be completed. Please try again.');
            error.fields = data.errors; throw error;
        }
        return data;
        } catch (error) {
            if (controller.signal.aborted && !options.signal?.aborted) throw new Error('The request took too long. Check the latest list before trying again.');
            throw error;
        } finally {clearTimeout(timeout); options.signal?.removeEventListener('abort', abort);}
    }
    function filtersURL(keepPage = false) {
        const form = workspace.querySelector('[data-catalog-filters]');
        const url = new URL(root.dataset.listUrl, location.origin);
        for (const [key, value] of new FormData(form)) if (value) url.searchParams.set(key, String(value).trim());
        url.searchParams.set('per_page', size);
        url.searchParams.set('page', keepPage ? appliedURL.searchParams.get('page') || '1' : '1');
        return url;
    }
    function invalidateList() {
        clearTimeout(timer); listRequest?.abort(); ++listVersion;
        workspace.classList.remove('is-loading'); workspace.removeAttribute('aria-busy');
    }
    async function load(url, push = true) {
        invalidateList(); selects.close();
        const controller = listRequest = new AbortController(), version = ++listVersion;
        const notice = workspace.querySelector('[data-list-feedback]'); feedback(notice);
        workspace.classList.add('is-loading'); workspace.setAttribute('aria-busy', 'true');
        try {
            const data = await request(url, {signal:controller.signal});
            if (version !== listVersion) return;
            const focus = workspace.contains(document.activeElement) ? document.activeElement : null;
            const focusName = focus?.name, start = focus?.selectionStart, end = focus?.selectionEnd;
            const position = scrollY;
            selects.release(workspace); workspace.innerHTML = data.html; selects.enhance();
            workspace.classList.remove('catalog-enter'); void workspace.offsetWidth; workspace.classList.add('catalog-enter');
            const actual = new URL(url, location.href); actual.searchParams.set('page', data.page);
            appliedURL = actual; size = workspace.querySelector('[data-list-size]')?.value || size;
            if (push) history.pushState({}, '', actual); else history.replaceState({}, '', actual);
            if (focusName) {
                const next = workspace.querySelector(`[name="${CSS.escape(focusName)}"]`);
                if (next && !next.hidden) {next.focus({preventScroll:true}); if (next.type === 'search') next.setSelectionRange(start, end);}
            }
            if (scrollY !== position) scrollTo({top:position, behavior:'instant'});
        } catch (error) {
            if (!controller.signal.aborted && version === listVersion) feedback(notice, error.message);
        } finally {
            if (version === listVersion) {workspace.classList.remove('is-loading'); workspace.removeAttribute('aria-busy');}
        }
    }
    function selection() {return [...workspace.querySelectorAll('[data-row-select]:checked:not(:disabled)')];}
    function syncSelection() {
        const eligible = [...workspace.querySelectorAll('[data-row-select]:not(:disabled)')], checked = selection();
        const all = workspace.querySelector('[data-select-all]');
        if (all) {all.checked = !!eligible.length && checked.length === eligible.length; all.indeterminate = checked.length > 0 && checked.length < eligible.length; all.disabled = !eligible.length;}
        workspace.querySelector('[data-bulk-bar]').hidden = !checked.length;
        workspace.querySelector('[data-selected-count]').textContent = checked.length;
    }
    function setBusy(value) {
        saving = value; dialog.setAttribute('aria-busy', String(value));
        root.querySelectorAll('[data-catalog-close], [data-delete-cancel], [data-delete-confirm]').forEach(button => button.disabled = value);
        content.querySelectorAll('[data-catalog-form] button').forEach(button => button.disabled = value);
        dialogFooter.querySelectorAll('button[type=submit]').forEach(button => button.disabled = value);
    }
    function disposeContent() {editorCleanup?.(); uploadCleanup?.(); editorCleanup = uploadCleanup = null; selects.release(content);}
    function resetFooter() {
        dialogFooter.innerHTML = defaultFooter;
        dialogFooter.classList.remove('catalog-form-footer');
    }
    function closeDialog() {
        if (saving) return;
        modalRequest?.abort(); ++modalVersion; dialog.close();
    }
    dialog.addEventListener('close', () => {
        if (dialog.open) return;
        disposeContent(); content.replaceChildren(); resetFooter();
        if (!confirmation.open) document.body.classList.remove('ac-modal-open');
        if (origin?.isConnected) origin.focus({preventScroll:true});
    });
    dialog.addEventListener('cancel', event => {if (saving) event.preventDefault();});
    dialog.addEventListener('click', event => {if (event.target === dialog) {const b = dialog.getBoundingClientRect(); if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) closeDialog();}});
    async function openDialog(url, button) {
        if (saving) return;
        origin = button || origin; modalRequest?.abort();
        const controller = modalRequest = new AbortController(), version = ++modalVersion;
        disposeContent(); content.replaceChildren(); resetFooter(); dialog.classList.remove('is-offer','has-form'); dialogFooter.hidden = false;
        dialogFeedback.dataset.loading = 'true'; feedback(dialogFeedback, 'Loading...'); root.querySelector('#catalogDialogTitle').textContent = 'Details';
        if (!dialog.open) dialog.showModal();
        document.body.classList.add('ac-modal-open');
        try {
            const data = await request(url, {signal:controller.signal});
            if (version !== modalVersion || !dialog.open) return;
            if (!data.html) throw new Error('The server returned an incomplete response. Please try again.');
            content.innerHTML = data.html; root.querySelector('#catalogDialogTitle').textContent = data.title;
            if (data.footer_html) {
                dialogFooter.innerHTML = data.footer_html;
                dialogFooter.classList.add('catalog-form-footer');
            }
            dialogFooter.hidden = !!content.querySelector('form') && !data.footer_html;
            dialog.classList.toggle('has-form', !!content.querySelector('form'));
            dialog.classList.toggle('is-offer', !!data.offer_editor); feedback(dialogFeedback);
            selects.enhance();
            if (data.offer_editor) editorCleanup = window.initOfferEditor(content);
            else uploadCleanup = initializeUpload();
            root.querySelector('[data-catalog-body]').scrollTop = 0;
            content.querySelector('input:not([type=hidden],[type=checkbox],[type=file]),textarea')?.focus({preventScroll:true});
        } catch (error) {if (!controller.signal.aborted) feedback(dialogFeedback, error.message);}
        finally {if (version === modalVersion) delete dialogFeedback.dataset.loading;}
    }
    function fieldError(form, name, message = '') {
        const group = form.querySelector(`[data-field="${CSS.escape(name)}"]`);
        if (!group) return;
        const node = group.querySelector('[data-error-for]');
        node.textContent = message; node.hidden = !message;
        group.querySelectorAll('input,textarea,select').forEach(input => {
            if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
        });
        group.querySelector('.ac-select-trigger')?.setAttribute('aria-invalid', String(!!message));
    }
    function validateField(form, group) {
        const controls = [...group.querySelectorAll('input,textarea,select')], input = controls[0];
        if (!input) return true;
        const name = group.dataset.field, required = group.dataset.required === 'true';
        const label = group.querySelector('label')?.textContent.replace('*', '').trim() || 'This field';
        const value = input.type === 'checkbox' ? controls.some(control => control.checked) : input.type === 'file' ? input.files.length : input.value.trim();
        let message = required && !value ? (name === 'available_for' ? 'Select at least one design type.' : name === 'images' ? 'Choose at least one image.' : `${label} is required.`) : '';
        if (!message && input.validity.rangeUnderflow) message = `Enter ${input.min} or more.`;
        if (!message && input.validity.rangeOverflow) message = `Enter ${input.max} or less.`;
        if (!message && (input.validity.badInput || input.validity.stepMismatch)) message = 'Enter a valid whole number.';
        if (!message && input.maxLength > 0 && input.value.length > input.maxLength) message = `Use ${input.maxLength} characters or fewer.`;
        fieldError(form, name, message); return !message;
    }
    function focusError(form) {
        const group = form.querySelector('[aria-invalid=true]')?.closest('[data-field]');
        (group?.querySelector('.ac-select-trigger,[data-upload-browse]') || group?.querySelector('input,textarea,select'))?.focus();
    }
    function initializeUpload() {
        const zone = content.querySelector('[data-upload-zone]');
        if (!zone) return;
        const form = zone.closest('form'), input = zone.querySelector('input[type=file]'), previews = content.querySelector('[data-upload-previews]');
        const limit = Number(zone.dataset.limit); let files = [], urls = [];
        function refresh() {
            urls.forEach(url => URL.revokeObjectURL(url)); urls = [];
            const transfer = new DataTransfer(); files.forEach(file => transfer.items.add(file)); input.files = transfer.files;
            previews.replaceChildren();
            files.forEach((file, index) => {
                const figure = document.createElement('figure'), img = document.createElement('img'), button = document.createElement('button');
                const url = URL.createObjectURL(file); urls.push(url); img.src = url; img.alt = file.name;
                button.type = 'button'; button.setAttribute('aria-label', `Remove selected image ${index + 1}`);
                button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
                button.addEventListener('click', () => {files.splice(index, 1); refresh(); fieldError(form, input.name);});
                figure.append(img, button); previews.append(figure);
            });
        }
        function add(incoming) {
            const added = [...incoming], next = limit === 1 ? added : [...files, ...added];
            const error = next.length > limit ? `Choose up to ${limit} image${limit === 1 ? '' : 's'} at a time.` :
                added.some(file => !file.type.startsWith('image/')) ? 'Choose image files only.' :
                added.some(file => file.size > 10 * 1024 * 1024) ? 'Choose images smaller than 10 MB each.' : '';
            if (!error) files = next;
            refresh(); fieldError(form, input.name, error);
        }
        zone.querySelector('[data-upload-browse]').addEventListener('click', () => input.click());
        input.addEventListener('change', () => add(input.files));
        zone.addEventListener('dragover', event => {event.preventDefault(); zone.classList.add('is-dragover');});
        zone.addEventListener('dragleave', event => {if (!zone.contains(event.relatedTarget)) zone.classList.remove('is-dragover');});
        zone.addEventListener('drop', event => {event.preventDefault(); zone.classList.remove('is-dragover'); add(event.dataTransfer.files);});
        return () => urls.forEach(url => URL.revokeObjectURL(url));
    }
    async function saveForm(form) {
        if (saving) return;
        feedback(form.querySelector('[data-form-feedback]'));
        const valid = [...form.querySelectorAll('[data-field]')].map(group => validateField(form, group)).every(Boolean);
        if (!valid) {focusError(form); return;}
        const body = new FormData(form); setBusy(true);
        try {
            const data = await request(form.action, {method:'POST', body});
            if (!data.success) throw new Error(data.message || 'The changes could not be confirmed. Check the latest item before trying again.');
            setBusy(false); closeDialog(); toast(data.message || 'Changes saved.'); await load(filtersURL(true), false);
        } catch (error) {
            if (error.fields) {
                for (const [name, messages] of Object.entries(error.fields)) {
                    if (name === '__all__') feedback(form.querySelector('[data-form-feedback]'), messages.join(' '));
                    else fieldError(form, name, messages.join(' '));
                }
                focusError(form);
            } else {
                feedback(form.querySelector('[data-form-feedback]'), error.message);
                toast(error.message, 'error');
            }
        } finally {setBusy(false);}
    }
    function confirmDelete(url, ids, name) {
        if (saving) return;
        const notify = confirmation.querySelector('[data-delete-notify]');
        if (notify) notify.checked = false;
        deleteState = {url, ids};
        root.querySelector('#catalogDeleteTitle').textContent = name ? 'Delete this item?' : 'Delete selected items?';
        root.querySelector('[data-delete-description]').textContent = name ? `Delete “${name}”?` : `Delete the ${ids.length} selected item(s)?`;
        feedback(root.querySelector('[data-delete-feedback]')); confirmation.showModal();
        document.body.classList.add('ac-modal-open');
        confirmation.querySelector('[data-delete-cancel]').focus();
    }
    root.addEventListener('input', event => {
        if (event.target.matches('[data-catalog-filters] [name=q]')) {
            workspace.querySelector('[data-search-clear]').hidden = !event.target.value;
            invalidateList(); timer = setTimeout(() => load(filtersURL()), 280);
        }
        const form = event.target.closest('[data-catalog-form]'), group = event.target.closest('[data-field]');
        if (form && group && event.target.type !== 'file' && group.querySelector('[aria-invalid=true]')) validateField(form, group);
    });
    root.addEventListener('change', event => {
        if (event.target.matches('[data-list-size]')) {size = event.target.value; load(filtersURL());}
        else if (event.target.closest('[data-catalog-filters]') && event.target.matches('select')) {
            if (event.target.name === 'kind' && event.target.form.elements.category) event.target.form.elements.category.value = '';
            load(filtersURL());
        }
        else if (event.target.matches('[data-select-all]')) {workspace.querySelectorAll('[data-row-select]:not(:disabled)').forEach(input => input.checked = event.target.checked); syncSelection();}
        else if (event.target.matches('[data-row-select]')) syncSelection();
        const form = event.target.closest('[data-catalog-form]');
        if (form && event.target.matches('select,input[type=checkbox]')) validateField(form, event.target.closest('[data-field]'));
    });
    root.addEventListener('submit', event => {
        const form = event.target;
        if (form.matches('[data-catalog-filters]')) {event.preventDefault(); load(filtersURL());}
        if (form.matches('[data-catalog-form]')) {event.preventDefault(); saveForm(form);}
    });
    root.addEventListener('click', async event => {
        const target = event.target.closest('button,a'); if (!target) return;
        if (saving) {event.preventDefault(); return;}
        if (target.matches('[data-catalog-open]')) {event.preventDefault(); openDialog(target.dataset.catalogOpen, target);}
        else if (target.matches('[data-photo-url]')) {imageDialog.querySelector('img').src = target.dataset.photoUrl; imageDialog.showModal();}
        else if (target.matches('[data-image-close]')) imageDialog.close();
        else if (target.matches('[data-catalog-close]')) closeDialog();
        else if (target.matches('[data-search-clear]')) {
            const search = workspace.querySelector('[name=q]'); search.value = ''; target.hidden = true; search.focus(); load(filtersURL());
        } else if (target.matches('[data-catalog-tab],[data-list-page]') && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault(); const url = target.matches('[data-catalog-tab]') ? new URL(target.href) : filtersURL(true);
            url.searchParams.set('per_page', size);
            if (target.matches('[data-list-page]')) url.searchParams.set('page', new URL(target.href).searchParams.get('page'));
            load(url);
        } else if (target.matches('[data-list-reset]')) {
            const form = workspace.querySelector('[data-catalog-filters]'); ['q','status','category'].forEach(key => {if (form.elements[key]) form.elements[key].value = '';}); load(filtersURL());
        } else if (target.matches('[data-clear-selection]')) {selection().forEach(input => input.checked = false); syncSelection();}
        else if (target.matches('[data-bulk-delete]')) confirmDelete(workspace.querySelector('[data-bulk-url]').dataset.bulkUrl, selection().map(input => input.value));
        else if (target.matches('[data-delete-url]')) confirmDelete(target.dataset.deleteUrl, [], target.dataset.itemName);
        else if (target.matches('[data-delete-cancel]')) confirmation.close();
        else if (target.matches('[data-delete-confirm]')) {
            const body = new FormData(); deleteState.ids.forEach(id => body.append('ids', id));
            if (confirmation.querySelector('[data-delete-notify]')?.checked) body.set('notify_clients', 'on');
            body.set('csrfmiddlewaretoken', root.querySelector('[name=csrfmiddlewaretoken]')?.value || getCookie('csrftoken'));
            setBusy(true);
            try {
                const data = await request(deleteState.url, {method:'POST', body});
                if (!data.success) throw new Error(data.message || 'The deletion could not be confirmed. Check the latest list before trying again.');
                confirmation.close(); toast(data.message); await load(filtersURL(true), false);
            } catch (error) {feedback(root.querySelector('[data-delete-feedback]'), error.message); toast(error.message, 'error');}
            finally {setBusy(false);}
        }
    });
    function getCookie(name) {return document.cookie.split('; ').find(value => value.startsWith(name + '='))?.slice(name.length + 1) || '';}
    confirmation.addEventListener('cancel', event => {if (saving) event.preventDefault();});
    imageDialog.addEventListener('click', event => {if (event.target === imageDialog) imageDialog.close();});
    imageDialog.addEventListener('close', () => imageDialog.querySelector('img').removeAttribute('src'));
    confirmation.addEventListener('close', () => {if (!dialog.open) document.body.classList.remove('ac-modal-open');});
    root.addEventListener('catalog:busy', event => setBusy(event.detail));
    root.addEventListener('catalog:saved', async event => {setBusy(false); closeDialog(); toast(event.detail.message || 'Offer saved.'); await load(filtersURL(true), false);});
    root.addEventListener('catalog:failed', event => toast(event.detail.message, 'error'));
    window.addEventListener('popstate', () => {if (!saving) {closeDialog(); size = new URL(location.href).searchParams.get('per_page') || '8'; load(new URL(location.href), false);}});
    selects.enhance(); syncSelection();
})();
