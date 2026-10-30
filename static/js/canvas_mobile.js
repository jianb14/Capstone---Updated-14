/* A labelled, touch-friendly view of the same canvas controls and state. */
window.setupCanvasMobileEditor = function (api) {
    const byId = (id) => document.getElementById(id);
    const query = window.matchMedia('(max-width: 1024px)');
    const section = document.querySelector('.design-canvas-section');
    const sidebar = byId('canvasSidebar');
    const rail = document.querySelector('.canvas-tool-rail');
    const selection = byId('selectionToolbar');
    const context = byId('objectContextToolbar');
    const summary = byId('summaryFloatPanel');
    const summaryToggle = byId('summaryFloatBtn');
    const canvasColors = byId('customCanvasColor').closest('.sidebar-section');
    const objectColors = byId('customObjectColor').closest('.sidebar-section');
    const backgroundControls = byId('bgImageUpload').closest('.sidebar-section');
    const backgroundHeader = backgroundControls.previousElementSibling;
    const inventory = byId('mobileInventoryDialog');
    const editor = byId('mobileEditItemDialog');
    const tools = byId('mobileCanvasToolsDialog');
    const checklist = byId('mobileChecklistDialog');
    const dialogs = [inventory, editor, tools, checklist];
    const placeholders = new Map();
    const originalPadding = new WeakMap();
    let mobile = false;
    let textEditStarted = false;
    let resizeFrame = null;
    let editingSelection = null;
    let restoreEditorFocus = false;

    function move(node, parent) {
        if (!node || !parent) return;
        if (!placeholders.has(node)) {
            const anchor = document.createComment('desktop canvas control');
            node.before(anchor);
            placeholders.set(node, anchor);
        }
        parent.appendChild(node);
    }
    function closeInventory() { if (inventory.open) inventory.close(); }
    function open(dialog) {
        api.closeFontMenu();
        dialogs.forEach((other) => { if (other !== dialog && other.open) other.close(); });
        if (dialog === editor) {
            // Keep the real canvas interactive and visible alongside its controls.
            // Other sheets still use a modal dialog for browsing and confirmations.
            section.classList.add('mobile-editor-editing');
            if (!dialog.open) dialog.show();
            resizeCanvas();
        } else if (!dialog.open) dialog.showModal();
    }
    dialogs.forEach((dialog) => {
        dialog.querySelector('[data-mobile-close]').addEventListener('click', () => {
            if (dialog === editor) restoreEditorFocus = true;
            dialog.close();
        });
        dialog.addEventListener('click', (event) => {
            const rect = dialog.getBoundingClientRect();
            if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
        });
    });
    inventory.addEventListener('close', () => {
        if (inventory.open) return; // Ignore a queued close event after reopening.
        const active = rail.querySelector('.rail-btn.active[data-panel-target]');
        if (active) active.click();
    });
    editor.addEventListener('close', () => {
        section.classList.toggle('mobile-editor-editing', mobile && editor.open);
        api.closeFontMenu();
        resizeCanvas();
        if (restoreEditorFocus && mobile && !editor.open && api.selected().length) {
            byId('mobileEditItemBtn').focus({ preventScroll: true });
        }
        restoreEditorFocus = false;
    });
    editor.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        event.stopPropagation();
        if (byId('fontFamilyDropdown').classList.contains('open')) {
            api.closeFontMenu();
        } else {
            restoreEditorFocus = true;
            editor.close();
        }
    });
    function setEditSection(name) {
        api.closeFontMenu();
        editor.dataset.editSection = name;
        editor.querySelectorAll('[data-edit-section]').forEach((button) => {
            button.setAttribute('aria-pressed', String(button.dataset.editSection === name));
        });
        byId('mobileEditControls').scrollTop = 0;
    }
    editor.querySelector('.mobile-edit-sections').addEventListener('click', (event) => {
        const button = event.target.closest('[data-edit-section]');
        if (button) setEditSection(button.dataset.editSection);
    });
    checklist.addEventListener('close', () => {
        if (summaryToggle.getAttribute('aria-expanded') === 'true') summaryToggle.click();
    });
    rail.addEventListener('click', (event) => {
        if (!mobile) return;
        const button = event.target.closest('[data-panel-target]');
        if (!button) return;
        if (!button.classList.contains('active')) { closeInventory(); return; }
        const names = { elementsPanel: ['Add an item', 'Tap an item to add it to your design.'], textPanel: ['Add text', 'Choose a text style. You can change the words afterwards.'], uploadsPanel: ['Your photos', 'Upload a photo, then tap its preview to add it.'], layersPanel: ['Arrange items', 'Items at the top appear in front. Use Forward or Back to reorder.'] };
        const copy = names[button.dataset.panelTarget];
        byId('mobileInventoryTitle').textContent = copy[0];
        inventory.querySelector('header p').textContent = copy[1];
        if (button.dataset.panelTarget === 'layersPanel') refreshLayers();
        open(inventory);
    });
    sidebar.addEventListener('click', (event) => {
        if (mobile && event.target.closest('.layer-row') && !event.target.closest('button.layer-action-btn, .mobile-layer-order')) closeInventory();
    });
    byId('mobileCanvasToolsBtn').addEventListener('click', () => open(tools));
    byId('mobileEditItemBtn').addEventListener('click', () => { sync(); open(editor); });
    byId('mobileDeselectBtn').addEventListener('click', () => { api.canvas.discardActiveObject(); api.canvas.requestRenderAll(); api.refresh(); sync(); });
    function openChecklist() {
        if (summaryToggle.getAttribute('aria-expanded') !== 'true') summaryToggle.click();
        open(checklist);
    }
    byId('mobileChecklistBtn').addEventListener('click', openChecklist);
    byId('mobileRequiredItemsBtn').addEventListener('click', openChecklist);
    tools.addEventListener('click', (event) => {
        if (event.target.closest('#clearBtn, #applySizeBtn, #zoomResetBtn, #redoBtn')) tools.close();
    });

    const labels = {
        textBoldBtn: 'Bold', textItalicBtn: 'Italic', textUnderlineBtn: 'Underline',
        textAlignLeftBtn: 'Align left', textAlignCenterBtn: 'Center text', textAlignRightBtn: 'Align right',
        layerForwardBtn: 'Forward', layerBackwardBtn: 'Backward', toFrontBtn: 'To front', toBackBtn: 'To back',
        flipXBtn: 'Flip left / right', flipYBtn: 'Flip up / down', skewLeftBtn: 'Tilt left', skewRightBtn: 'Tilt right',
        contextLockBtn: 'Lock item', contextMoveUpBtn: 'Move up', contextMoveDownBtn: 'Move down',
        contextMoveLeftBtn: 'Move left', contextMoveRightBtn: 'Move right', contextDuplicateBtn: 'Duplicate', contextDeleteBtn: 'Delete item',
        redoBtn: 'Redo', zoomResetBtn: 'Fit to screen', clearBtn: 'Clear canvas', applySizeBtn: 'Apply size'
    };
    Object.entries(labels).forEach(([id, label]) => {
        const button = byId(id);
        if (!button) return;
        const span = document.createElement('span');
        span.className = 'mobile-editor-control-label'; span.textContent = label; button.appendChild(span);
    });
    [['fontFamilyDropdown', 'Font', 'mobile-font-label'], ['fontSizeInput', 'Text size', 'mobile-font-size-label'], ['itemColorPicker', 'Item color', 'mobile-color-label']].forEach(([id, copy, className]) => {
        const field = byId(id);
        const label = document.createElement('label');
        label.className = `mobile-editor-only ${className}`;
        label.textContent = copy;
        if (id !== 'fontFamilyDropdown') label.htmlFor = id;
        field.before(label);
    });
    const widthLabels = Array.from(document.querySelectorAll('label[for="elemWidthInput"], label[for="elemHeightInput"], label[for="canvasWidthInput"], label[for="canvasHeightInput"]'));
    const originalLabels = widthLabels.map((label) => label.textContent);

    function touchControls(object) {
        if (!object || object._isArtboard || object._isBgImage) return;
        if (!originalPadding.has(object)) originalPadding.set(object, { padding: object.padding, cornerSize: object.cornerSize, touchCornerSize: object.touchCornerSize });
        object.set(mobile ? { padding: 10, cornerSize: 14, touchCornerSize: 44 } : originalPadding.get(object));
        object.setCoords();
    }
    function updateRequirements(evaluation = api.evaluation()) {
        const required = (evaluation?.rows || []).filter((row) => row.required);
        const remaining = required.filter((row) => row.missing || row.over_limit).length;
        const ready = !!evaluation?.can_book;
        const review = !!evaluation && (!evaluation.rows?.length || !!evaluation.invalid_items?.length || evaluation.rows.some((row) => row.over_limit));
        const title = !evaluation ? 'Start your design' : ready ? 'Ready to book' : review ? 'Review items before booking' : `${required.length - remaining} of ${required.length} ${required.length === 1 ? 'requirement' : 'requirements'} complete`;
        const copy = !evaluation ? 'Tap Assets or Text below to add an item.' : ready ? 'Required items complete. Save your design to book.' : review ? 'Open the checklist to see what needs fixing. You can still save a draft.' : 'Add required items to book. You can save a draft anytime.';
        const setText = (id, text) => { const node = byId(id); if (node.textContent !== text) node.textContent = text; };
        setText('mobileRequirementsTitle', title);
        setText('mobileRequirementsCopy', copy);
        byId('mobileEditorGuide').classList.toggle('is-ready', ready);
        const badge = byId('mobileChecklistCount');
        badge.hidden = !evaluation;
        const badgeCopy = review ? '!' : String(remaining);
        if (badge.textContent !== badgeCopy) badge.textContent = badgeCopy;
        byId('mobileChecklistBtn').classList.toggle('is-ready', ready);
        byId('mobileChecklistBtn').setAttribute('aria-label', !evaluation ? 'Design checklist' : ready ? 'Checklist: ready to book' : review ? 'Checklist: items need review' : `Checklist: ${remaining} ${remaining === 1 ? 'requirement' : 'requirements'} left`);
        byId('mobileRequiredItemsBtn').setAttribute('aria-label', ready ? 'View completed booking requirements' : 'View required items before booking');
    }
    function sync() {
        if (!mobile) return;
        const objects = api.selected();
        const object = objects.length === 1 ? objects[0] : null;
        const selected = api.canvas.getActiveObject();
        const isText = !!object && api.isText(object);
        editor.querySelector('[data-edit-section="text"]').hidden = !isText;
        editor.querySelector('[data-edit-section="adjust"]').textContent = isText ? 'Size & color' : 'Size & tilt';
        if (selected !== editingSelection) {
            editingSelection = selected;
            setEditSection(isText ? 'text' : 'adjust');
        }
        byId('mobileSelectionBar').hidden = !objects.length;
        byId('mobileSelectionName').textContent = objects.length > 1 ? `${objects.length} items selected` : object && api.isText(object) ? 'Text selected' : object ? api.label(object) : 'Item selected';
        updateRequirements();
        byId('mobileTextField').hidden = !object || !api.isText(object);
        const text = byId('mobileObjectText');
        if (object && api.isText(object)) {
            if (document.activeElement !== text) text.value = object.text || '';
            text.disabled = !!object._isLocked;
        }
        const allLocked = objects.length && objects.every((item) => item._isLocked);
        byId('mobileLockedNote').hidden = !allLocked;
        byId('mobileSelectionTools').disabled = !!allLocked;
        byId('mobileSelectionTools').inert = !!allLocked;
        byId('mobileObjectColors').inert = !!allLocked;
        byId('contextLockBtn').querySelector('.mobile-editor-control-label').textContent = allLocked ? 'Unlock item' : 'Lock item';
        if (!objects.length && editor.open) editor.close();
    }
    byId('mobileObjectText').addEventListener('focus', () => { textEditStarted = false; });
    byId('mobileObjectText').addEventListener('input', (event) => {
        const selected = api.selected();
        const object = selected.length === 1 ? selected[0] : null;
        if (!object || !api.isText(object) || object._isLocked) return;
        if (!textEditStarted) { api.saveState(); textEditStarted = true; }
        object.set('text', event.target.value); object.setCoords();
        api.canvas.requestRenderAll(); api.refresh();
    });
    function refreshLayers() {
        if (!mobile) return;
        const objects = api.layers().slice().reverse();
        byId('layersList').querySelectorAll('.layer-row').forEach((row) => {
            const object = objects.find((item) => item._layerId === row.dataset.layerId);
            if (!object) return;
            row.querySelector('.layer-name').textContent = api.label(object);
            if (row.dataset.mobileControls === 'true') return;
            row.dataset.mobileControls = 'true';
            row.querySelectorAll('.layer-action-btn').forEach((button) => {
                const label = document.createElement('span');
                label.className = 'mobile-editor-control-label';
                label.textContent = button.getAttribute('aria-label').replace(' layer', '');
                button.appendChild(label);
            });
            const index = objects.findIndex((object) => object._layerId === row.dataset.layerId);
            if (!object || object._isBgImage) return;
            const order = document.createElement('div'); order.className = 'mobile-layer-order';
            [['Forward', -1], ['Back', 1]].forEach(([copy, delta]) => {
                const button = document.createElement('button'); button.type = 'button'; button.className = 'mobile-editor-secondary'; button.textContent = copy;
                const neighbor = objects[index + delta];
                button.disabled = !!object._isLocked || !neighbor || !!neighbor._isBgImage;
                button.addEventListener('click', (event) => {
                    event.stopPropagation(); api.reorder(object, neighbor, delta < 0); sync();
                });
                order.appendChild(button);
            });
            row.appendChild(order);
        });
    }
    new MutationObserver(refreshLayers).observe(byId('layersList'), { childList: true });

    function resizeCanvas() {
        if (resizeFrame) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
            resizeFrame = null;
            api.resize();
        });
    }
    function setMode() {
        mobile = query.matches;
        api.closeFontMenu();
        dialogs.forEach((dialog) => { if (dialog.open) dialog.close(); });
        section.classList.remove('mobile-editor-editing');
        document.body.classList.toggle('canvas-mobile-active', mobile);
        section.classList.toggle('mobile-editor-mode', mobile);
        document.querySelector('.canvas-main-toolbar > a svg use').setAttribute('href', mobile ? '#ci-arrow-left' : '#ci-home');
        if (mobile) {
            move(editor, document.querySelector('.design-layout'));
            move(sidebar, byId('mobileInventoryBody'));
            move(selection, byId('mobileSelectionTools'));
            move(context, byId('mobileObjectActions'));
            move(summary, byId('mobileChecklistBody'));
            move(canvasColors, byId('mobileCanvasColors'));
            move(objectColors, byId('mobileObjectColors'));
            move(backgroundHeader, byId('mobileCanvasBackground'));
            move(backgroundControls, byId('mobileCanvasBackground'));
            move(document.querySelector('.dimension-toolbar-group'), byId('mobileCanvasSize'));
            move(document.querySelector('.zoom-toolbar-group'), byId('mobileZoomTools'));
            ['redoBtn', 'zoomResetBtn', 'clearBtn'].forEach((id) => move(byId(id), byId('mobileCanvasActions')));
            if (summaryToggle.getAttribute('aria-expanded') === 'true') summaryToggle.click();
            widthLabels.forEach((label) => { label.textContent = label.htmlFor.includes('Width') ? 'Width' : 'Height'; });
        } else {
            placeholders.forEach((anchor, node) => anchor.parentNode.insertBefore(node, anchor.nextSibling));
            widthLabels.forEach((label, index) => { label.textContent = originalLabels[index]; });
        }
        api.canvas.getObjects().forEach(touchControls);
        sync(); refreshLayers(); resizeCanvas();
    }
    api.canvas.on('selection:created', sync);
    api.canvas.on('selection:updated', sync);
    api.canvas.on('selection:cleared', sync);
    api.canvas.on('object:modified', sync);
    api.canvas.on('text:changed', sync);
    api.canvas.on('object:added', (event) => {
        touchControls(event.target);
        if (mobile && inventory.open && !api.isRestoring() && event.target && !event.target._isArtboard && !event.target._isBgImage) {
            queueMicrotask(() => { closeInventory(); sync(); });
        }
    });
    new ResizeObserver(resizeCanvas).observe(byId('canvasDropZone'));
    query.addEventListener('change', setMode);
    const updateViewport = () => {
        const viewport = window.visualViewport;
        const height = viewport ? viewport.height : window.innerHeight;
        const keyboardInset = Math.max(0, window.innerHeight - height - (viewport ? viewport.offsetTop : 0));
        section.style.setProperty('--mobile-viewport-height', `${height}px`);
        section.style.setProperty('--mobile-keyboard-inset', `${keyboardInset}px`);
    };
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', updateViewport);
        window.visualViewport.addEventListener('scroll', updateViewport);
    }
    updateViewport(); setMode();
    return { sync, updateRequirements, closeSheets: () => dialogs.forEach(dialog => { if (dialog.open) dialog.close(); }) };
};
