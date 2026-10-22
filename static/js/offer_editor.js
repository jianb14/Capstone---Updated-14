document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('.offer-editor');
    if (!root) return;
    const form = document.getElementById('offerEditorForm');
    const data = JSON.parse(document.getElementById('offer-editor-data').textContent);
    const categories = new Map(data.categories.map(category => [Number(category.id), category]));
    const rows = data.rows.filter(row => row && typeof row === 'object').map(row => ({...row,
        required: typeof row.required === 'boolean' ? row.required : Number(row.required_minimum || 0) > 0,
        minimumCustom: Number(row.required_minimum || 0) > 0 && Number(row.required_minimum) !== Number(row.quantity || 1)}));
    const list = document.getElementById('inclusionRows');
    const template = document.getElementById('inclusionRowTemplate');
    const picker = document.getElementById('categoryPicker');
    const search = document.getElementById('categorySearch');
    const clearSearch = document.getElementById('clearCategorySearch');
    const colorInput = document.getElementById('id_design_max_colors');
    const removedImages = new Set();
    const newImages = [];
    const imageInput = document.getElementById('previewImageInput');
    const dropzone = document.getElementById('previewDropzone');
    const browse = document.getElementById('browsePreviewImages');
    const save = document.getElementById('saveOfferButton');
    const saveLabel = save.textContent;
    const state = document.getElementById('offerSaveStatus');
    const errorSummary = document.getElementById('offerErrorSummary');
    let openCategorySelect = null;
    let validationShown = !errorSummary.hidden;
    let inclusionErrors = [];

    function refreshValidationSummary() {
        if (!validationShown) return;
        const hasErrors = form.querySelector('[aria-invalid="true"], .oe-field-invalid') ||
            Array.from(form.querySelectorAll('.oe-field-error, .oe-row-errors')).some(area => area.textContent.trim());
        if (!hasErrors) {
            errorSummary.hidden = true;
            validationShown = false;
            state.textContent = 'Changes are saved together.';
        }
    }

    function clearFieldError(control) {
        if (!control) return;
        control.removeAttribute('aria-invalid');
        control.closest('.oe-field')?.classList.remove('oe-field-invalid');
        document.getElementById(`error_${control.name}`)?.replaceChildren();
        refreshValidationSummary();
    }

    function clearRowErrors(article, row, fields) {
        fields.forEach(field => {
            if (row.errors) delete row.errors[field];
            article.querySelector(field === 'category_id' ? '[data-category-trigger]' : `[data-row-field="${field}"]`)?.removeAttribute('aria-invalid');
        });
        article.querySelectorAll('[data-error-field]').forEach(message => {
            if (fields.includes(message.dataset.errorField)) message.remove();
        });
        clearFieldError(document.getElementById('id_design_enabled'));
    }

    function setupCategorySelect(article, index) {
        const wrapper = article.querySelector('.oe-select');
        const select = wrapper.querySelector('select');
        const trigger = wrapper.querySelector('[data-category-trigger]');
        const panel = wrapper.querySelector('[data-category-options]');
        const label = article.querySelector('[data-category-label]');
        const value = wrapper.querySelector('[data-category-value]');
        label.id = `inclusion-${index}-category-label`;
        value.id = `inclusion-${index}-category-value`;
        trigger.id = `inclusion-${index}-category-trigger`;
        panel.id = `inclusion-${index}-category-options`;
        trigger.setAttribute('aria-controls', panel.id);
        trigger.setAttribute('aria-labelledby', `${label.id} ${value.id}`);
        trigger.setAttribute('aria-describedby', `inclusion-${index}-errors`);
        panel.setAttribute('aria-labelledby', label.id);
        value.textContent = select.selectedOptions[0]?.textContent || 'Choose canvas category';
        let activeIndex = -1;
        let typed = '', lastTyped = 0;
        const choices = Array.from(select.options).filter(option => option.value).map((option, optionIndex) => {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'oe-select-option';
            button.id = `${panel.id}-${optionIndex}`;
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', String(option.value === select.value));
            button.disabled = option.disabled; button.tabIndex = -1;
            button.textContent = option.textContent + (option.disabled ? ' — Already included' : '');
            button.addEventListener('mousedown', event => event.preventDefault());
            button.addEventListener('click', () => choose(optionIndex));
            panel.appendChild(button);
            return {option, button};
        });
        if (!choices.length) {
            const note = document.createElement('p');
            note.textContent = 'No categories available for this offer type.';
            panel.appendChild(note);
        }
        function close() {
            panel.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            trigger.removeAttribute('aria-activedescendant');
            if (openCategorySelect?.wrapper === wrapper) openCategorySelect = null;
        }
        function activate(nextIndex) {
            if (!choices[nextIndex] || choices[nextIndex].option.disabled) return;
            activeIndex = nextIndex;
            choices.forEach((choice, i) => choice.button.classList.toggle('is-focused', i === nextIndex));
            trigger.setAttribute('aria-activedescendant', choices[nextIndex].button.id);
            choices[nextIndex].button.scrollIntoView({block: 'nearest'});
        }
        function open(preferLast = false) {
            openCategorySelect?.close();
            panel.hidden = false;
            const rect = trigger.getBoundingClientRect();
            const below = window.innerHeight - rect.bottom - 24;
            const above = rect.top - 24;
            const flip = below < Math.min(panel.scrollHeight, 220) && above > below;
            wrapper.classList.toggle('opens-above', flip);
            panel.style.maxHeight = `${Math.min(220, Math.max(60, flip ? above : below))}px`;
            trigger.setAttribute('aria-expanded', 'true');
            openCategorySelect = {wrapper, close};
            const enabled = choices.map((choice, i) => choice.option.disabled ? -1 : i).filter(i => i >= 0);
            const selected = choices.findIndex(choice => choice.option.value === select.value && !choice.option.disabled);
            activate(selected >= 0 ? selected : enabled[preferLast ? enabled.length - 1 : 0]);
        }
        function choose(nextIndex) {
            const choice = choices[nextIndex];
            if (!choice || choice.option.disabled) return;
            close();
            select.value = choice.option.value;
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }
        trigger.addEventListener('click', () => panel.hidden ? open() : close());
        trigger.addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); close(); return; }
            if (event.key === 'Tab') { close(); return; }
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                if (panel.hidden) open(); else choose(activeIndex);
                return;
            }
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                if (panel.hidden) { open(event.key === 'ArrowUp' || event.key === 'End'); return; }
                const enabled = choices.map((choice, i) => choice.option.disabled ? -1 : i).filter(i => i >= 0);
                const current = enabled.indexOf(activeIndex);
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length;
                activate(enabled[next]);
                return;
            }
            if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
                event.preventDefault();
                if (panel.hidden) open();
                const now = Date.now();
                typed = (now - lastTyped > 700 ? '' : typed) + event.key.toLowerCase();
                lastTyped = now;
                activate(choices.findIndex(choice => !choice.option.disabled && choice.option.textContent.toLowerCase().startsWith(typed)));
            }
        });
        trigger.addEventListener('blur', event => {
            if (!wrapper.contains(event.relatedTarget)) close();
        });
    }

    document.addEventListener('pointerdown', event => {
        if (openCategorySelect && !(event.target instanceof Node && openCategorySelect.wrapper.contains(event.target))) openCategorySelect.close();
    });
    window.addEventListener('resize', () => openCategorySelect?.close());

    function syncRows() {
        document.getElementById('offerInclusions').value = JSON.stringify(rows.map((row, index) => ({
            row_type: row.row_type, name: row.name || '', quantity: row.quantity === '' ? null : row.quantity,
            category_id: row.row_type === 'item' ? row.category_id || null : null,
            required_minimum: row.row_type === 'item' ? row.required_minimum || 0 : 0, order: index,
            required: row.row_type === 'item' && Boolean(row.required),
        })));
    }

    function fieldValue(name) { return document.getElementById(`id_${name}`)?.value || ''; }
    function balloonRows() { return rows.filter(row => row.row_type === 'item' && categories.get(Number(row.category_id))?.balloon); }
    function currentImages() {
        return [...data.previews.filter(image => !removedImages.has(image.id)).map(image => ({...image, existing: true})), ...newImages];
    }

    function updatePreview() {
        syncRows();
        document.getElementById('inclusionCount').textContent = `${rows.length} inclusion${rows.length === 1 ? '' : 's'}`;
        document.getElementById('emptyInclusions').hidden = rows.length > 0;
        document.getElementById('customerPreviewName').textContent = fieldValue('name') || 'Your offer name';
        document.getElementById('customerPreviewDescription').textContent = fieldValue('description');
        const amount = Number(fieldValue(root.dataset.offerKind === 'entrance' ? 'solo_price' : 'price'));
        document.getElementById('customerPreviewPrice').textContent = new Intl.NumberFormat('en-PH', {style: 'currency', currency: 'PHP', maximumFractionDigits: amount % 1 ? 2 : 0}).format(Number.isFinite(amount) ? amount : 0);
        document.getElementById('customerPreviewNotes').textContent = fieldValue('notes');
        const balloons = balloonRows();
        document.getElementById('balloonSettings').hidden = !balloons.length;
        colorInput.disabled = !balloons.length;
        if (!balloons.length) clearFieldError(colorInput);
        const preview = document.getElementById('customerPreviewInclusions');
        preview.replaceChildren();
        let colorShown = false;
        rows.forEach(row => {
            if (!String(row.name || '').trim()) return;
            const li = document.createElement('li');
            const text = document.createElement('span');
            text.textContent = `${row.quantity ? `${row.quantity} ` : ''}${row.name}`;
            if (!colorShown && row.row_type === 'item' && categories.get(Number(row.category_id))?.balloon && colorInput.value) {
                text.textContent += ` (max ${colorInput.value} colors)`;
                colorShown = true;
            }
            li.appendChild(text); preview.appendChild(li);
        });
        if (!preview.childElementCount) { const item = document.createElement('li'); item.textContent = 'Your inclusions will appear here.'; preview.appendChild(item); }
        document.getElementById('customerPreviewImages').replaceChildren(...currentImages().map(image => {
            const img = document.createElement('img'); img.src = image.url; img.alt = 'Offer preview'; return img;
        }));
        refreshValidationSummary();
    }

    function updateRowControls(article, row) {
        const service = row.row_type === 'service';
        article.querySelector('.oe-required-label').hidden = service;
        article.querySelector('.oe-service-tag').hidden = !service;
        article.querySelector('.oe-category-field').hidden = service;
        const settings = article.querySelector('.oe-design-settings');
        settings.hidden = service;
        if (!service && !row.category_id) settings.open = true;
        const required = article.querySelector('[data-row-required]');
        required.checked = !service && Boolean(row.required);
        required.setAttribute('aria-label', `Require ${row.name || 'this item'} in the design`);
        article.querySelector('[data-row-required-note]').textContent = required.checked ? `Minimum ${row.required_minimum}` : 'Optional';
        const minimum = article.querySelector('[data-row-field="required_minimum"]');
        minimum.disabled = !required.checked;
        minimum.value = required.checked ? row.required_minimum : '';
        article.querySelector('[data-convert-row]').textContent = service ? 'Change to Canvas Item' : 'Change to Service';
        article.querySelector('[data-remove-row]').setAttribute('aria-label', `Remove ${row.name || 'inclusion'}`);
        article.classList.toggle('oe-row-needs-review', !service && !row.category_id);
    }

    function renderRows(errors) {
        if (errors) rows.forEach((row, index) => { row.errors = {...(errors[String(index)] || {})}; });
        inclusionErrors = errors ? errors.inclusions || [] : [];
        openCategorySelect?.close();
        list.replaceChildren();
        rows.forEach((row, index) => {
            const article = template.content.firstElementChild.cloneNode(true);
            article.dataset.rowIndex = index;
            article.querySelectorAll('[data-row-field]').forEach(control => {
                const key = control.dataset.rowField;
                control.id = `inclusion-${index}-${key}`;
                control.setAttribute('aria-describedby', `inclusion-${index}-errors`);
                if (key === 'category_id') {
                    const placeholder = new Option('Choose canvas category', '');
                    control.appendChild(placeholder);
                    data.categories.forEach(category => {
                        const option = new Option(category.name + (category.active ? '' : ' (Hidden)'), String(category.id));
                        option.disabled = rows.some((other, otherIndex) => otherIndex !== index && other.row_type === 'item' && Number(other.category_id) === Number(category.id));
                        control.appendChild(option);
                    });
                }
                control.value = row[key] ?? '';
                control.addEventListener(key === 'category_id' ? 'change' : 'input', () => {
                    const related = key === 'quantity' ? ['quantity', 'required_minimum'] : key === 'category_id' ? ['category_id', 'name'] : [key];
                    clearRowErrors(article, row, related);
                    const previousCategory = categories.get(Number(row.category_id));
                    row[key] = control.value;
                    if (key === 'category_id') {
                        const expanded = article.querySelector('.oe-design-settings').open;
                        const category = categories.get(Number(row.category_id));
                        if (!row.name || row.name === previousCategory?.name) row.name = category?.name || row.name;
                        renderRows();
                        const replacement = list.children[index];
                        replacement.querySelector('.oe-design-settings').open = expanded;
                        replacement.querySelector('[data-category-trigger]').focus();
                    } else {
                        if (key === 'quantity' && row.required && !row.minimumCustom) row.required_minimum = Number(control.value) || 1;
                        if (key === 'required_minimum') row.minimumCustom = true;
                        updateRowControls(article, row);
                    }
                    updatePreview();
                });
            });
            setupCategorySelect(article, index);
            article.querySelector('[data-row-required]').addEventListener('change', event => {
                clearRowErrors(article, row, ['required_minimum']);
                row.required = event.target.checked;
                row.required_minimum = event.target.checked ? Number(row.quantity) || 1 : 0;
                row.minimumCustom = false;
                updateRowControls(article, row); updatePreview();
            });
            article.querySelector('[data-remove-row]').addEventListener('click', () => {
                clearFieldError(document.getElementById('id_design_enabled'));
                rows.splice(index, 1); renderRows(); updatePreview();
                list.querySelector(`[data-row-index="${Math.min(index, rows.length - 1)}"] [data-row-field="name"]`)?.focus();
            });
            article.querySelector('[data-convert-row]').addEventListener('click', () => {
                clearRowErrors(article, row, ['category_id', 'required_minimum', 'row_type']);
                row.row_type = row.row_type === 'item' ? 'service' : 'item';
                row.category_id = null; row.required_minimum = 0; row.minimumCustom = false; row.required = false;
                renderRows(); updatePreview();
                const focusSelector = row.row_type === 'item' ? '[data-category-trigger]' : '[data-row-field="name"]';
                list.children[index]?.querySelector(focusSelector)?.focus();
            });
            const errorArea = article.querySelector('.oe-row-errors');
            errorArea.id = `inclusion-${index}-errors`;
            for (const [field, messages] of Object.entries(row.errors || {})) {
                const control = article.querySelector(field === 'category_id' ? '[data-category-trigger]' : `[data-row-field="${field}"]`);
                control?.setAttribute('aria-invalid', 'true');
                if (field === 'required_minimum' || field === 'category_id') article.querySelector('.oe-design-settings').open = true;
                for (const message of messages) { const p = document.createElement('p'); p.dataset.errorField = field; p.textContent = message; errorArea.appendChild(p); }
            }
            if (row.row_type === 'item' && !row.category_id && !errorArea.childElementCount) {
                const note = document.createElement('p'); note.textContent = 'Needs review: choose a canvas category or change this row to Service.'; errorArea.appendChild(note);
            }
            updateRowControls(article, row); list.appendChild(article);
        });
        document.getElementById('inclusionsError').textContent = inclusionErrors.join(' ');
        updatePreview();
    }

    function renderPicker() {
        clearSearch.hidden = !search.value.length;
        const options = document.getElementById('categoryPickerOptions');
        const term = search.value.trim().toLowerCase(); options.replaceChildren();
        data.categories.filter(category => category.name.toLowerCase().includes(term)).forEach(category => {
            const used = rows.some(row => row.row_type === 'item' && Number(row.category_id) === Number(category.id));
            const button = document.createElement('button'); button.type = 'button'; button.className = 'oe-category-option'; button.disabled = used || !category.active;
            const name = document.createElement('span'); name.textContent = category.name; button.appendChild(name);
            const status = document.createElement('small'); status.textContent = used ? 'Already included' : category.active ? 'Add item +' : 'Hidden'; button.appendChild(status);
            button.addEventListener('click', () => {
                clearFieldError(document.getElementById('id_design_enabled'));
                rows.push({row_type: 'item', name: category.name, quantity: '', category_id: category.id, required_minimum: 0, minimumCustom: false});
                picker.close(); renderRows();
                list.lastElementChild.querySelector('[data-row-field="quantity"]').focus();
            }); options.appendChild(button);
        });
        if (!options.childElementCount) { const note = document.createElement('p'); note.textContent = 'No matching categories. Create categories in Canvas Assets and make them available for this offer type.'; options.appendChild(note); }
    }
    document.getElementById('addCanvasItem').addEventListener('click', () => { search.value = ''; renderPicker(); picker.showModal(); search.focus(); });
    document.getElementById('closeCategoryPicker').addEventListener('click', () => picker.close());
    picker.addEventListener('click', event => { if (event.target === picker) { const bounds = picker.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) picker.close(); } });
    search.addEventListener('input', renderPicker);
    clearSearch.addEventListener('click', () => { search.value = ''; renderPicker(); search.focus(); });
    document.getElementById('addService').addEventListener('click', () => {
        clearFieldError(document.getElementById('id_design_enabled'));
        rows.push({row_type: 'service', name: '', quantity: '', category_id: null, required_minimum: 0});
        renderRows(); list.lastElementChild.querySelector('[data-row-field="name"]').focus();
    });

    function showImageMessages(messages) {
        dropzone.classList.toggle('is-invalid', messages.length > 0);
        const area = document.getElementById('previewImageErrors'); area.replaceChildren();
        messages.forEach(message => { const p = document.createElement('p'); p.textContent = message; area.appendChild(p); });
        refreshValidationSummary();
    }
    function renderImages() {
        const transfer = new DataTransfer(); newImages.forEach(image => transfer.items.add(image.file)); imageInput.files = transfer.files;
        document.getElementById('removedPreviewIds').value = Array.from(removedImages).join(',');
        const images = currentImages();
        document.getElementById('previewImageCount').textContent = `${images.length}/2`;
        browse.disabled = images.length >= 2;
        browse.textContent = images.length >= 2 ? '2 images selected' : 'Browse Files';
        const cards = document.getElementById('previewImageCards'); cards.replaceChildren();
        images.forEach((image, index) => {
            const card = document.createElement('figure'); card.className = 'oe-image-card';
            const picture = document.createElement('img'); picture.src = image.url; picture.alt = `Preview image ${index + 1}`;
            const caption = document.createElement('figcaption');
            const name = document.createElement('span'); name.textContent = image.existing ? `Saved image ${index + 1}` : image.file.name;
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove preview image ${index + 1}`);
            remove.addEventListener('click', () => {
                if (image.existing) removedImages.add(image.id);
                else { newImages.splice(newImages.indexOf(image), 1); URL.revokeObjectURL(image.url); }
                showImageMessages([]); renderImages(); browse.focus();
            });
            caption.append(name, remove); card.append(picture, caption); cards.appendChild(card);
        }); updatePreview();
    }
    function addImages(files) {
        const messages = [];
        Array.from(files).forEach(file => {
            if (!file.type.startsWith('image/')) { messages.push(`${file.name}: choose an image file.`); return; }
            if (currentImages().length >= 2) { messages.push(`${file.name} was not added. Only 2 preview images are allowed.`); return; }
            if (newImages.some(image => image.file.name === file.name && image.file.size === file.size && image.file.lastModified === file.lastModified)) return;
            newImages.push({file, url: URL.createObjectURL(file)});
        }); showImageMessages(messages); renderImages();
    }
    browse.addEventListener('click', () => imageInput.click());
    imageInput.addEventListener('change', () => addImages(imageInput.files));
    dropzone.addEventListener('dragover', event => { event.preventDefault(); dropzone.classList.add('is-dragover'); });
    dropzone.addEventListener('dragleave', event => { if (!dropzone.contains(event.relatedTarget)) dropzone.classList.remove('is-dragover'); });
    dropzone.addEventListener('drop', event => { event.preventDefault(); dropzone.classList.remove('is-dragover'); addImages(event.dataTransfer.files); });
    form.querySelectorAll('.oe-fields input, .oe-fields textarea, #id_design_max_colors').forEach(input => input.addEventListener('input', updatePreview));
    form.querySelectorAll('.oe-fields input, .oe-fields textarea, #id_design_max_colors, #id_design_enabled, #id_is_featured').forEach(input => {
        input.addEventListener('input', () => clearFieldError(input));
        input.addEventListener('change', () => clearFieldError(input));
    });

    function displayErrors(result) {
        form.querySelectorAll('.oe-field-invalid').forEach(field => field.classList.remove('oe-field-invalid'));
        form.querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
        form.querySelectorAll('.oe-field-error[id^="error_"]').forEach(field => field.replaceChildren());
        renderRows(result.row_errors || {});
        for (const [name, messages] of Object.entries(result.errors || {})) {
            const area = document.getElementById(`error_${name}`);
            if (area) area.textContent = messages.join(' ');
            const input = document.getElementById(`id_${name}`); input?.setAttribute('aria-invalid', 'true'); input?.closest('.oe-field')?.classList.add('oe-field-invalid');
        }
        showImageMessages(result.image_errors || []);
        validationShown = true;
        errorSummary.hidden = false;
        errorSummary.textContent = 'Please review the marked fields. Your changes and selected images have been kept.';
        const first = form.querySelector('[aria-invalid="true"]');
        if (first) { first.closest('details')?.setAttribute('open', ''); first.focus(); first.scrollIntoView({behavior: 'smooth', block: 'center'}); }
        else { errorSummary.focus(); errorSummary.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    }
    form.addEventListener('submit', async event => {
        event.preventDefault(); syncRows(); const payload = new FormData(form);
        save.disabled = true; save.textContent = 'Saving…'; state.textContent = 'Saving your offer…';
        try {
            const response = await fetch(form.action || window.location.href, {method: 'POST', body: payload, headers: {'X-Requested-With': 'XMLHttpRequest'}});
            const result = await response.json();
            if (response.ok && result.success) { window.location.assign(result.redirect_url); return; }
            displayErrors(result); state.textContent = 'Review the marked fields to continue.';
        } catch (error) {
            validationShown = false;
            errorSummary.hidden = false; errorSummary.textContent = 'The offer could not be saved. Your changes are still here. Please try again.'; state.textContent = 'Not saved. Please try again.';
        } finally { save.disabled = false; save.textContent = saveLabel; }
    });
    renderRows(data.row_errors || {}); showImageMessages(data.image_errors || []); renderImages();
});
