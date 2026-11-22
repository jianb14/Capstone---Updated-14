/* Personal image libraries; placements and offer evaluation stay in the canvas. */
(function (root) {
    const libraryIds = new Set();
    let options = null;
    let pending = 0;
    let selection = [];
    const registry = () => root.canvasUploadsPayload || (root.canvasUploadsPayload = {});
    const categoryRule = id => options?.getOffer()?.requirements.find(rule => Number(rule.category_id) === Number(id));
    const names = {'#ffffff': 'White', '#000000': 'Black', '#ff0000': 'Red', '#e74c3c': 'Red', '#0000ff': 'Blue', '#3498db': 'Blue', '#00ff00': 'Green', '#2ecc71': 'Green', '#ffff00': 'Yellow', '#f1c40f': 'Yellow', '#e91e63': 'Pink', '#e91e8c': 'Pink', '#9b59b6': 'Purple', '#e67e22': 'Orange', '#1abc9c': 'Teal'};
    const colorName = value => names[String(value).toLowerCase()] || String(value).toUpperCase();

    function renderColors(container, colors, showNames = false) {
        container.replaceChildren();
        if (!colors?.length) { if (showNames) container.textContent = 'Colors not set'; return; }
        colors.forEach(color => {
            const label = document.createElement('span');
            label.className = 'upload-color-label';
            label.title = `${colorName(color)} (${color.toUpperCase()})`;
            label.dataset.color = color;
            label.setAttribute('role', 'img');
            label.setAttribute('aria-label', label.title);
            const dot = document.createElement('span');
            dot.className = 'upload-color-dot';
            dot.style.backgroundColor = color;
            dot.setAttribute('aria-hidden', 'true');
            label.append(dot);
            if (showNames) label.append(document.createTextNode(colorName(color)));
            container.append(label);
        });
    }

    function syncSelection(objects = []) {
        selection = objects;
        if (!options) return;
        const panel = document.getElementById('selectedUploadColors');
        const obj = objects.length === 1 ? objects[0] : null;
        const upload = obj?._designSource === 'upload' ? registry()[String(obj._uploadId)] : null;
        const balloon = upload && (categoryRule(upload.category_id)?.is_balloon || upload.colors?.length);
        panel.hidden = !balloon;
        document.getElementById('selectionToolbar').classList.toggle('has-upload-colors', !!balloon);
        if (!balloon) return;
        renderColors(panel.querySelector('.upload-color-labels'), upload.colors, true);
        const edit = panel.querySelector('button');
        edit.disabled = !!obj._isLocked || pending > 0;
        edit.onclick = () => editColors(upload, edit);
    }

    function canonicalizeSources(state, uploads, origin) {
        const stack = [...state.objects];
        while (stack.length) {
            const obj = stack.pop();
            if (!obj || typeof obj !== 'object') continue;
            if (Array.isArray(obj.objects)) stack.push(...obj.objects);
            const upload = uploads[String(obj._uploadId)];
            if (!upload || !obj.src) continue;
            try {
                const actual = new URL(obj.src, origin), expected = new URL(upload.src, origin);
                if (actual.origin === origin && actual.href === expected.href) obj.src = upload.src;
            } catch (error) { /* The server reports invalid upload sources. */ }
        }
    }

    function setError(control, message) {
        const error = control.querySelector('.category-upload-error');
        error.textContent = message || '';
        error.hidden = !message;
    }
    function render() {
        document.querySelectorAll('[data-upload-library]').forEach(grid => {
            grid.replaceChildren();
            for (const id of libraryIds) {
                const upload = registry()[id];
                if (!upload || Number(upload.category_id) !== Number(grid.dataset.uploadLibrary)) continue;
                const wrapper = document.createElement('div');
                wrapper.className = 'category-upload-card';
                const item = document.createElement('div');
                item.className = 'draggable-item';
                item.draggable = true;
                Object.assign(item.dataset, {
                    type: 'image', designSource: 'upload', uploadId: String(upload.id), uploadToken: upload.token,
                    categoryId: String(upload.category_id), category: upload.category, src: upload.src,
                    width: '180', height: '180'
                });
                item.title = upload.label;
                item.setAttribute('aria-disabled', categoryRule(upload.category_id) ? 'false' : 'true');
                const preview = document.createElement('div');
                preview.className = 'item-preview-img-wrapper';
                const img = document.createElement('img');
                img.className = 'item-preview-img';
                img.src = upload.src;
                img.alt = upload.label;
                img.loading = 'lazy';
                preview.appendChild(img);
                const label = document.createElement('span');
                label.className = 'item-label';
                label.textContent = upload.label;
                item.append(preview, label);
                options.bindItem(item);
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'upload-library-remove';
                const close = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                close.setAttribute('viewBox', '0 0 24 24');
                close.setAttribute('aria-hidden', 'true');
                const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
                use.setAttribute('href', '#ci-close');
                close.append(use); remove.append(close);
                remove.setAttribute('aria-label', `Remove ${upload.label} from uploads`);
                remove.addEventListener('click', async () => {
                    if (pending) return;
                    pending++; updateOffer();
                    let removed = false;
                    const control = document.querySelector(`[data-category-upload="${upload.category_id}"]`);
                    try {
                        const response = await fetch(`${options.uploadUrl}${id}/remove/`, {method: 'POST', headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''}});
                        const result = await response.json().catch(() => ({}));
                        if (!response.ok || Number(result.removed) !== Number(id)) throw new Error('Unable to remove this upload. Please try again.');
                        registry()[id].in_library = false;
                        libraryIds.delete(String(id));
                        render();
                        options.changed();
                        removed = true;
                    } catch (error) { if (control) setError(control, error.message); }
                    finally {
                        pending--; updateOffer();
                        if (removed) control?.querySelector('[data-browse-category]')?.focus();
                        else remove.focus();
                    }
                });
                wrapper.append(item, remove);
                if (categoryRule(upload.category_id)?.is_balloon || upload.colors?.length) {
                    const colors = document.createElement('div');
                    colors.className = 'upload-color-labels';
                    colors.setAttribute('aria-label', 'Balloon colors');
                    renderColors(colors, upload.colors);
                    const edit = document.createElement('button');
                    edit.type = 'button';
                    edit.className = 'upload-colors-edit';
                    edit.textContent = 'Edit colors';
                    edit.addEventListener('click', () => editColors(upload, edit));
                    wrapper.append(colors, edit);
                }
                grid.appendChild(wrapper);
            }
            const heading = grid.parentElement.querySelector('.custom-uploads-heading');
            if (heading) heading.hidden = !grid.children.length;
        });
    }
    function updateOffer() {
        document.querySelectorAll('[data-category-upload]').forEach(control => {
            const allowed = !!categoryRule(control.dataset.categoryUpload);
            control.querySelector('.category-not-included').hidden = allowed;
            control.querySelector('.category-upload-fields').hidden = !allowed;
            control.querySelectorAll('button, input').forEach(input => { input.disabled = !allowed || control.dataset.uploading === 'true'; });
        });
        document.querySelectorAll('.draggable-item[data-upload-id]').forEach(item => item.setAttribute('aria-disabled', categoryRule(item.dataset.categoryId) ? 'false' : 'true'));
        document.querySelectorAll('.category-upload-card .upload-colors-edit').forEach(button => {
            const item = button.parentElement.querySelector('[data-upload-id]');
            button.disabled = pending > 0 || !categoryRule(item.dataset.categoryId);
        });
        document.querySelectorAll('.upload-library-remove').forEach(button => { button.disabled = pending > 0; });
        syncSelection(selection);
    }
    function addColor(control, value, selected = false) {
        const normalized = value.toLowerCase();
        if (!/^#[0-9a-f]{6}$/.test(normalized)) return;
        const existing = [...control.querySelectorAll('.upload-color-option input')].find(input => input.value === normalized);
        if (existing) { if (selected) existing.checked = true; return; }
        const label = document.createElement('label');
        label.className = 'upload-color-option';
        label.title = normalized;
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = normalized;
        input.checked = selected;
        const isPalette = [...document.querySelectorAll('.color-swatch[data-target="object"]')].some(swatch => swatch.dataset.color.toLowerCase() === normalized);
        const caption = colorName(normalized) + (!isPalette && names[normalized] ? ` (${normalized.toUpperCase()})` : '');
        input.setAttribute('aria-label', caption);
        const swatch = document.createElement('span');
        swatch.style.backgroundColor = normalized;
        label.append(input, swatch, document.createTextNode(caption));
        control.querySelector('.upload-color-options').appendChild(label);
    }

    function colorDialog(src, label, colors, editing, save, preview = null) {
        const dialog = document.getElementById('balloonColorsDialog');
        const error = dialog.querySelector('[data-color-error]');
        const submit = dialog.querySelector('[data-save-colors]');
        const status = dialog.querySelector('[data-background-status]');
        const original = dialog.querySelector('[data-use-original]');
        const retry = dialog.querySelector('[data-remove-background]');
        const balloon = preview ? preview.rule.is_balloon : true;
        const saveLabel = balloon ? 'Save colors' : 'Use image';
        let saving = false, processing = false, ready = !preview;
        let selectedFile = preview?.file, processedUrl = null, controller = null, generation = 0;
        dialog.returnValue = '';
        dialog.querySelector('#balloonColorsTitle').textContent = balloon ? 'Balloon photo colors' : 'Upload image';
        dialog.querySelector('.balloon-colors-heading [data-color-cancel]').setAttribute('aria-label', balloon ? 'Close balloon colors' : 'Close image preview');
        dialog.querySelector('img').src = src;
        dialog.querySelector('img').alt = `${label} preview`;
        dialog.querySelector('[data-color-file]').textContent = label;
        dialog.querySelector('[data-color-edit-note]').hidden = !editing;
        dialog.querySelector('[data-background-controls]').hidden = !preview;
        dialog.querySelector('[data-balloon-color-fields]').hidden = !balloon;
        dialog.querySelector('#balloonColorsDescription').textContent = preview
            ? 'Review your image before adding it. You can keep the original if the cutout needs changes.'
            : 'Select the colors shown in this photo. Your photo keeps its original appearance.';
        dialog.querySelector('[data-color-limit]').hidden = !balloon;
        const limit = options.getOffer()?.max_balloon_colors;
        dialog.querySelector('[data-color-limit]').textContent = limit
            ? `Your package allows up to ${limit} balloon colors across the design. Colors count when the photo is placed.`
            : 'Colors are recorded for this photo and counted when it is placed.';
        dialog.querySelector('.upload-color-options').replaceChildren();
        if (balloon) {
            document.querySelectorAll('.color-swatch[data-target="object"]').forEach(swatch => addColor(dialog, swatch.dataset.color));
            colors.forEach(color => addColor(dialog, color, true));
        }
        error.textContent = ''; error.hidden = true;
        const syncBusy = () => {
            dialog.querySelectorAll('button, input').forEach(input => { input.disabled = saving; });
            retry.disabled = saving || processing;
            submit.disabled = saving || processing || !ready;
            dialog.setAttribute('aria-busy', String(saving || processing));
            submit.textContent = saving ? 'Saving?' : saveLabel;
        };
        const setOriginal = () => {
            generation++;
            controller?.abort();
            processing = false; ready = true;
            selectedFile = preview.file;
            dialog.querySelector('img').src = src;
            status.textContent = 'Original photo selected.';
            original.setAttribute('aria-pressed', 'true');
            syncBusy();
        };
        const processBackground = async () => {
            const version = ++generation;
            controller?.abort();
            const abort = new AbortController(); controller = abort;
            processing = true; ready = false;
            status.textContent = 'Removing background?';
            original.setAttribute('aria-pressed', 'false');
            syncBusy();
            const timeout = setTimeout(() => abort.abort(), 60000);
            try {
                const body = new FormData();
                body.append('image', preview.file);
                body.append('category_id', preview.rule.category_id);
                body.append('design_offer_id', preview.offer.id);
                const response = await fetch(`${options.uploadUrl}preview/`, {method:'POST',
                    headers:{'X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''}, body, signal:abort.signal});
                if (!response.ok || !response.headers.get('Content-Type')?.includes('image/png')) {
                    const result = await response.json().catch(() => ({}));
                    throw new Error(result.message || 'Unable to remove the background. Try again or use the original photo.');
                }
                const blob = await response.blob();
                if (version !== generation || !dialog.open) return;
                if (processedUrl) URL.revokeObjectURL(processedUrl);
                processedUrl = URL.createObjectURL(blob);
                selectedFile = new File([blob], preview.file.name.replace(/\.[^.]+$/, '') + '.png', {type:'image/png'});
                dialog.querySelector('img').src = processedUrl;
                ready = true;
                status.textContent = 'Background removed. Review the preview or use the original.';
            } catch (failure) {
                if (version !== generation || !dialog.open) return;
                status.textContent = failure.name === 'AbortError'
                    ? 'Processing took too long. Try again or use the original photo.'
                    : (root.AppErrors?.text(failure.message, 'Unable to remove the background. Try again or use the original photo.') || failure.message);
            } finally {
                clearTimeout(timeout);
                if (version === generation) { processing = false; syncBusy(); }
            }
        };
        original.onclick = setOriginal;
        retry.onclick = processBackground;
        const cancel = event => { if (saving) event.preventDefault(); };
        dialog.addEventListener('cancel', cancel);
        syncBusy();
        submit.onclick = async () => {
            if (saving || processing || !ready) return;
            const chosen = [...dialog.querySelectorAll('.upload-color-option input:checked')].map(input => input.value);
            if (balloon && !chosen.length) {
                error.textContent = 'Choose at least 1 balloon color.';
                error.hidden = false;
                error.scrollIntoView({block:'nearest'});
                return;
            }
            saving = true; syncBusy(); error.hidden = true;
            try {
                await save(chosen, selectedFile);
                dialog.close('saved');
            } catch (failure) {
                error.textContent = root.AppErrors?.text(failure.message, 'Unable to save this image. Please try again.') || failure.message;
                error.hidden = false;
                error.scrollIntoView({block:'nearest'});
            } finally { saving = false; syncBusy(); }
        };
        return new Promise(resolve => {
            dialog.addEventListener('close', () => {
                generation++; controller?.abort();
                if (processedUrl) URL.revokeObjectURL(processedUrl);
                dialog.removeEventListener('cancel', cancel);
                submit.onclick = null; original.onclick = null; retry.onclick = null;
                dialog.querySelector('img').removeAttribute('src');
                resolve(dialog.returnValue === 'saved');
            }, {once:true});
            dialog.showModal();
            dialog.querySelector('.balloon-colors-body').scrollTop = 0;
            if (preview) processBackground();
        });
    }

    async function postUpload(body, url = options.uploadUrl) {
        const response = await fetch(url, {method: 'POST', headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''}, body});
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.upload) throw new Error(result.message || result.error || 'The image could not be saved. Please try again.');
        return result.upload;
    }

    async function editColors(upload, opener = document.activeElement) {
        if (pending || !categoryRule(upload.category_id) || document.getElementById('balloonColorsDialog').open) return;
        let revisedId = upload.id;
        await colorDialog(upload.src, upload.label, upload.colors || [], true, async colors => {
            const message = options.validateColors(upload, colors);
            if (message) throw new Error(message);
            if (JSON.stringify(colors) === JSON.stringify(upload.colors)) return;
            pending++;
            updateOffer();
            try {
                const body = new FormData();
                body.append('design_offer_id', options.getOffer().id);
                body.append('colors', JSON.stringify(colors));
                if (options.getDesignId()) body.append('design_id', options.getDesignId());
                const revised = await postUpload(body, `${options.uploadUrl}${upload.id}/colors/`);
                await options.replaceUpload(upload, revised);
                revisedId = revised.id;
                registry()[String(revised.id)] = revised;
                registry()[String(upload.id)].in_library = false;
                libraryIds.delete(String(upload.id));
                libraryIds.add(String(revised.id));
                render();
                options.changed();
            } finally { pending--; updateOffer(); }
        });
        if (opener?.isConnected) opener.focus();
        else document.querySelector(`[data-upload-id="${revisedId}"]`)?.closest('.category-upload-card')?.querySelector('.upload-colors-edit')?.focus();
    }
    async function uploadFiles(control, files) {
        const offer = options.getOffer();
        const rule = categoryRule(control.dataset.categoryUpload);
        if (!rule || control.dataset.uploading === 'true') return;
        if (document.getElementById('balloonColorsDialog').open) return;
        control.dataset.uploading = 'true';
        pending++;
        updateOffer();
        control.setAttribute('aria-busy', 'true');
        const errors = [];
        try {
            for (const file of files) {
                if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) {
                    errors.push(`${file.name}: choose a JPG, PNG or WebP image up to 10 MB.`);
                    continue;
                }
                const save = async (colors, selectedFile) => {
                    const body = new FormData();
                    body.append('image', selectedFile);
                    body.append('category_id', rule.category_id);
                    body.append('design_offer_id', offer.id);
                    body.append('colors', JSON.stringify(colors));
                    body.append('label', file.name.replace(/\.[^.]+$/, ''));
                    if (options.getDesignId()) body.append('design_id', options.getDesignId());
                    const upload = await postUpload(body);
                    registry()[String(upload.id)] = upload;
                    libraryIds.add(String(upload.id));
                    render();
                    options.changed();
                };
                const preview = URL.createObjectURL(file);
                try { await colorDialog(preview, file.name, [], false, save, {file, rule, offer}); }
                finally { URL.revokeObjectURL(preview); }
            }
        } finally {
            pending--;
            delete control.dataset.uploading;
            control.removeAttribute('aria-busy');
            updateOffer();
            setError(control, errors.join(' '));
        }
    }
    function restore(uploads, ids) {
        if (uploads && typeof uploads === 'object' && !Array.isArray(uploads)) Object.assign(registry(), uploads);
        libraryIds.clear();
        (Array.isArray(ids) ? ids : Object.keys(registry())).forEach(id => { if (registry()[String(id)]) libraryIds.add(String(id)); });
        if (options) { render(); updateOffer(); }
    }
    function init(config) {
        options = config;
        let saved = {};
        try { saved = JSON.parse(root.savedCanvasJson || '{}'); } catch (error) { /* An invalid saved canvas is handled by the editor. */ }
        restore(null, root.canvasUploadLibraryIds || saved.upload_library_ids);
        document.querySelectorAll('[data-category-upload]').forEach(control => {
            const picker = control.querySelector('[data-category-file]');
            control.querySelector('[data-browse-category]').addEventListener('click', () => picker.click());
            picker.addEventListener('change', () => { uploadFiles(control, [...picker.files]); picker.value = ''; });
            ['dragenter', 'dragover'].forEach(type => control.addEventListener(type, event => {
                if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
                event.preventDefault(); event.stopPropagation();
                if (categoryRule(control.dataset.categoryUpload)) control.classList.add('is-file-over');
            }));
            control.addEventListener('dragleave', event => { if (!control.contains(event.relatedTarget)) control.classList.remove('is-file-over'); });
            control.addEventListener('drop', event => {
                if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
                event.preventDefault(); event.stopPropagation(); control.classList.remove('is-file-over');
                uploadFiles(control, [...event.dataTransfer.files]);
            });
        });
        const dialog = document.getElementById('balloonColorsDialog');
        dialog.addEventListener('keydown', event => event.stopPropagation());
        dialog.querySelectorAll('[data-color-cancel]').forEach(button => button.addEventListener('click', () => dialog.close('cancel')));
        dialog.querySelector('[data-add-upload-color]').addEventListener('click', () => addColor(dialog, dialog.querySelector('input[type="color"]').value, true));
        updateOffer();
    }
    const api = {init, restore, updateOffer, syncSelection, colorName, canonicalizeSources, ids: () => [...libraryIds], busy: () => pending > 0};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.CanvasCategoryUploads = api;
})(typeof window !== 'undefined' ? window : globalThis);
