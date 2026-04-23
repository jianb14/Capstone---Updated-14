document.addEventListener('DOMContentLoaded', function() {
    const byId = (id) => document.getElementById(id);

    const dropZone = byId('canvasDropZone');

    function setCategoryOpenState(category, header, lists, open) {
        if (!category || !header || !lists || !lists.length) return;
        header.classList.toggle('is-open', open);
        header.dataset.manualOpen = open ? 'true' : 'false';
        header.setAttribute('aria-expanded', open ? 'true' : 'false');
        category.classList.toggle('is-open', open);
        lists.forEach((list) => list.classList.toggle('open', open));
    }

    const initSidebarFallback = () => {
        const categories = Array.from(document.querySelectorAll('.inventory-category'));
        const searchInput = byId('assetSearchInput');

        categories.forEach((category, index) => {
            const header = category.querySelector('.category-header');
            const list = category.querySelector('.category-items');
            if (!header || !list) return;

            const shouldOpen = list.classList.contains('open') || index === 0;
            setCategoryOpenState(category, header, [list], shouldOpen);

            if (header.dataset.accordionBound === 'true') return;
            header.dataset.accordionBound = 'true';

            header.addEventListener('click', (event) => {
                event.preventDefault();
                const willOpen = !header.classList.contains('is-open');
                setCategoryOpenState(category, header, [list], willOpen);
                if (willOpen) {
                    list.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
            });
        });

        if (!searchInput) return;

        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();
            categories.forEach((category) => {
                const header = category.querySelector('.category-header');
                const list = category.querySelector('.category-items');
                if (!header || !list) return;

                const items = Array.from(list.querySelectorAll('.draggable-item'));
                const hasItems = items.length > 0;
                let hasVisibleItems = false;

                items.forEach((item) => {
                    const text = `${item.getAttribute('title') || ''} ${item.dataset.text || ''}`.toLowerCase();
                    const matches = !query || text.includes(query);
                    item.classList.toggle('is-hidden', !matches);
                    if (matches) hasVisibleItems = true;
                });

                if (!query) {
                    const manualOpen = header.dataset.manualOpen === 'true';
                    setCategoryOpenState(category, header, [list], manualOpen);
                    category.classList.remove('is-search-hidden');
                    return;
                }

                const showCategory = hasItems ? hasVisibleItems : (header.textContent || '').toLowerCase().includes(query);
                category.classList.toggle('is-search-hidden', !showCategory);
                setCategoryOpenState(category, header, [list], showCategory);
            });
        });
    };

    if (!dropZone || typeof fabric === 'undefined') {
        initSidebarFallback();
        return;
    }

    const dropHint = byId('dropHint');
    const selectionToolbar = byId('selectionToolbar');
    const contextToolbar = byId('objectContextToolbar');

    const undoBtn = byId('undoBtn');
    const redoBtn = byId('redoBtn');
    const clearBtn = byId('clearBtn');
    const saveDesignBtn = byId('saveDesignBtn');
    const zoomInBtn = byId('zoomInBtn');
    const zoomOutBtn = byId('zoomOutBtn');
    const zoomResetBtn = byId('zoomResetBtn');
    const zoomLabel = byId('zoomLabel');
    const zoomRange = byId('zoomRange');

    const cloneBtn = byId('cloneBtn');
    const lockBtn = byId('lockBtn');
    const layerUpBtn = byId('layerUpBtn');
    const layerDownBtn = byId('layerDownBtn');
    const toFrontBtn = byId('toFrontBtn');
    const toBackBtn = byId('toBackBtn');
    const flipXBtn = byId('flipXBtn');
    const flipYBtn = byId('flipYBtn');
    const skewLeftBtn = byId('skewLeftBtn');
    const skewRightBtn = byId('skewRightBtn');
    const rotateLeftBtn = byId('rotateLeftBtn');
    const rotateRightBtn = byId('rotateRightBtn');
    const moveUpBtn = byId('moveUpBtn');
    const moveDownBtn = byId('moveDownBtn');
    const moveLeftBtn = byId('moveLeftBtn');
    const moveRightBtn = byId('moveRightBtn');
    const deleteBtn = byId('deleteBtn');
    const itemColorPicker = byId('itemColorPicker');

    const fontFamilySelect = byId('fontFamilySelect');
    const fontSizeInput = byId('fontSizeInput');
    const textBoldBtn = byId('textBoldBtn');
    const textItalicBtn = byId('textItalicBtn');
    const textUnderlineBtn = byId('textUnderlineBtn');
    const textAlignLeftBtn = byId('textAlignLeftBtn');
    const textAlignCenterBtn = byId('textAlignCenterBtn');
    const textAlignRightBtn = byId('textAlignRightBtn');

    const contextDuplicateBtn = byId('contextDuplicateBtn');
    const contextLockBtn = byId('contextLockBtn');
    const contextBringFrontBtn = byId('contextBringFrontBtn');
    const contextRotateLeftBtn = byId('contextRotateLeftBtn');
    const contextRotateRightBtn = byId('contextRotateRightBtn');
    const contextMoveUpBtn = byId('contextMoveUpBtn');
    const contextMoveDownBtn = byId('contextMoveDownBtn');
    const contextMoveLeftBtn = byId('contextMoveLeftBtn');
    const contextMoveRightBtn = byId('contextMoveRightBtn');
    const contextDeleteBtn = byId('contextDeleteBtn');

    const customCanvasColor = byId('customCanvasColor');
    const bgImageUpload = byId('bgImageUpload');
    const removeBgImage = byId('removeBgImage');

    const elemWidthInput = byId('elemWidthInput');
    const elemHeightInput = byId('elemHeightInput');
    const applySizeBtn = byId('applySizeBtn');
    const canvasWidthInput = byId('canvasWidthInput');
    const canvasHeightInput = byId('canvasHeightInput');
    const canvasSizeDisp = byId('canvasSizeDisp');

    const quickTextInput = byId('quickTextInput');
    const addTextBtn = byId('addTextBtn');
    const assetSearchInput = byId('assetSearchInput');

    const userUploadInput = byId('userUploadInput');
    const userUploadsGrid = byId('userUploadsGrid');

    const drawToolButtons = Array.from(document.querySelectorAll('.draw-tool-btn[data-draw-tool]'));
    const drawColorInput = byId('drawColorInput');
    const drawColorLabel = byId('drawColorLabel');
    const drawSizeInput = byId('drawSizeInput');
    const drawSizeValue = byId('drawSizeValue');
    const drawOpacityInput = byId('drawOpacityInput');
    const drawOpacityValue = byId('drawOpacityValue');
    const disableDrawBtn = byId('disableDrawBtn');

    const cartInclusionsList = byId('cartInclusionsList');
    const cartAddonsList = byId('cartAddonsList');
    const cartTotalPrice = byId('cartTotalPrice');

    let ARTBOARD_W = 1920;
    let ARTBOARD_H = 1080;
    const MIN_ZOOM = 0.15;
    const MAX_ZOOM = 1.5;
    const MAX_UNDO = 40;
    const ENABLE_VIEWPORT_PAN = false;

    const canvas = new fabric.Canvas('designCanvas', {
        width: dropZone.clientWidth,
        height: dropZone.clientHeight,
        selection: true,
        preserveObjectStacking: true,
        backgroundColor: 'transparent'
    });

    const undoStack = [];
    const redoStack = [];
    let isLoadingState = false;
    let isPanning = false;
    let isSpaceDown = false;
    let lastPanPos = { x: 0, y: 0 };
    let artboard = null;
    let currentDrawTool = drawToolButtons.find((btn) => btn.classList.contains('active'))?.dataset.drawTool || 'pen';
    let lastBalloonColor = null;

    const objectControlStyle = {
        cornerColor: '#ffffff',
        cornerStrokeColor: '#111111',
        borderColor: '#f4f4f4',
        cornerStyle: 'circle',
        cornerSize: 10,
        transparentCorners: false,
        borderScaleFactor: 2,
        padding: 6
    };
    const rotateCursorSvg = `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><path fill='%23ffffff' d='M12 4a8 8 0 1 1-7.3 4.7h2.2A6 6 0 1 0 12 6v2.2l4-3.7-4-3.7z'/><path fill='%23000000' d='M12 5.2a6.8 6.8 0 1 1-6.2 4h.7a6 6 0 1 0 5.5-3.2V7.9l2.7-2.5L12 2.9z' opacity='.35'/></svg>`;
    const ROTATE_CURSOR = `url("data:image/svg+xml,${encodeURIComponent(rotateCursorSvg)}") 12 12, crosshair`;

    const textActionButtons = [
        textBoldBtn,
        textItalicBtn,
        textUnderlineBtn,
        textAlignLeftBtn,
        textAlignCenterBtn,
        textAlignRightBtn
    ].filter(Boolean);

    function hexToRgba(hex, alpha) {
        if (!hex) return `rgba(0, 0, 0, ${alpha})`;
        const normalized = hex.replace('#', '');
        const safeHex =
            normalized.length === 3
                ? normalized
                      .split('')
                      .map((char) => char + char)
                      .join('')
                : normalized.padEnd(6, '0').slice(0, 6);

        const r = parseInt(safeHex.slice(0, 2), 16);
        const g = parseInt(safeHex.slice(2, 4), 16);
        const b = parseInt(safeHex.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function toHexColor(value, fallback = '#000000') {
        if (!value) return fallback;
        try {
            const hex = new fabric.Color(value).toHex();
            return hex ? `#${hex}` : fallback;
        } catch (error) {
            return fallback;
        }
    }

    function applyObjectControlStyle(obj) {
        if (!obj) return obj;
        obj.set(objectControlStyle);
        applyInteractionCursors(obj);
        return obj;
    }

    function applyInteractionCursors(obj) {
        if (!obj || obj._isArtboard) return obj;

        const isTextObject = obj.type === 'i-text' || obj.type === 'text' || obj.type === 'textbox';
        if (!obj._isLocked) {
            obj.set({
                hasControls: true,
                hasRotatingPoint: true,
                lockRotation: false,
                moveCursor: 'move',
                hoverCursor: isTextObject ? 'move' : 'move'
            });
            if (typeof obj.setControlsVisibility === 'function') {
                obj.setControlsVisibility({
                    mtr: true
                });
            }
            obj.rotatingPointOffset = 28;
        }

        if (obj.controls?.mtr) {
            obj.controls.mtr.cursorStyleHandler = () => ROTATE_CURSOR;
        }

        return obj;
    }

    function categoriesMatch(categoryName, quotaName) {
        const catLower = normalizeCategoryName(categoryName);
        const quotaLower = normalizeCategoryName(quotaName);

        if (!catLower || !quotaLower) return false;

        const catSingular = catLower.endsWith('s') ? catLower.slice(0, -1) : catLower;
        const catPlural = catLower.endsWith('s') ? catLower : `${catLower}s`;
        const quotaSingular = quotaLower.endsWith('s') ? quotaLower.slice(0, -1) : quotaLower;
        const quotaPlural = quotaLower.endsWith('s') ? quotaLower : `${quotaLower}s`;

        return (
            catLower === quotaLower ||
            catLower === quotaSingular ||
            catLower === quotaPlural ||
            quotaLower === catSingular ||
            quotaLower === catPlural ||
            (quotaLower.includes(catSingular) && catSingular.length > 3) ||
            (catLower.includes(quotaSingular) && quotaSingular.length > 3) ||
            (quotaLower.includes('panel') && catLower.includes('backdrop')) ||
            (quotaLower.includes('backdrop') && catLower.includes('panel')) ||
            (quotaLower.includes('flower') && catLower.includes('floral')) ||
            (quotaLower.includes('floral') && catLower.includes('flower'))
        );
    }

    function updateSidebarGroupsBadge(visibleCount) {
        const groupsBadge = document.querySelector('.panel-badge');
        if (groupsBadge) groupsBadge.textContent = `${visibleCount} groups`;
    }

    function syncVisibleCategoryAccordions() {
        const visibleCategories = Array.from(document.querySelectorAll('.inventory-category')).filter(
            (cat) => cat.style.display !== 'none'
        );
        if (!visibleCategories.length) return;

        let hasOpenVisible = false;
        visibleCategories.forEach((category) => {
            const header = category.querySelector('.category-header');
            if (!header) return;
            if (header.classList.contains('is-open')) hasOpenVisible = true;
        });

        if (hasOpenVisible) return;

        const firstVisible = visibleCategories[0];
        const firstHeader = firstVisible.querySelector('.category-header');
        const firstLists = firstVisible.querySelectorAll('.category-items');
        if (!firstHeader || !firstLists.length) return;

        firstHeader.classList.add('is-open');
        firstHeader.dataset.manualOpen = 'true';
        firstLists.forEach((list) => list.classList.add('open'));
    }

    function ensureCategoryLabelsVisible() {
        document.querySelectorAll('.inventory-category').forEach((category) => {
            const header = category.querySelector('.category-header');
            if (!header) return;

            let labelNode = header.querySelector('span');
            if (!labelNode) {
                labelNode = document.createElement('span');
                header.prepend(labelNode);
            }

            const currentText = (labelNode.textContent || '').trim();
            if (currentText) return;

            const fallback = (category.dataset.categoryName || 'Category')
                .replace(/\s+/g, ' ')
                .trim()
                .replace(/\b\w/g, (c) => c.toUpperCase());
            labelNode.textContent = fallback || 'Category';
        });
    }

    function normalizeAssetSrc(src) {
        const value = String(src || '').trim();
        if (!value) return '';
        if (/^(data:|blob:|https?:\/\/|\/\/)/i.test(value)) return value;
        if (value.startsWith('/')) return value;
        return `/${value.replace(/^\.?\//, '')}`;
    }

    function ensureAssetPreviewFallback(img) {
        if (!img || img.dataset.previewFallbackBound === 'true') return;
        img.dataset.previewFallbackBound = 'true';
        img.addEventListener('error', () => {
            const wrapper = img.closest('.item-preview-img-wrapper');
            if (!wrapper) {
                img.remove();
                return;
            }
            if (!wrapper.querySelector('.empty-panel-note')) {
                const emptyText = document.createElement('span');
                emptyText.className = 'empty-panel-note';
                emptyText.textContent = 'Image unavailable';
                wrapper.appendChild(emptyText);
            }
            img.remove();
        });
    }

    function getCategoryAssetsFromPayload(payload, categoryKey) {
        if (!payload || typeof payload !== 'object') return [];
        if (Array.isArray(payload[categoryKey])) return payload[categoryKey];

        const matchedEntry = Object.entries(payload).find(([key, items]) => {
            return normalizeCategoryName(key) === categoryKey && Array.isArray(items);
        });

        return matchedEntry ? matchedEntry[1] : [];
    }

    function buildAssetCardFromPayload(asset, fallbackCategory) {
        if (!asset) return null;

        const item = document.createElement('div');
        item.className = 'draggable-item';
        item.setAttribute('draggable', 'true');
        item.setAttribute('data-type', asset.type || 'image');
        item.setAttribute('data-category', asset.category || fallbackCategory || 'custom');
        item.setAttribute('data-src', normalizeAssetSrc(asset.src));
        item.setAttribute('data-width', `${asset.width || 150}`);
        item.setAttribute('data-height', `${asset.height || 150}`);
        item.setAttribute('title', asset.label || 'Asset');

        const preview = document.createElement('div');
        preview.className = 'item-preview-img-wrapper';
        const normalizedSrc = normalizeAssetSrc(asset.src);

        if (normalizedSrc) {
            const img = document.createElement('img');
            img.className = 'item-preview-img';
            img.src = normalizedSrc;
            img.alt = asset.label || 'Asset';
            img.loading = 'lazy';
            ensureAssetPreviewFallback(img);
            preview.appendChild(img);
        } else {
            const emptyText = document.createElement('span');
            emptyText.className = 'empty-panel-note';
            emptyText.textContent = 'No image';
            preview.appendChild(emptyText);
        }

        const label = document.createElement('span');
        label.className = 'item-label';
        label.textContent = asset.label || 'Asset';

        item.appendChild(preview);
        item.appendChild(label);
        return item;
    }

    function hydrateSidebarAssetsFromPayload() {
        const payload = window.canvasAssetsPayload;
        if (!payload || typeof payload !== 'object') {
            document.querySelectorAll('.item-preview-img').forEach(ensureAssetPreviewFallback);
            return;
        }

        document.querySelectorAll('.inventory-category').forEach((category) => {
            const list = category.querySelector('.category-items');
            if (!list) return;

            const headerLabel =
                category.querySelector('.category-header span')?.textContent ||
                category.dataset.categoryName ||
                '';
            const categoryKey = normalizeCategoryName(category.dataset.categoryName || headerLabel);
            const categoryAssets = getCategoryAssetsFromPayload(payload, categoryKey);
            const existingItems = Array.from(list.querySelectorAll('.draggable-item'));
            const shouldHydrateFromPayload = categoryAssets.length > 0;

            if (shouldHydrateFromPayload) {
                list.innerHTML = '';
                categoryAssets.forEach((asset) => {
                    const card = buildAssetCardFromPayload(asset, categoryKey);
                    if (card) list.appendChild(card);
                });
            } else {
                existingItems.forEach((item) => {
                    const normalizedDataSrc = normalizeAssetSrc(item.getAttribute('data-src'));
                    if (normalizedDataSrc) item.setAttribute('data-src', normalizedDataSrc);

                    const previewImg = item.querySelector('.item-preview-img');
                    if (previewImg) {
                        const rawSrc = previewImg.getAttribute('src');
                        const normalizedImgSrc = normalizeAssetSrc(rawSrc);
                        if (normalizedImgSrc && rawSrc !== normalizedImgSrc) {
                            previewImg.setAttribute('src', normalizedImgSrc);
                        }
                        ensureAssetPreviewFallback(previewImg);
                    }
                });
            }

            if (!list.querySelector('.draggable-item') && !list.querySelector('.empty-panel-note')) {
                const emptyText = document.createElement('div');
                emptyText.className = 'empty-panel-note';
                emptyText.textContent = 'No assets in this category yet.';
                list.appendChild(emptyText);
            }
        });

        document.querySelectorAll('.item-preview-img').forEach(ensureAssetPreviewFallback);
    }

    function filterAssetsByPackage() {
        const categories = Array.from(document.querySelectorAll('.inventory-category'));
        if (!categories.length) return;

        // Keep categories visible in the sidebar so users can always browse assets.
        // Package limits are still enforced when adding items to canvas via checkQuota().
        categories.forEach((cat) => {
            cat.style.removeProperty('display');
            cat.classList.remove('is-search-hidden');
        });

        updateSidebarGroupsBadge(categories.length);
        syncVisibleCategoryAccordions();
    }

    // Call it after initializing sidebar panels or accordions
    hydrateSidebarAssetsFromPayload();
    ensureCategoryLabelsVisible();
    filterAssetsByPackage();

    function initSidebarPanels() {
        const railButtons = Array.from(document.querySelectorAll('.rail-btn[data-panel-target]'));
        const panels = Array.from(document.querySelectorAll('.sidebar-panel'));
        const sidebar = byId('canvasSidebar');
        const designLayout = document.querySelector('.design-layout');
        if (!railButtons.length || !panels.length) return;

        const syncCanvasAfterSidebarToggle = () => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    canvas.setWidth(dropZone.clientWidth);
                    canvas.setHeight(dropZone.clientHeight);
                    zoomCenter(canvas.getZoom());
                });
            });
        };

        const setSidebarState = (targetId) => {
            const isOpen = !!targetId;
            railButtons.forEach((node) => {
                const isActive = isOpen && node.getAttribute('data-panel-target') === targetId;
                node.classList.toggle('active', isActive);
                node.setAttribute('aria-pressed', isActive ? 'true' : 'false');
            });

            panels.forEach((panel) => panel.classList.toggle('active', isOpen && panel.id === targetId));
            if (sidebar) sidebar.classList.toggle('is-collapsed', !isOpen);
            if (designLayout) designLayout.classList.toggle('sidebar-collapsed', !isOpen);
            syncCanvasAfterSidebarToggle();
        };

        setSidebarState(null);

        railButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-panel-target');
                const isAlreadyActive = btn.classList.contains('active');

                if (isAlreadyActive) {
                    setSidebarState(null);
                    disableDrawingMode();
                    return;
                }

                setSidebarState(targetId);
                if (targetId !== 'toolsPanel') disableDrawingMode();
            });
        });
    }

    function initPackageSelection() {
        const packageCards = document.querySelectorAll('.package-selection-card');
        const cartBaseName = byId('cartBaseName');
        const cartInclusionsArea = byId('cartInclusionsArea');

        if (!packageCards.length) return;

        // Pre-select the active package card if editing/re-loading
        if (window.basePackageId) {
            packageCards.forEach((card) => {
                if (card.dataset.packageId === window.basePackageId) {
                    card.classList.add('selected');
                }
            });
        }

        packageCards.forEach((card) => {
            card.addEventListener('click', () => {
                const pkgId = card.dataset.packageId;
                const pkgName = card.dataset.packageName;
                const pkgPrice = parseFloat(card.dataset.packagePrice || '0');

                // 1. Update global state
                window.basePackageId = pkgId;
                window.basePackagePrice = pkgPrice;
                if (window.allPackageQuotas && window.allPackageQuotas[pkgId]) {
                    window.packageQuotas = window.allPackageQuotas[pkgId];
                } else {
                    window.packageQuotas = {};
                }

                // 2. Update UI selection
                packageCards.forEach((c) => c.classList.remove('selected'));
                card.classList.add('selected');

                // 3. Update summary panel info
                if (cartBaseName) cartBaseName.textContent = pkgName;
                if (cartInclusionsArea) cartInclusionsArea.style.display = 'block';

                // 4. Update asset visibility based on new quotas
                filterAssetsByPackage();

                // 5. Recalculate cart total
                updateVisualCart();
            });
        });
    }

    function initCategoryAccordions() {
        const categories = document.querySelectorAll('.inventory-category');
        categories.forEach((category, index) => {
            const header = category.querySelector('.category-header');
            const lists = category.querySelectorAll('.category-items');
            if (!header || !lists.length) return;

            const initiallyOpen = category.querySelector('.category-items.open') || index === 0;
            setCategoryOpenState(category, header, lists, !!initiallyOpen);

            if (header.dataset.accordionBound === 'true') return;
            header.dataset.accordionBound = 'true';

            header.addEventListener('click', (event) => {
                event.preventDefault();
                const willOpen = !header.classList.contains('is-open');
                setCategoryOpenState(category, header, lists, willOpen);
                if (willOpen) {
                    const firstOpenList = category.querySelector('.category-items.open');
                    if (firstOpenList) {
                        firstOpenList.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }
                }
            });
        });
    }

    function initAssetSearch() {
        if (!assetSearchInput) return;

        assetSearchInput.addEventListener('input', () => {
            const query = assetSearchInput.value.trim().toLowerCase();
            const categories = document.querySelectorAll('.inventory-category');

            categories.forEach((category) => {
                const header = category.querySelector('.category-header');
                const lists = category.querySelectorAll('.category-items');
                const categoryLabel = header ? header.textContent.toLowerCase() : '';
                let categoryHasVisibleItems = false;

                lists.forEach((list) => {
                    const items = list.querySelectorAll('.draggable-item');
                    let listHasVisibleItems = false;

                    items.forEach((item) => {
                        const title = item.getAttribute('title') || '';
                        const text = item.dataset.text || '';
                        const font = item.dataset.fontFamily || '';
                        const haystack = `${title} ${text} ${font} ${categoryLabel}`.toLowerCase();
                        const matches = !query || haystack.includes(query);
                        item.classList.toggle('is-hidden', !matches);
                        if (matches) listHasVisibleItems = true;
                    });

                    if (query) {
                        list.classList.toggle('open', listHasVisibleItems);
                    } else if (header) {
                        list.classList.toggle('open', header.dataset.manualOpen === 'true');
                    }

                    if (listHasVisibleItems) categoryHasVisibleItems = true;
                });

                if (header && !query) {
                    setCategoryOpenState(category, header, lists, header.dataset.manualOpen === 'true');
                } else if (header) {
                    setCategoryOpenState(category, header, lists, categoryHasVisibleItems);
                }

                category.classList.toggle('is-search-hidden', !categoryHasVisibleItems && !!query);
            });
        });
    }

    function updateDrawLabels() {
        if (drawSizeInput && drawSizeValue) {
            drawSizeValue.textContent = `${drawSizeInput.value}px`;
        }
        if (drawOpacityInput && drawOpacityValue) {
            drawOpacityValue.textContent = `${drawOpacityInput.value}%`;
        }
        if (drawColorLabel) {
            drawColorLabel.textContent =
                currentDrawTool === 'eraser'
                    ? `Artboard ${toHexColor(artboard?.fill || '#ffffff', '#ffffff').toUpperCase()}`
                    : (drawColorInput?.value || '#000000').toUpperCase();
        }
    }

    function applyDrawSettings() {
        if (!canvas || !drawSizeInput || !drawOpacityInput) return;
        if (!canvas.freeDrawingBrush) {
            canvas.freeDrawingBrush = new fabric.PencilBrush(canvas);
        }

        let width = parseInt(drawSizeInput.value, 10) || 5;
        let opacity = (parseInt(drawOpacityInput.value, 10) || 100) / 100;
        let color = drawColorInput?.value || '#000000';

        if (currentDrawTool === 'marker') {
            width = Math.max(width, 10);
            opacity = Math.min(opacity, 0.45);
        } else if (currentDrawTool === 'highlighter') {
            width = Math.max(width, 18);
            opacity = Math.min(opacity, 0.24);
        } else if (currentDrawTool === 'eraser') {
            width = Math.max(width, 12);
            opacity = 1;
            color = toHexColor(artboard?.fill || '#ffffff', '#ffffff');
        }

        canvas.freeDrawingBrush = new fabric.PencilBrush(canvas);
        canvas.freeDrawingBrush.width = width;
        canvas.freeDrawingBrush.color = hexToRgba(color, opacity);
        updateDrawLabels();
    }

    function activateDrawTool(toolName) {
        if (!toolName) return;
        currentDrawTool = toolName;
        drawToolButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.drawTool === toolName));
        canvas.discardActiveObject();
        canvas.renderAll();
        canvas.isDrawingMode = true;
        canvas.selection = false;
        canvas.defaultCursor = 'crosshair';
        canvas.setCursor('crosshair');
        hideContextToolbar();
        if (selectionToolbar) {
            selectionToolbar.classList.remove('is-visible');
            selectionToolbar.setAttribute('aria-hidden', 'true');
        }
        applyDrawSettings();
    }

    function disableDrawingMode() {
        if (!canvas.isDrawingMode) return;
        canvas.isDrawingMode = false;
        canvas.selection = true;
        canvas.defaultCursor = 'default';
        canvas.setCursor('default');
        updateControlsState();
    }

    initSidebarPanels();
    initPackageSelection();
    initCategoryAccordions();
    initAssetSearch();
    ensureCategoryLabelsVisible();

    function createArtboard() {
        const rect = new fabric.Rect({
            width: ARTBOARD_W,
            height: ARTBOARD_H,
            fill: '#ffffff',
            stroke: null,
            strokeWidth: 0,
            shadow: null,
            selectable: false,
            evented: false,
            hoverCursor: 'default',
            moveCursor: 'default',
            lockMovementX: true,
            lockMovementY: true,
            lockRotation: true,
            lockScalingX: false,
            lockScalingY: false,
            hasControls: false,
            hasBorders: false,
            cornerStyle: 'circle'
        });
        rect.setControlsVisibility({
            mtr: false
        });
        rect._isArtboard = true;
        canvas.add(rect);
        rect.sendToBack();
        return rect;
    }

    artboard = createArtboard();

    function syncLockState(obj, shouldLock) {
        obj._isLocked = shouldLock;
        obj.set({
            lockMovementX: shouldLock,
            lockMovementY: shouldLock,
            lockRotation: shouldLock,
            lockScalingX: shouldLock,
            lockScalingY: shouldLock,
            hasControls: !shouldLock,
            hoverCursor: shouldLock ? 'not-allowed' : 'move',
            opacity: shouldLock ? 0.8 : 1,
            selectable: true,
            evented: true
        });
        if (typeof obj.setControlsVisibility === 'function') {
            obj.setControlsVisibility({
                mtr: !shouldLock
            });
        }
        if (!shouldLock) {
            applyInteractionCursors(obj);
        }
    }

    function getCurrentState() {
        return JSON.stringify(
            canvas.toJSON([
                '_isArtboard',
                '_isColorableSVG',
                '_isLocked',
                '_packageCategory',
                '_isBgImage'
            ])
        );
    }

    function updateUndoRedoBtnState() {
        if (undoBtn) undoBtn.disabled = undoStack.length === 0;
        if (redoBtn) redoBtn.disabled = redoStack.length === 0;
    }

    function saveState() {
        if (isLoadingState) return;
        undoStack.push(getCurrentState());
        if (undoStack.length > MAX_UNDO) undoStack.shift();
        redoStack.length = 0;
        updateUndoRedoBtnState();
    }

    function updateCanvasSizeDisplay() {
        if (canvasSizeDisp) {
            canvasSizeDisp.textContent = `Canvas: ${ARTBOARD_W} x ${ARTBOARD_H}`;
        }
        if (canvasWidthInput) canvasWidthInput.value = ARTBOARD_W;
        if (canvasHeightInput) canvasHeightInput.value = ARTBOARD_H;
    }

    function clampArtboardSize(width, height) {
        return {
            width: Math.max(100, Math.min(5000, Math.round(width || ARTBOARD_W))),
            height: Math.max(100, Math.min(5000, Math.round(height || ARTBOARD_H)))
        };
    }

    function syncBackgroundToArtboard() {
        canvas.getObjects().forEach((obj) => {
            if (!obj._isBgImage) return;
            const scale = Math.max(ARTBOARD_W / obj.width, ARTBOARD_H / obj.height);
            obj.set({
                left: artboard.left,
                top: artboard.top,
                originX: 'left',
                originY: 'top',
                scaleX: scale,
                scaleY: scale
            });
            obj.setCoords();
        });
    }

    function applyArtboardSize(nextWidth, nextHeight, options = {}) {
        const { saveHistory = false, fitToView = false } = options;
        const clamped = clampArtboardSize(nextWidth, nextHeight);

        if (saveHistory) saveState();

        ARTBOARD_W = clamped.width;
        ARTBOARD_H = clamped.height;

        artboard.set({
            width: ARTBOARD_W,
            height: ARTBOARD_H,
            scaleX: 1,
            scaleY: 1
        });
        artboard.setCoords();

        syncBackgroundToArtboard();
        updateCanvasSizeDisplay();

        if (fitToView) {
            fitArtboardToView();
        } else {
            canvas.renderAll();
            updateContextToolbar();
        }
    }

    function commitArtboardResizeFromTransform() {
        const scaledW = (artboard.width || ARTBOARD_W) * (artboard.scaleX || 1);
        const scaledH = (artboard.height || ARTBOARD_H) * (artboard.scaleY || 1);
        applyArtboardSize(scaledW, scaledH, { saveHistory: true, fitToView: false });
    }

    function restoreCanvasState(state) {
        isLoadingState = true;

        canvas.loadFromJSON(state, () => {
            const loadedArtboard = canvas.getObjects().find((obj) => obj._isArtboard);
            if (loadedArtboard) {
                artboard = loadedArtboard;
                ARTBOARD_W = Math.round((artboard.width || ARTBOARD_W) * (artboard.scaleX || 1));
                ARTBOARD_H = Math.round((artboard.height || ARTBOARD_H) * (artboard.scaleY || 1));
            } else {
                artboard = createArtboard();
            }

            canvas.getObjects().forEach((obj) => {
                if (obj._isArtboard) {
                    obj.set({
                        selectable: false,
                        evented: false,
                        lockMovementX: true,
                        lockMovementY: true,
                        lockRotation: true,
                        lockScalingX: false,
                        lockScalingY: false,
                        hasControls: false,
                        hasBorders: false,
                        hoverCursor: 'default',
                        moveCursor: 'default'
                    });
                    obj.setControlsVisibility({
                        mtr: false
                    });
                    obj.sendToBack();
                }
                if (obj._isBgImage) {
                    obj.selectable = false;
                    obj.evented = false;
                }
                if (!obj._isArtboard && !obj._isBgImage) {
                    applyInteractionCursors(obj);
                }
                if (obj._isLocked) {
                    syncLockState(obj, true);
                }
            });

            artboard.set({
                width: ARTBOARD_W,
                height: ARTBOARD_H,
                scaleX: 1,
                scaleY: 1,
                stroke: null,
                strokeWidth: 0,
                shadow: null
            });
            artboard.setCoords();
            syncBackgroundToArtboard();

            fitArtboardToView();
            updateCanvasSizeDisplay();
            updateHintVisibility();
            updateControlsState();
            updateUndoRedoBtnState();
            updateVisualCart();
            updateDrawLabels();

            isLoadingState = false;
        });
    }

    function updateZoomLabel() {
        if (!zoomLabel) return;
        const zoomPercent = Math.round(canvas.getZoom() * 100);
        zoomLabel.textContent = `${zoomPercent}%`;
        if (zoomRange) {
            const minZoomPercent = Math.round(getMinAllowedZoom() * 100);
            const maxZoomPercent = Math.round(MAX_ZOOM * 100);
            zoomRange.min = `${minZoomPercent}`;
            zoomRange.max = `${maxZoomPercent}`;
            zoomRange.value = `${zoomPercent}`;
        }
    }

    function getFitZoom() {
        const zoomX = canvas.getWidth() / ARTBOARD_W;
        const zoomY = canvas.getHeight() / ARTBOARD_H;
        return Math.min(zoomX, zoomY);
    }

    function getMinAllowedZoom() {
        return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, getFitZoom()));
    }

    function centerArtboardAtCurrentZoom() {
        const zoom = canvas.getZoom();
        const abLeft = (canvas.getWidth() - ARTBOARD_W * zoom) / 2;
        const abTop = (canvas.getHeight() - ARTBOARD_H * zoom) / 2;

        artboard.set({
            left: abLeft / zoom,
            top: abTop / zoom
        });

        const vpt = canvas.viewportTransform;
        vpt[4] = 0;
        vpt[5] = 0;
        canvas.setViewportTransform(vpt);
        artboard.setCoords();
        syncBackgroundToArtboard();
    }

    function clampPan() {
        const zoom = canvas.getZoom();
        const vpt = canvas.viewportTransform;
        const canvasW = canvas.getWidth();
        const canvasH = canvas.getHeight();

        const abLeft = artboard.left * zoom + vpt[4];
        const abTop = artboard.top * zoom + vpt[5];
        const abRight = abLeft + ARTBOARD_W * zoom;
        const abBottom = abTop + ARTBOARD_H * zoom;

        const margin = 220;

        if (abRight < margin) vpt[4] += margin - abRight;
        if (abLeft > canvasW - margin) vpt[4] -= abLeft - (canvasW - margin);
        if (abBottom < margin) vpt[5] += margin - abBottom;
        if (abTop > canvasH - margin) vpt[5] -= abTop - (canvasH - margin);

        canvas.setViewportTransform(vpt);
    }

    function fitArtboardToView() {
        const zoom = getMinAllowedZoom();

        canvas.setZoom(zoom);
        centerArtboardAtCurrentZoom();
        canvas.renderAll();
        updateZoomLabel();
        updateSelectionToolbarPosition();
        updateContextToolbar();
    }

    function zoomToPoint(point, newZoom) {
        const minZoom = getMinAllowedZoom();
        const safeZoom = Math.max(minZoom, Math.min(MAX_ZOOM, newZoom));
        if (ENABLE_VIEWPORT_PAN) {
            canvas.zoomToPoint(point, safeZoom);
            clampPan();
        } else {
            canvas.setZoom(safeZoom);
            centerArtboardAtCurrentZoom();
        }
        canvas.renderAll();
        updateZoomLabel();
        updateSelectionToolbarPosition();
        updateContextToolbar();
    }

    function zoomCenter(newZoom) {
        const center = new fabric.Point(canvas.getWidth() / 2, canvas.getHeight() / 2);
        zoomToPoint(center, newZoom);
    }

    function hideContextToolbar() {
        if (!contextToolbar) return;
        contextToolbar.classList.remove('is-visible');
        contextToolbar.setAttribute('aria-hidden', 'true');
    }

    function updateSelectionToolbarPosition() {
        if (!selectionToolbar || !selectionToolbar.classList.contains('is-visible')) return;
        const zoom = canvas.getZoom();
        const vpt = canvas.viewportTransform || [1, 0, 0, 1, 0, 0];
        const artboardLeft = artboard.left * zoom + vpt[4];
        const artboardTop = artboard.top * zoom + vpt[5];
        const artboardWidth = ARTBOARD_W * zoom;

        const centerX = artboardLeft + artboardWidth / 2;
        const topY = artboardTop + 12;
        const clampedX = Math.max(12, Math.min(dropZone.clientWidth - 12, centerX));
        const clampedY = Math.max(12, Math.min(dropZone.clientHeight - 12, topY));

        selectionToolbar.style.left = `${clampedX}px`;
        selectionToolbar.style.top = `${clampedY}px`;
    }

    function updateContextToolbar() {
        if (!contextToolbar) return;
        const active = canvas.getActiveObject();
        if (!active || active._isArtboard) {
            hideContextToolbar();
            return;
        }

        const bounds = active.getBoundingRect(false, true);
        if (!bounds) {
            hideContextToolbar();
            return;
        }

        const centerX = bounds.left + bounds.width / 2;
        const topY = Math.max(18, bounds.top - 10);

        const clampedX = Math.max(18, Math.min(dropZone.clientWidth - 18, centerX));
        const clampedY = Math.max(18, topY);

        contextToolbar.style.left = `${clampedX}px`;
        contextToolbar.style.top = `${clampedY}px`;
        contextToolbar.classList.add('is-visible');
        contextToolbar.setAttribute('aria-hidden', 'false');
    }

    function updateHintVisibility() {
        const count = canvas.getObjects().filter((obj) => !obj._isArtboard).length;

        if (dropHint) dropHint.style.display = count > 0 ? 'none' : 'grid';
        if (clearBtn) clearBtn.disabled = count === 0;
        if (saveDesignBtn) saveDesignBtn.disabled = count === 0;
    }

    function isOutlineColor(colorStr) {
        if (!colorStr || colorStr === 'none' || colorStr === 'transparent') return false;
        const value = colorStr.toLowerCase();
        return (
            value === '#000000' ||
            value === '#111111' ||
            value === '#222222' ||
            value === '#333333' ||
            value === 'black'
        );
    }

    function getSelectableActiveObjects() {
        return canvas.getActiveObjects().filter((obj) => !obj._isArtboard);
    }

    function getUnlockedActiveObjects() {
        return getSelectableActiveObjects().filter((obj) => !obj._isLocked);
    }

    function rotateSelectedObjects(degrees) {
        const selected = getUnlockedActiveObjects();
        if (!selected.length) return;
        saveState();
        selected.forEach((obj) => {
            obj.rotate((obj.angle || 0) + degrees);
            obj.setCoords();
        });
        canvas.renderAll();
        updateContextToolbar();
    }

    function nudgeSelectedObjects(dx, dy) {
        const selected = getUnlockedActiveObjects();
        if (!selected.length) return;
        saveState();
        selected.forEach((obj) => {
            obj.left += dx;
            obj.top += dy;
            obj.setCoords();
        });
        canvas.renderAll();
        updateContextToolbar();
    }

    function getSingleActiveObject() {
        const active = getSelectableActiveObjects();
        return active.length === 1 ? active[0] : null;
    }

    function getActiveTextObjects() {
        return getSelectableActiveObjects().filter(
            (obj) => obj.type === 'i-text' || obj.type === 'text' || obj.type === 'textbox'
        );
    }

    function setTextButtonState(btn, active) {
        if (!btn) return;
        btn.classList.toggle('is-active', !!active);
    }

    function updateTextControlsUI() {
        const textObjects = getActiveTextObjects();
        const hasTextSelection = textObjects.length > 0;

        textActionButtons.forEach((btn) => {
            btn.disabled = !hasTextSelection;
        });
        if (fontFamilySelect) fontFamilySelect.disabled = !hasTextSelection;
        if (fontSizeInput) fontSizeInput.disabled = !hasTextSelection;

        if (!hasTextSelection) {
            setTextButtonState(textBoldBtn, false);
            setTextButtonState(textItalicBtn, false);
            setTextButtonState(textUnderlineBtn, false);
            setTextButtonState(textAlignLeftBtn, false);
            setTextButtonState(textAlignCenterBtn, false);
            setTextButtonState(textAlignRightBtn, false);
            return;
        }

        const first = textObjects[0];
        if (fontFamilySelect) fontFamilySelect.value = first.fontFamily || '';
        if (fontSizeInput) fontSizeInput.value = Math.round(first.fontSize || 40);

        setTextButtonState(textBoldBtn, first.fontWeight === 'bold' || Number(first.fontWeight) >= 600);
        setTextButtonState(textItalicBtn, first.fontStyle === 'italic');
        setTextButtonState(textUnderlineBtn, !!first.underline);
        setTextButtonState(textAlignLeftBtn, (first.textAlign || 'left') === 'left');
        setTextButtonState(textAlignCenterBtn, first.textAlign === 'center');
        setTextButtonState(textAlignRightBtn, first.textAlign === 'right');
    }

    function updateElementSizeInputs() {
        const active = getSingleActiveObject();
        if (!active) {
            if (elemWidthInput) elemWidthInput.value = 0;
            if (elemHeightInput) elemHeightInput.value = 0;
            return;
        }
        if (elemWidthInput) elemWidthInput.value = Math.round(active.getScaledWidth());
        if (elemHeightInput) elemHeightInput.value = Math.round(active.getScaledHeight());
    }

    function updateControlsState() {
        const activeObjs = getSelectableActiveObjects();
        const hasSelection = activeObjs.length > 0;
        const singleObj = activeObjs.length === 1 ? activeObjs[0] : null;
        const hasUnlockedSelection = activeObjs.some((obj) => !obj._isLocked);
        const allLocked = hasSelection && activeObjs.every((obj) => obj._isLocked);
        const hasTextSelection = getActiveTextObjects().length > 0;

        if (selectionToolbar) {
            selectionToolbar.classList.toggle('is-visible', hasSelection && !canvas.isDrawingMode);
            selectionToolbar.setAttribute('aria-hidden', hasSelection && !canvas.isDrawingMode ? 'false' : 'true');
            selectionToolbar.dataset.selectionType = hasTextSelection ? 'text' : hasSelection ? 'object' : 'none';
            if (hasSelection && !canvas.isDrawingMode) {
                requestAnimationFrame(updateSelectionToolbarPosition);
            }
        }
        if (!hasSelection) hideContextToolbar();

        if (cloneBtn) cloneBtn.disabled = !hasSelection || allLocked;
        if (lockBtn) lockBtn.disabled = !hasSelection;
        if (layerUpBtn) layerUpBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (layerDownBtn) layerDownBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (toFrontBtn) toFrontBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (toBackBtn) toBackBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (flipXBtn) flipXBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (flipYBtn) flipYBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (skewLeftBtn) skewLeftBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (skewRightBtn) skewRightBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (rotateLeftBtn) rotateLeftBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (rotateRightBtn) rotateRightBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (moveUpBtn) moveUpBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (moveDownBtn) moveDownBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (moveLeftBtn) moveLeftBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (moveRightBtn) moveRightBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (deleteBtn) deleteBtn.disabled = !hasSelection;
        if (contextRotateLeftBtn) contextRotateLeftBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (contextRotateRightBtn) contextRotateRightBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (contextMoveUpBtn) contextMoveUpBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (contextMoveDownBtn) contextMoveDownBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (contextMoveLeftBtn) contextMoveLeftBtn.disabled = !hasSelection || !hasUnlockedSelection;
        if (contextMoveRightBtn) contextMoveRightBtn.disabled = !hasSelection || !hasUnlockedSelection;

        if (lockBtn) {
            const lockIcon = lockBtn.querySelector('i');
            if (lockIcon) lockIcon.className = allLocked ? 'fas fa-lock' : 'fas fa-lock-open';
        }
        if (contextLockBtn) {
            const contextIcon = contextLockBtn.querySelector('i');
            if (contextIcon) contextIcon.className = allLocked ? 'fas fa-lock' : 'fas fa-lock-open';
        }

        if (itemColorPicker) {
            itemColorPicker.disabled = !hasSelection;
            if (singleObj) {
                if (singleObj._currentColor) {
                    itemColorPicker.value = toHexColor(singleObj._currentColor, '#111111');
                } else if (singleObj.type === 'path') {
                    itemColorPicker.value = toHexColor(singleObj.stroke || singleObj.fill || '#111111', '#111111');
                } else if (singleObj.type === 'i-text' || singleObj.type === 'text' || singleObj.type === 'textbox' || singleObj.type === 'rect') {
                    itemColorPicker.value = toHexColor(singleObj.fill || '#111111', '#111111');
                } else if (singleObj._isColorableSVG) {
                    const shapes = singleObj._objects ? singleObj._objects : [singleObj];
                    let foundColor = '#111111';
                    for (const shape of shapes) {
                        if (shape.fill && !isOutlineColor(shape.fill) && shape.fill !== 'none') {
                            try {
                                const hex = new fabric.Color(shape.fill).toHex();
                                if (hex) foundColor = `#${hex}`;
                            } catch (error) {
                                foundColor = '#111111';
                            }
                            break;
                        }
                    }
                    itemColorPicker.value = foundColor;
                }
            }
        }

        updateElementSizeInputs();
        updateTextControlsUI();
        updateSelectionToolbarPosition();
        updateContextToolbar();
    }

    function getArtboardCenterPoint() {
        return {
            x: artboard.left + ARTBOARD_W / 2,
            y: artboard.top + ARTBOARD_H / 2
        };
    }

    function getCategoryFromSrc(src) {
        if (!src) return 'custom';
        const value = src.toLowerCase();
        if (value.includes('arch')) return 'arch';
        if (value.includes('backdrop')) return 'backdrop';
        if (value.includes('plinth')) return 'plinths';
        if (value.includes('balloon')) return 'balloons';
        if (value.includes('flower') || value.includes('floral') || value.includes('fern')) return 'florals';
        if (value.includes('neon')) return 'neon';
        return 'custom';
    }

    function applyColorToObject(obj, color) {
        if (!obj || !color) return;

        const normalizedCat = normalizeCategoryName(obj._packageCategory);
        const isBalloon = normalizedCat === 'balloons' || normalizedCat === 'balloon';

        if (isBalloon) {
            // Check if applying this color would exceed the unique color limit
            const potentialColors = getUniqueBalloonColors(obj, color);
            const limit = window.packageQuotas ? (window.packageQuotas.balloon_color_limit || 2) : 2;
            
            if (potentialColors.length > limit) {
                handleColorUpgrade(limit);
                return; // RESTRICT: Do not apply the color
            }
            lastBalloonColor = color; // Track last balloon color
        }

        obj._currentColor = color;

        if (obj.type === 'path') {
            obj.set('stroke', color);
        } else if (obj.type === 'i-text' || obj.type === 'text' || obj.type === 'textbox' || obj.type === 'rect') {
            obj.set('fill', color);
        } else if (obj._isColorableSVG) {
            const shapes = obj._objects ? obj._objects : [obj];
            shapes.forEach((shape) => {
                if (shape.fill && !isOutlineColor(shape.fill)) {
                    shape.set('fill', color);
                }
            });
            obj.dirty = true;
        } else if (obj.type === 'image' || obj instanceof fabric.Image) {
            // Apply color filter to raster images
            obj.filters = [
                new fabric.Image.filters.BlendColor({
                    color: color,
                    mode: 'multiply',
                    alpha: 1
                })
            ];
            obj.applyFilters();
        } else if (obj.fill && obj.fill !== 'none') {
            obj.set('fill', color);
        }
    }

    function getUniqueBalloonColors(pendingObj = null, pendingColor = null) {
        const balloons = canvas.getObjects().filter((obj) => {
            const cat = normalizeCategoryName(obj._packageCategory);
            return (cat === 'balloons' || cat === 'balloon') && !obj._isArtboard && !obj._isBgImage;
        });
        const colors = new Set();
        balloons.forEach((obj) => {
            let colorToProcess;
            if (obj === pendingObj && pendingColor) {
                colorToProcess = pendingColor;
            } else {
                colorToProcess = obj._currentColor || (typeof obj.fill === 'string' ? obj.fill : null);
            }

            if (colorToProcess && typeof colorToProcess === 'string') {
                const fillLower = colorToProcess.toLowerCase();
                // Ignore the "transparent" placeholder colors
                if (fillLower !== 'rgba(255, 255, 255, 0.2)' && fillLower !== 'rgba(255, 255, 255, 0.1)' && fillLower !== 'transparent' && fillLower !== 'none' && !fillLower.startsWith('url')) {
                    colors.add(fillLower);
                }
            }
        });
        return Array.from(colors);
    }

    function isSvgSource(src) {
        if (!src || typeof src !== 'string') return false;
        const normalized = src.toLowerCase();
        return (
            normalized.includes('.svg') ||
            normalized.startsWith('data:image/svg+xml') ||
            normalized.includes('image/svg+xml')
        );
    }

    function addRasterImage(data, pointer) {
        fabric.Image.fromURL(
            data.src,
            (img) => {
                if (!img) return;
                const desiredW = data.width || 180;
                const desiredH = data.height || 180;
                const scale = Math.min(desiredW / img.width, desiredH / img.height);
                applyObjectControlStyle(img).set({
                    left: pointer.x,
                    top: pointer.y,
                    originX: 'center',
                    originY: 'center',
                    scaleX: scale,
                    scaleY: scale
                });
                img._packageCategory = data.category || 'custom';
                if (data.fill) {
                    applyColorToObject(img, data.fill);
                }
                canvas.add(img);
                canvas.setActiveObject(img);
                canvas.renderAll();
                updateHintVisibility();
                updateVisualCart();
            },
            { crossOrigin: 'anonymous' }
        );
    }

    function addSvgImage(data, pointer) {
        fabric.loadSVGFromURL(data.src, (objects, options) => {
            if (!objects || !objects.length) {
                addRasterImage(data, pointer);
                return;
            }

            const validObjects = objects.filter(Boolean);
            const grouped = fabric.util.groupSVGElements(validObjects, options);
            const desiredW = data.width || 180;
            const desiredH = data.height || 180;
            const scale = Math.min(desiredW / grouped.width, desiredH / grouped.height);

            applyObjectControlStyle(grouped).set({
                left: pointer.x,
                top: pointer.y,
                originX: 'center',
                originY: 'center',
                scaleX: scale,
                scaleY: scale
            });
            grouped._isColorableSVG = true;
            grouped._packageCategory = data.category || 'custom';
            if (data.fill) {
                applyColorToObject(grouped, data.fill);
            }
            canvas.add(grouped);
            canvas.setActiveObject(grouped);
            canvas.renderAll();
            updateHintVisibility();
            updateVisualCart();
        });
    }

    function addShapeToCanvas(data, pointer) {
        const point = pointer || getArtboardCenterPoint();

        // 1. Validation: Check if we are over the limit for package inclusions
        if (window.packageQuotas) {
            const category = (data.category || 'custom').toLowerCase();
            if (!checkQuota(category)) return;

            // Check balloon color limit when adding
            if (category === 'balloons' || category === 'balloon') {
                // If the user has already picked a color, use it as the default for new drags
                if (lastBalloonColor) {
                    data.fill = lastBalloonColor;
                } else {
                    // Otherwise, make it transparent as a placeholder
                    data.fill = 'rgba(255, 255, 255, 0.2)';
                }
            }
        }

        if (data.type === 'image' && data.src) {
            if (isSvgSource(data.src)) addSvgImage(data, point);
            else addRasterImage(data, point);
            return;
        }

        const commonOptions = {
            left: point.x,
            top: point.y,
            originX: 'center',
            originY: 'center',
            ...objectControlStyle
        };

        let obj = null;
        if (data.type === 'i-text') {
            obj = new fabric.IText(data.text || 'Your text', {
                ...commonOptions,
                fill: data.fill || '#111111',
                fontFamily: data.fontFamily || 'Montserrat',
                fontSize: data.fontSize || 42,
                fontWeight: 'bold'
            });
        } else if (data.type === 'rect') {
            obj = new fabric.Rect({
                ...commonOptions,
                width: data.width || 160,
                height: data.height || 160,
                fill: data.fill || '#202020',
                rx: 6,
                ry: 6
            });
        }

        if (!obj) return;
        obj._packageCategory = data.category || 'custom';
        applyInteractionCursors(obj);
        canvas.add(obj);
        canvas.setActiveObject(obj);
        canvas.renderAll();
        updateHintVisibility();
        updateVisualCart();
    }

    function checkQuota(category) {
        if (!window.packageQuotas) return true;
        
        const normalized = normalizeCategoryName(category);
        if (normalized === 'custom') return true;

        let quotaKey = null;
        if (window.packageQuotas[normalized]) {
            quotaKey = normalized;
        } else {
            const singular = normalized.endsWith('s') ? normalized.slice(0, -1) : normalized;
            const plural = normalized.endsWith('s') ? normalized : normalized + 's';
            
            if (window.packageQuotas[singular]) quotaKey = singular;
            else if (window.packageQuotas[plural]) quotaKey = plural;
        }

        if (quotaKey) {
            const limit = window.packageQuotas[quotaKey];
            const currentCount = canvas.getObjects().filter(obj => 
                (obj._packageCategory === quotaKey || normalizeCategoryName(obj._packageCategory) === quotaKey) 
                && !obj._isArtboard && !obj._isBgImage
            ).length;

            if (currentCount >= limit) {
                // If it's a panel, show upgrade modal
                if (quotaKey === 'panels' || quotaKey === 'panel' || quotaKey === 'backdrop' || quotaKey === 'backdrops') {
                    handlePackageUpgrade(quotaKey, limit);
                } else {
                    showToast(`Limit reached for ${quotaKey}. You can only have ${limit} ${quotaKey}(s) in this package.`, 'error');
                }
                return false;
            }
        }
        return true;
    }

    function handlePackageUpgrade(quotaKey, currentLimit) {
        const upgradeModal = byId('upgradeModal');
        const upgradeMessage = byId('upgradeModalMessage');
        const confirmBtn = byId('confirmUpgradeBtn');
        const cancelBtn = byId('cancelUpgradeBtn');

        if (!upgradeModal || !upgradeMessage || !confirmBtn || !cancelBtn) return;

        // Find a package that allows more of this quotaKey
        const currentPrice = window.basePackagePrice || 0;
        const allPackages = JSON.parse(document.getElementById('allPackagesData').textContent || '[]');
        
        // Filter packages that have a higher limit for this quotaKey and are more expensive
        let nextPackage = null;
        for (const pkg of allPackages) {
            const pkgQuotas = window.allPackageQuotas[pkg.id] || {};
            const pkgLimit = pkgQuotas[quotaKey] || 0;
            
            if (pkgLimit > currentLimit && parseFloat(pkg.price) > currentPrice) {
                if (!nextPackage || parseFloat(pkg.price) < parseFloat(nextPackage.price)) {
                    nextPackage = pkg;
                }
            }
        }

        if (nextPackage) {
            upgradeMessage.innerHTML = `You've used all <strong>${currentLimit} ${quotaKey}(s)</strong> included in your current package. <br><br>Upgrade to <strong>${nextPackage.name}</strong> (P${nextPackage.price}) to use up to <strong>${window.allPackageQuotas[nextPackage.id][quotaKey]} ${quotaKey}(s)</strong>?`;
            
            upgradeModal.style.display = 'flex';

            const onConfirm = () => {
                applyPackage(nextPackage.id);
                upgradeModal.style.display = 'none';
                showToast(`Upgraded to ${nextPackage.name}!`, 'success');
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
            };

            const onCancel = () => {
                upgradeModal.style.display = 'none';
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
            };

            confirmBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
        } else {
            showToast(`Limit reached for ${quotaKey}. No higher package available.`, 'error');
        }
    }

    function handleColorUpgrade(currentLimit) {
        const upgradeModal = byId('upgradeModal');
        const upgradeMessage = byId('upgradeModalMessage');
        const confirmBtn = byId('confirmUpgradeBtn');
        const cancelBtn = byId('cancelUpgradeBtn');

        if (!upgradeModal || !upgradeMessage || !confirmBtn || !cancelBtn) return;

        const currentPrice = window.basePackagePrice || 0;
        const allPackages = JSON.parse(document.getElementById('allPackagesData').textContent || '[]');
        
        let nextPackage = null;
        for (const pkg of allPackages) {
            const pkgQuotas = window.allPackageQuotas[pkg.id] || {};
            const pkgColorLimit = pkgQuotas.balloon_color_limit || 0;
            
            if (pkgColorLimit > currentLimit && parseFloat(pkg.price) > currentPrice) {
                if (!nextPackage || parseFloat(pkg.price) < parseFloat(nextPackage.price)) {
                    nextPackage = pkg;
                }
            }
        }

        if (nextPackage) {
            upgradeMessage.innerHTML = `You've used all <strong>${currentLimit} colors</strong> for balloons included in your current package. <br><br>Upgrade to <strong>${nextPackage.name}</strong> (P${nextPackage.price}) to use up to <strong>${window.allPackageQuotas[nextPackage.id].balloon_color_limit} colors</strong>?`;
            
            upgradeModal.style.display = 'flex';

            const onConfirm = () => {
                applyPackage(nextPackage.id);
                upgradeModal.style.display = 'none';
                showToast(`Upgraded to ${nextPackage.name}!`, 'success');
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
            };

            const onCancel = () => {
                upgradeModal.style.display = 'none';
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
            };

            confirmBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
        } else {
            showToast(`Color limit reached. No higher package available with more colors.`, 'error');
        }
    }

    function applyPackage(pkgId) {
        const packageCards = document.querySelectorAll('.package-selection-card');
        const targetCard = Array.from(packageCards).find(card => card.dataset.packageId == pkgId);
        
        if (targetCard) {
            targetCard.click(); // Use the existing logic
        } else {
            // Fallback if card not found (though it should be)
            const allPackages = JSON.parse(document.getElementById('allPackagesData').textContent || '[]');
            const pkg = allPackages.find(p => p.id == pkgId);
            if (pkg) {
                window.basePackageId = pkg.id;
                window.basePackagePrice = parseFloat(pkg.price);
                window.packageQuotas = window.allPackageQuotas[pkg.id] || {};
                
                const cartBaseName = byId('cartBaseName');
                if (cartBaseName) cartBaseName.textContent = pkg.name;
                
                filterAssetsByPackage();
                updateVisualCart();
            }
        }
    }

    function normalizeCategoryName(cat) {
        if (!cat) return 'custom';
        return String(cat)
            .toLowerCase()
            .replace(/[_/-]+/g, ' ')
            .replace(/[^a-z0-9\s]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function showToast(message, type = 'info') {
        // Simple toast implementation or use existing one if available
        // Based on the UI, it seems there's no built-in toast, but I can alert for now
        // or check if there's a toast container.
        const toastContainer = document.querySelector('.toast-container') || createToastContainer();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <div class="toast-content">
                <i class="fas ${type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i>
                <span>${message}</span>
            </div>
        `;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }, 100);
    }

    function createToastContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    }

    function getDraggableItemPayload(item) {
        if (!item) return null;
        return {
            type: item.getAttribute('data-type') || 'image',
            category: item.getAttribute('data-category') || 'custom',
            src: item.getAttribute('data-src') || '',
            fill: item.getAttribute('data-color') || '',
            width: parseInt(item.getAttribute('data-width') || '0', 10),
            height: parseInt(item.getAttribute('data-height') || '0', 10),
            text: item.getAttribute('data-text') || 'Text',
            fontFamily: item.getAttribute('data-font-family') || 'Montserrat'
        };
    }

    function addDraggableItemToCanvas(item) {
        const payload = getDraggableItemPayload(item);
        if (!payload) return;
        addShapeToCanvas(payload, getArtboardCenterPoint());
    }

    function bindDraggableItem(item) {
        if (!item || item.dataset.dragBound === 'true') return;
        item.dataset.dragBound = 'true';

        if (!item.hasAttribute('tabindex')) item.setAttribute('tabindex', '0');
        if (!item.hasAttribute('role')) item.setAttribute('role', 'button');
        if (!item.hasAttribute('aria-label') && item.getAttribute('title')) {
            item.setAttribute('aria-label', `Add ${item.getAttribute('title')} to canvas`);
        }

        let lastDragStartedAt = 0;

        item.addEventListener('dragstart', (event) => {
            const payload = getDraggableItemPayload(item);
            if (!payload) return;
            lastDragStartedAt = Date.now();
            event.dataTransfer.setData('text/plain', JSON.stringify(payload));
            event.dataTransfer.effectAllowed = 'copy';
        });

        item.addEventListener('click', (event) => {
            if (event.defaultPrevented) return;
            if (Date.now() - lastDragStartedAt < 250) return;
            event.preventDefault();
            addDraggableItemToCanvas(item);
        });

        item.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            addDraggableItemToCanvas(item);
        });
    }

    document.querySelectorAll('.draggable-item').forEach(bindDraggableItem);
    updateDrawLabels();

    drawToolButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            activateDrawTool(btn.dataset.drawTool || 'pen');
        });
    });

    if (disableDrawBtn) {
        disableDrawBtn.addEventListener('click', () => {
            disableDrawingMode();
        });
    }

    if (drawColorInput) {
        drawColorInput.addEventListener('input', () => {
            updateDrawLabels();
            if (canvas.isDrawingMode && currentDrawTool !== 'eraser') applyDrawSettings();
        });
    }

    if (drawSizeInput) {
        drawSizeInput.addEventListener('input', () => {
            applyDrawSettings();
        });
    }

    if (drawOpacityInput) {
        drawOpacityInput.addEventListener('input', () => {
            applyDrawSettings();
        });
    }

    dropZone.addEventListener('dragover', (event) => {
        event.preventDefault();
        dropZone.classList.add('drag-over');
        event.dataTransfer.dropEffect = 'copy';
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (event) => {
        event.preventDefault();
        dropZone.classList.remove('drag-over');

        const raw = event.dataTransfer.getData('text/plain');
        if (!raw) return;

        try {
            const data = JSON.parse(raw);
            const pointer = canvas.getPointer(event);
            addShapeToCanvas(data, pointer);
        } catch (error) {
            console.error('Error while dropping item:', error);
        }
    });

    function deleteSelectedObjects() {
        const selected = getSelectableActiveObjects();
        if (!selected.length) return;

        saveState();
        canvas.discardActiveObject();
        selected.forEach((obj) => canvas.remove(obj));
        canvas.renderAll();
        updateHintVisibility();
        updateVisualCart();
        updateControlsState();
    }

    function toggleLockSelection() {
        const selected = getSelectableActiveObjects();
        if (!selected.length) return;

        const shouldLock = selected.some((obj) => !obj._isLocked);
        saveState();
        selected.forEach((obj) => syncLockState(obj, shouldLock));
        canvas.renderAll();
        updateControlsState();
    }

    if (layerUpBtn) {
        layerUpBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => obj.bringForward());
            canvas.renderAll();
            updateContextToolbar();
        });
    }

    if (layerDownBtn) {
        layerDownBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => {
                const index = canvas.getObjects().indexOf(obj);
                if (index > 1) obj.sendBackwards();
            });
            canvas.renderAll();
            updateContextToolbar();
        });
    }

    if (toFrontBtn) {
        toFrontBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => canvas.bringToFront(obj));
            canvas.renderAll();
            updateContextToolbar();
        });
    }

    if (toBackBtn) {
        toBackBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => {
                canvas.sendToBack(obj);
                canvas.moveTo(obj, 1);
            });
            canvas.renderAll();
            updateContextToolbar();
        });
    }

    if (flipXBtn) {
        flipXBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => obj.set('flipX', !obj.flipX));
            canvas.renderAll();
        });
    }

    if (flipYBtn) {
        flipYBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => obj.set('flipY', !obj.flipY));
            canvas.renderAll();
        });
    }

    if (skewLeftBtn) {
        skewLeftBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => obj.set('skewX', (obj.skewX || 0) - 5));
            canvas.renderAll();
        });
    }

    if (skewRightBtn) {
        skewRightBtn.addEventListener('click', () => {
            const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
            if (!selected.length) return;
            saveState();
            selected.forEach((obj) => obj.set('skewX', (obj.skewX || 0) + 5));
            canvas.renderAll();
        });
    }

    if (rotateLeftBtn) {
        rotateLeftBtn.addEventListener('click', () => {
            rotateSelectedObjects(-15);
        });
    }

    if (rotateRightBtn) {
        rotateRightBtn.addEventListener('click', () => {
            rotateSelectedObjects(15);
        });
    }

    if (moveUpBtn) {
        moveUpBtn.addEventListener('click', () => {
            nudgeSelectedObjects(0, -5);
        });
    }

    if (moveDownBtn) {
        moveDownBtn.addEventListener('click', () => {
            nudgeSelectedObjects(0, 5);
        });
    }

    if (moveLeftBtn) {
        moveLeftBtn.addEventListener('click', () => {
            nudgeSelectedObjects(-5, 0);
        });
    }

    if (moveRightBtn) {
        moveRightBtn.addEventListener('click', () => {
            nudgeSelectedObjects(5, 0);
        });
    }

    if (lockBtn) {
        lockBtn.addEventListener('click', () => {
            toggleLockSelection();
        });
    }

    if (cloneBtn) {
        cloneBtn.addEventListener('click', () => {
            const activeObj = getSingleActiveObject();
            if (!activeObj || activeObj._isLocked) return;

            // Check quota before cloning
            if (!checkQuota(activeObj._packageCategory || 'custom')) return;

            activeObj.clone((cloned) => {
                saveState();
                canvas.discardActiveObject();
                cloned.set({
                    left: activeObj.left + 22,
                    top: activeObj.top + 22,
                    evented: true
                });
                canvas.add(cloned);
                canvas.setActiveObject(cloned);
                canvas.renderAll();
                updateHintVisibility();
                updateVisualCart();
                updateControlsState();
            });
        });
    }

    if (deleteBtn) {
        deleteBtn.addEventListener('click', deleteSelectedObjects);
    }

    if (contextDuplicateBtn) {
        contextDuplicateBtn.addEventListener('click', () => {
            if (cloneBtn && !cloneBtn.disabled) cloneBtn.click();
        });
    }
    if (contextLockBtn) {
        contextLockBtn.addEventListener('click', () => {
            if (lockBtn && !lockBtn.disabled) lockBtn.click();
        });
    }
    if (contextBringFrontBtn) {
        contextBringFrontBtn.addEventListener('click', () => {
            if (toFrontBtn && !toFrontBtn.disabled) toFrontBtn.click();
        });
    }
    if (contextRotateLeftBtn) {
        contextRotateLeftBtn.addEventListener('click', () => {
            if (rotateLeftBtn && !rotateLeftBtn.disabled) rotateLeftBtn.click();
        });
    }
    if (contextRotateRightBtn) {
        contextRotateRightBtn.addEventListener('click', () => {
            if (rotateRightBtn && !rotateRightBtn.disabled) rotateRightBtn.click();
        });
    }
    if (contextMoveUpBtn) {
        contextMoveUpBtn.addEventListener('click', () => {
            if (moveUpBtn && !moveUpBtn.disabled) moveUpBtn.click();
        });
    }
    if (contextMoveDownBtn) {
        contextMoveDownBtn.addEventListener('click', () => {
            if (moveDownBtn && !moveDownBtn.disabled) moveDownBtn.click();
        });
    }
    if (contextMoveLeftBtn) {
        contextMoveLeftBtn.addEventListener('click', () => {
            if (moveLeftBtn && !moveLeftBtn.disabled) moveLeftBtn.click();
        });
    }
    if (contextMoveRightBtn) {
        contextMoveRightBtn.addEventListener('click', () => {
            if (moveRightBtn && !moveRightBtn.disabled) moveRightBtn.click();
        });
    }
    if (contextDeleteBtn) {
        contextDeleteBtn.addEventListener('click', () => {
            deleteSelectedObjects();
        });
    }

    if (undoBtn) {
        undoBtn.addEventListener('click', () => {
            if (!undoStack.length) return;
            redoStack.push(getCurrentState());
            const previous = undoStack.pop();
            restoreCanvasState(previous);
        });
    }

    if (redoBtn) {
        redoBtn.addEventListener('click', () => {
            if (!redoStack.length) return;
            undoStack.push(getCurrentState());
            const next = redoStack.pop();
            restoreCanvasState(next);
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            const objects = canvas.getObjects().filter((obj) => !obj._isArtboard);
            if (!objects.length) return;
            if (!confirm('Clear all objects from the canvas?')) return;

            saveState();
            objects.forEach((obj) => canvas.remove(obj));
            canvas.discardActiveObject();
            canvas.renderAll();
            updateHintVisibility();
            updateVisualCart();
            updateControlsState();
        });
    }

    if (zoomInBtn) zoomInBtn.addEventListener('click', () => zoomCenter(canvas.getZoom() * 1.2));
    if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => zoomCenter(canvas.getZoom() / 1.2));
    if (zoomResetBtn) zoomResetBtn.addEventListener('click', () => fitArtboardToView());
    if (zoomRange) {
        zoomRange.addEventListener('input', () => {
            zoomCenter((parseInt(zoomRange.value, 10) || 100) / 100);
        });
    }

    if (itemColorPicker) {
        itemColorPicker.addEventListener('input', (event) => {
            const selected = getSelectableActiveObjects();
            if (!selected.length) return;
            selected.forEach((obj) => applyColorToObject(obj, event.target.value));
            canvas.renderAll();
        });
        itemColorPicker.addEventListener('change', () => saveState());
    }

    document.querySelectorAll('.color-swatch').forEach((swatch) => {
        swatch.addEventListener('click', () => {
            const color = swatch.dataset.color;
            document.querySelectorAll('.color-swatch').forEach((node) => node.classList.remove('active'));
            swatch.classList.add('active');

            const selected = getSelectableActiveObjects();
            if (selected.length) {
                selected.forEach((obj) => applyColorToObject(obj, color));
            } else {
                artboard.set('fill', color);
            }
            canvas.renderAll();
            if (canvas.isDrawingMode) applyDrawSettings();
            saveState();
        });
    });

    if (customCanvasColor) {
        customCanvasColor.addEventListener('input', (event) => {
            const color = event.target.value;
            const selected = getSelectableActiveObjects();
            if (selected.length) {
                selected.forEach((obj) => applyColorToObject(obj, color));
            } else {
                artboard.set('fill', color);
            }
            canvas.renderAll();
            if (canvas.isDrawingMode) applyDrawSettings();
        });
        customCanvasColor.addEventListener('change', () => saveState());
    }

    if (bgImageUpload) {
        bgImageUpload.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = (loadEvent) => {
                fabric.Image.fromURL(loadEvent.target.result, (img) => {
                    if (!img) return;

                    const scale = Math.max(ARTBOARD_W / img.width, ARTBOARD_H / img.height);
                    img.set({
                        left: artboard.left,
                        top: artboard.top,
                        originX: 'left',
                        originY: 'top',
                        scaleX: scale,
                        scaleY: scale,
                        selectable: false,
                        evented: false,
                        _isBgImage: true
                    });

                    canvas.getObjects().forEach((obj) => {
                        if (obj._isBgImage) canvas.remove(obj);
                    });
                    canvas.insertAt(img, 1);
                    canvas.renderAll();
                    saveState();
                    updateHintVisibility();
                });
            };
            reader.readAsDataURL(file);
            bgImageUpload.value = '';
        });
    }

    if (removeBgImage) {
        removeBgImage.addEventListener('click', () => {
            const hasBg = canvas.getObjects().some((obj) => obj._isBgImage);
            if (!hasBg) return;
            saveState();
            canvas.getObjects().forEach((obj) => {
                if (obj._isBgImage) canvas.remove(obj);
            });
            canvas.renderAll();
            updateHintVisibility();
        });
    }

    function applyElemWidth() {
        const active = getSingleActiveObject();
        if (!active || active._isLocked || !elemWidthInput) return;
        const newWidth = parseInt(elemWidthInput.value, 10) || 1;
        saveState();
        active.scaleX = newWidth / active.width;
        active.setCoords();
        canvas.renderAll();
        updateContextToolbar();
    }

    function applyElemHeight() {
        const active = getSingleActiveObject();
        if (!active || active._isLocked || !elemHeightInput) return;
        const newHeight = parseInt(elemHeightInput.value, 10) || 1;
        saveState();
        active.scaleY = newHeight / active.height;
        active.setCoords();
        canvas.renderAll();
        updateContextToolbar();
    }

    if (elemWidthInput) {
        elemWidthInput.addEventListener('change', applyElemWidth);
        elemWidthInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') applyElemWidth();
        });
    }

    if (elemHeightInput) {
        elemHeightInput.addEventListener('change', applyElemHeight);
        elemHeightInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') applyElemHeight();
        });
    }

    function applyToActiveTextObjects(mutator) {
        const textObjects = getActiveTextObjects().filter((obj) => !obj._isLocked);
        if (!textObjects.length) return;
        saveState();
        textObjects.forEach(mutator);
        canvas.renderAll();
        updateTextControlsUI();
    }

    if (fontFamilySelect) {
        fontFamilySelect.addEventListener('change', () => {
            const font = fontFamilySelect.value;
            if (!font) return;
            applyToActiveTextObjects((obj) => obj.set('fontFamily', font));
        });
    }

    if (fontSizeInput) {
        const applyFontSize = () => {
            const size = parseInt(fontSizeInput.value, 10);
            if (!size || size < 8) return;
            applyToActiveTextObjects((obj) => obj.set('fontSize', size));
        };
        fontSizeInput.addEventListener('change', applyFontSize);
        fontSizeInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') applyFontSize();
        });
    }

    if (textBoldBtn) {
        textBoldBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => {
                const isBold = obj.fontWeight === 'bold' || Number(obj.fontWeight) >= 600;
                obj.set('fontWeight', isBold ? 'normal' : 'bold');
            });
        });
    }

    if (textItalicBtn) {
        textItalicBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => obj.set('fontStyle', obj.fontStyle === 'italic' ? 'normal' : 'italic'));
        });
    }

    if (textUnderlineBtn) {
        textUnderlineBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => obj.set('underline', !obj.underline));
        });
    }

    if (textAlignLeftBtn) {
        textAlignLeftBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => obj.set('textAlign', 'left'));
        });
    }
    if (textAlignCenterBtn) {
        textAlignCenterBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => obj.set('textAlign', 'center'));
        });
    }
    if (textAlignRightBtn) {
        textAlignRightBtn.addEventListener('click', () => {
            applyToActiveTextObjects((obj) => obj.set('textAlign', 'right'));
        });
    }

    function addQuickTextToCanvas() {
        const textValue = (quickTextInput && quickTextInput.value ? quickTextInput.value : '').trim() || 'Your text';
        addShapeToCanvas(
            {
                type: 'i-text',
                text: textValue,
                fill: '#111111',
                fontFamily: fontFamilySelect && fontFamilySelect.value ? fontFamilySelect.value : 'Montserrat',
                fontSize: fontSizeInput ? parseInt(fontSizeInput.value, 10) || 42 : 42
            },
            getArtboardCenterPoint()
        );
    }

    if (addTextBtn) addTextBtn.addEventListener('click', addQuickTextToCanvas);
    if (quickTextInput) {
        quickTextInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                addQuickTextToCanvas();
            }
        });
    }

    if (applySizeBtn && canvasWidthInput && canvasHeightInput) {
        const applyCanvasSizeFromInputs = () => {
            const nextW = parseInt(canvasWidthInput.value, 10) || ARTBOARD_W;
            const nextH = parseInt(canvasHeightInput.value, 10) || ARTBOARD_H;
            if (nextW < 100 || nextH < 100 || nextW > 5000 || nextH > 5000) {
                alert('Canvas size must be between 100 and 5000 pixels.');
                return;
            }

            applyArtboardSize(nextW, nextH, { saveHistory: true, fitToView: true });
        };

        applySizeBtn.addEventListener('click', applyCanvasSizeFromInputs);

        [canvasWidthInput, canvasHeightInput].forEach((input) => {
            input.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                applyCanvasSizeFromInputs();
            });
        });
    }

    if (userUploadInput && userUploadsGrid) {
        userUploadInput.addEventListener('change', (event) => {
            Array.from(event.target.files).forEach((file) => {
                if (!file.type.startsWith('image/')) return;
                const reader = new FileReader();
                reader.onload = (loadEvent) => {
                    const dataUrl = loadEvent.target.result;
                    const node = document.createElement('div');
                    node.className = 'draggable-item';
                    node.draggable = true;
                    node.dataset.type = 'image';
                    node.dataset.src = dataUrl;
                    node.dataset.width = '180';
                    node.dataset.height = '180';
                    node.title = file.name;
                    node.innerHTML = `<div class="item-preview-img-wrapper"><img class="item-preview-img" src="${dataUrl}" alt="${file.name}"></div>`;
                    bindDraggableItem(node);
                    userUploadsGrid.prepend(node);
                };
                reader.readAsDataURL(file);
            });

            userUploadInput.value = '';
        });
    }

    if (saveDesignBtn) {
        saveDesignBtn.addEventListener('click', async () => {
            const nonArtboard = canvas.getObjects().filter((obj) => !obj._isArtboard);
            if (!nonArtboard.length) {
                alert('The canvas is empty. Add some elements first.');
                return;
            }

            canvas.discardActiveObject();
            canvas.renderAll();

            const originalVpt = canvas.viewportTransform.slice();
            canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
            canvas.renderAll();

            const thumbnail = canvas.toDataURL({
                format: 'png',
                quality: 0.8,
                multiplier: 2,
                left: artboard.left,
                top: artboard.top,
                width: ARTBOARD_W,
                height: ARTBOARD_H
            });

            canvas.setViewportTransform(originalVpt);
            canvas.renderAll();

            let designName = 'My Balloon Setup';
            if (!window.currentDesignId) {
                const prompted = prompt('Enter a name for your design:', 'My Balloon Setup');
                if (prompted === null) return;
                if (prompted.trim()) designName = prompted.trim();
            } else {
                designName = '';
            }

            const originalHtml = saveDesignBtn.innerHTML;
            saveDesignBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
            saveDesignBtn.disabled = true;

            try {
                const csrfTokenNode = document.querySelector('[name=csrfmiddlewaretoken]');
                const csrfToken = csrfTokenNode ? csrfTokenNode.value : '';

                const response = await fetch('/my-designs/save/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({
                        id: window.currentDesignId || null,
                        name: designName,
                        canvas_json: getCurrentState(),
                        thumbnail: thumbnail,
                        base_package_id: window.basePackageId || null
                    })
                });

                const result = await response.json();
                if (result.status === 'success') {
                    alert('Design saved successfully!');
                    window.location.href = '/my-designs/';
                    return;
                }

                alert(`Error saving design: ${result.message || 'Unknown error'}`);
            } catch (error) {
                console.error('Save error:', error);
                alert('Network error. Could not save design.');
            } finally {
                saveDesignBtn.innerHTML = originalHtml;
                saveDesignBtn.disabled = false;
            }
        });
    }

    function getAddonPrice(category) {
        const matchKey = Object.keys(window.addonPrices || {}).find((key) =>
            key.toLowerCase().includes(category)
        );
        if (matchKey && window.addonPrices[matchKey]) return parseFloat(window.addonPrices[matchKey]);

        const fallback = {
            arch: 1500,
            backdrop: 2000,
            plinths: 500,
            balloons: 15,
            florals: 800,
            neon: 1200,
            custom: 100
        };
        return fallback[category] || 100;
    }

    function generateCartLabel(category) {
        // Capitalize first letter
        if (!category) return 'Custom Item';
        return category.charAt(0).toUpperCase() + category.slice(1);
    }

    function updateVisualCart() {
        if (!cartAddonsList || !cartTotalPrice) return;

        const objects = canvas.getObjects().filter((obj) => !obj._isArtboard && !obj._isBgImage);
        const counts = {};
        objects.forEach((obj) => {
            const category = normalizeCategoryName(obj._packageCategory || 'custom');
            counts[category] = (counts[category] || 0) + 1;
        });

        if (cartInclusionsList) cartInclusionsList.innerHTML = '';
        cartAddonsList.innerHTML = '';

        let totalAddonPrice = window.basePackagePrice || 0;
        let hasAddons = false;

        if (window.basePackageId && window.packageQuotas) {
            Object.keys(window.packageQuotas).forEach((quotaKey) => {
                if (quotaKey === 'balloon_color_limit') return; // Skip color limit in the summary list
                
                const limit = window.packageQuotas[quotaKey] || 0;
                
                // Find count for this quotaKey, considering singular/plural and partial matches
                let used = 0;
                const quotaLower = quotaKey.toLowerCase().trim();
                const quotaSingular = quotaLower.endsWith('s') ? quotaLower.slice(0, -1) : quotaLower;
                const quotaPlural = quotaLower.endsWith('s') ? quotaLower : quotaLower + 's';
                
                Object.keys(counts).forEach(catKey => {
                    const catLower = catKey.toLowerCase().trim();
                    const catSingular = catLower.endsWith('s') ? catLower.slice(0, -1) : catLower;
                    const catPlural = catLower.endsWith('s') ? catLower : catLower + 's';

                    // Flexible matching logic
                    const isMatch = 
                        catLower === quotaLower || 
                        catLower === quotaSingular || 
                        catLower === quotaPlural ||
                        quotaLower === catSingular || 
                        quotaLower === catPlural ||
                        (quotaLower.includes(catSingular) && catSingular.length > 3) ||
                        (catLower.includes(quotaSingular) && quotaSingular.length > 3) ||
                        // Specific common synonyms
                        (quotaLower.includes('panel') && catLower.includes('backdrop')) ||
                        (quotaLower.includes('backdrop') && catLower.includes('panel')) ||
                        (quotaLower.includes('flower') && catLower.includes('floral')) ||
                        (quotaLower.includes('floral') && catLower.includes('flower'));

                    if (isMatch) {
                        used += counts[catKey];
                        delete counts[catKey];
                    }
                });

                if (cartInclusionsList) {
                    const inclusionNode = document.createElement('li');
                    const isChecked = limit === -1 || used >= limit;
                    
                    let statusHtml = '';
                    if (limit === -1) {
                        statusHtml = 'Included';
                    } else {
                        const displayLimit = limit >= 999 ? '∞' : limit;
                        const displayUsed = limit >= 999 ? used : Math.min(used, limit);
                        statusHtml = `${displayUsed} / ${displayLimit}`;
                    }
                    
                    let nameHtml = generateCartLabel(quotaKey);
                    
                    // Display non-numeric inclusions more cleanly
                    if (limit === -1) {
                        // If it's a long text inclusion, just use it as is or title case it
                        nameHtml = quotaKey.length > 20 ? quotaKey : generateCartLabel(quotaKey);
                    }

                    if (quotaKey === 'balloons' || quotaKey === 'balloon') {
                        const colorLimit = window.packageQuotas.balloon_color_limit || 2;
                        nameHtml += ` <small style="display:block; font-size:0.7rem; color:var(--editor-text-soft); font-weight:normal;">(Max ${colorLimit} colors)</small>`;
                    }
                    
                    inclusionNode.innerHTML = `
                        <div class="inclusion-item ${isChecked ? 'checked' : ''}">
                            <span class="inclusion-name">${nameHtml}</span>
                            <span class="inclusion-status">${statusHtml}</span>
                        </div>
                    `;
                    cartInclusionsList.appendChild(inclusionNode);
                }

                if (limit !== -1 && used > limit && limit < 999) {
                    const excess = used - limit;
                    const cost = excess * getAddonPrice(quotaKey);
                    totalAddonPrice += cost;
                    hasAddons = true;

                    const addonNode = document.createElement('li');
                    addonNode.innerHTML = `<span>Extra ${generateCartLabel(quotaKey)} (x${excess})</span> <span>P${cost.toFixed(2)}</span>`;
                    cartAddonsList.appendChild(addonNode);
                }
            });
        }

        Object.keys(counts).forEach((category) => {
            const used = counts[category];
            if (used <= 0 || category === 'custom') return;

            const price = getAddonPrice(category);
            if (price <= 0) return;

            const cost = used * price;
            totalAddonPrice += cost;
            hasAddons = true;

            const addonNode = document.createElement('li');
            addonNode.innerHTML = `<span>${generateCartLabel(category)} (x${used})</span> <span>P${cost.toFixed(2)}</span>`;
            cartAddonsList.appendChild(addonNode);
        });

        if (!hasAddons) {
            cartAddonsList.innerHTML = '<li class="empty-list" style="color:#98a2b3;font-style:italic;">No extra items yet.</li>';
        }
        cartTotalPrice.textContent = `P${totalAddonPrice.toFixed(2)}`;
    }

    canvas.on('object:added', (event) => {
        const obj = event.target;
        if (obj && obj._isArtboard) {
            obj.sendToBack();
        } else {
            // Ensure artboards are always at the back
            canvas.getObjects().forEach(o => {
                if (o._isArtboard) o.sendToBack();
            });
        }

        if (obj && obj.type === 'path') {
            obj._packageCategory = 'custom';
            obj.set({
                fill: '',
                strokeLineCap: 'round',
                strokeLineJoin: 'round'
            });
            applyObjectControlStyle(obj);
        } else if (obj && !obj._isArtboard && !obj._isBgImage) {
            applyInteractionCursors(obj);
        }

        if (!isLoadingState && obj && !obj._isArtboard) {
            saveState();
            updateHintVisibility();
            updateVisualCart();
            updateControlsState();
        }
    });

    canvas.on('mouse:wheel', (opt) => {
        const event = opt.e;
        event.preventDefault();
        event.stopPropagation();

        // Always zoom on wheel scroll, never pan.
        // The artboard itself is fixed in place (non-draggable) and only resizable.
        let zoom = canvas.getZoom();
        zoom *= 0.997 ** event.deltaY;
        zoomToPoint(new fabric.Point(event.offsetX, event.offsetY), zoom);
    });

    document.addEventListener('keydown', (event) => {
        if (!ENABLE_VIEWPORT_PAN) return;
        if (event.code === 'Space' && event.target.tagName !== 'INPUT' && event.target.tagName !== 'TEXTAREA') {
            if (canvas.getActiveObject() && canvas.getActiveObject().isEditing) return;
            event.preventDefault();
            isSpaceDown = true;
            canvas.defaultCursor = 'grab';
            canvas.setCursor('grab');
            canvas.selection = false;
        }
    });

    document.addEventListener('keyup', (event) => {
        if (!ENABLE_VIEWPORT_PAN) return;
        if (event.code === 'Space') {
            isSpaceDown = false;
            canvas.defaultCursor = 'default';
            canvas.setCursor('default');
            canvas.selection = true;
        }
    });

    canvas.on('mouse:down', (opt) => {
        if (opt.e.button === 1) {
            opt.e.preventDefault();
            opt.e.stopPropagation();
            return;
        }
        if (!ENABLE_VIEWPORT_PAN) return;
        if (opt.e.altKey || opt.e.button === 1 || isSpaceDown) {
            isPanning = true;
            lastPanPos = { x: opt.e.clientX, y: opt.e.clientY };
            canvas.selection = false;
            canvas.defaultCursor = 'grabbing';
            canvas.setCursor('grabbing');
        }
    });

    canvas.on('mouse:move', (opt) => {
        if (!ENABLE_VIEWPORT_PAN) return;
        if (!isPanning) return;
        const dx = opt.e.clientX - lastPanPos.x;
        const dy = opt.e.clientY - lastPanPos.y;
        canvas.relativePan(new fabric.Point(dx, dy));
        clampPan();
        lastPanPos = { x: opt.e.clientX, y: opt.e.clientY };
        updateContextToolbar();
    });

    canvas.on('mouse:up', () => {
        if (!ENABLE_VIEWPORT_PAN) return;
        if (!isPanning) return;
        isPanning = false;
        if (!isSpaceDown) {
            canvas.selection = true;
            canvas.defaultCursor = 'default';
        } else {
            canvas.defaultCursor = 'grab';
            canvas.setCursor('grab');
        }
    });

    canvas.on('selection:created', updateControlsState);
    canvas.on('selection:updated', updateControlsState);
    canvas.on('selection:cleared', updateControlsState);

    canvas.on('object:modified', (event) => {
        if (event.target && event.target._isArtboard) {
            commitArtboardResizeFromTransform();
            return;
        }

        if (!isLoadingState && event.target && !event.target._isArtboard) {
            saveState();
            updateVisualCart();
            updateControlsState();
        }
    });

    canvas.on('object:scaling', () => {
        if (artboard === canvas.getActiveObject()) {
            const scaledW = Math.round((artboard.width || ARTBOARD_W) * (artboard.scaleX || 1));
            const scaledH = Math.round((artboard.height || ARTBOARD_H) * (artboard.scaleY || 1));
            if (canvasWidthInput) canvasWidthInput.value = scaledW;
            if (canvasHeightInput) canvasHeightInput.value = scaledH;
            if (canvasSizeDisp) canvasSizeDisp.textContent = `Canvas: ${scaledW} x ${scaledH}`;
        }
        updateElementSizeInputs();
        updateContextToolbar();
    });
    canvas.on('object:moving', updateContextToolbar);
    canvas.on('object:rotating', updateContextToolbar);

    document.addEventListener('keydown', (event) => {
        const tag = (event.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (canvas.getActiveObject() && canvas.getActiveObject().isEditing) return;

        if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault();
            deleteSelectedObjects();
            return;
        }

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') {
            event.preventDefault();
            if (cloneBtn && !cloneBtn.disabled) cloneBtn.click();
            return;
        }

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
            event.preventDefault();
            if (undoBtn && !undoBtn.disabled) undoBtn.click();
            return;
        }

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
            event.preventDefault();
            if (redoBtn && !redoBtn.disabled) redoBtn.click();
            return;
        }

        if ((event.ctrlKey || event.metaKey) && (event.key === '=' || event.key === '+')) {
            event.preventDefault();
            zoomCenter(canvas.getZoom() * 1.2);
            return;
        }

        if ((event.ctrlKey || event.metaKey) && event.key === '-') {
            event.preventDefault();
            zoomCenter(canvas.getZoom() / 1.2);
            return;
        }

        if ((event.ctrlKey || event.metaKey) && event.key === '0') {
            event.preventDefault();
            fitArtboardToView();
            return;
        }

        const arrowKeys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
        if (!arrowKeys.includes(event.key)) return;

        const selected = getSelectableActiveObjects().filter((obj) => !obj._isLocked);
        if (!selected.length) return;
        event.preventDefault();

        const step = event.shiftKey ? 10 : 1;
        saveState();

        selected.forEach((obj) => {
            if (event.key === 'ArrowUp') obj.top -= step;
            if (event.key === 'ArrowDown') obj.top += step;
            if (event.key === 'ArrowLeft') obj.left -= step;
            if (event.key === 'ArrowRight') obj.left += step;
            obj.setCoords();
        });

        canvas.renderAll();
        updateContextToolbar();
    });

    window.addEventListener('resize', () => {
        canvas.setWidth(dropZone.clientWidth);
        canvas.setHeight(dropZone.clientHeight);
        fitArtboardToView();
    });

    setTimeout(() => {
        fitArtboardToView();
        updateCanvasSizeDisplay();
        if (window.savedCanvasJson) {
            try {
                const jsonStr =
                    typeof window.savedCanvasJson === 'string'
                        ? window.savedCanvasJson
                        : JSON.stringify(window.savedCanvasJson);
                restoreCanvasState(jsonStr);
            } catch (error) {
                console.error('Failed to load saved canvas json:', error);
            }
        } else {
            updateHintVisibility();
            updateControlsState();
            updateVisualCart();
        }
    }, 100);

    updateUndoRedoBtnState();
    updateHintVisibility();
    updateControlsState();
    updateVisualCart();
    filterAssetsByPackage();
});
