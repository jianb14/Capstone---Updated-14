// static/js/design_canvas.js

document.addEventListener('DOMContentLoaded', function() {
    // ===== CONFIG =====
    let ARTBOARD_W = 1920;   // Artboard width in px  (landscape 16:9)
    let ARTBOARD_H = 1080;   // Artboard height in px
    const MIN_ZOOM = 0.15;
    const MAX_ZOOM = 3;

    // 1. Initialize Fabric.js Canvas
    const dropZone = document.getElementById('canvasDropZone');
    const dropHint = document.getElementById('dropHint');
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    const customCanvasColor = document.getElementById('customCanvasColor');
    const bgImageUpload = document.getElementById('bgImageUpload');
    const removeBgImage = document.getElementById('removeBgImage');
    const elemWidthInput = document.getElementById('elemWidthInput');
    const elemHeightInput = document.getElementById('elemHeightInput');
    const applySizeBtn = document.getElementById('applySizeBtn');
    const canvasWidthInput = document.getElementById('canvasWidthInput');
    const canvasHeightInput = document.getElementById('canvasHeightInput');
    const canvasSizeDisp = document.getElementById('canvasSizeDisp');
    const cartInclusionsList = document.getElementById('cartInclusionsList');
    const cartAddonsList = document.getElementById('cartAddonsList');
    const cartTotalPrice = document.getElementById('cartTotalPrice');
    
    const width = dropZone.clientWidth;
    const height = dropZone.clientHeight;
    
    const canvas = new fabric.Canvas('designCanvas', {
        width: width,
        height: height,
        selection: true,
        preserveObjectStacking: true,
        backgroundColor: 'transparent',  // let the CSS background show through
    });

    const undoStack = [];
    const redoStack = [];
    const MAX_UNDO = 30;
    let isLoadingState = false;

    function getCurrentState() {
        return JSON.stringify(canvas.toJSON(['_isArtboard', '_isColorableSVG', '_isLocked', '_packageCategory', '_isBgImage']));
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

    function restoreCanvasState(state) {
        isLoadingState = true;
        canvas.loadFromJSON(state, function() {
            canvas.getObjects().forEach(obj => {
                if (obj._isArtboard) {
                    obj.selectable = false;
                    obj.evented = false;
                }
                if (obj._isLocked) {
                    obj.set({
                        lockMovementX: true,
                        lockMovementY: true,
                        lockRotation: true,
                        lockScalingX: true,
                        lockScalingY: true,
                        hasControls: false,
                        hoverCursor: 'not-allowed',
                        opacity: 0.75
                    });
                }
            });
            canvas.renderAll();
            isLoadingState = false;
            updateHintVisibility();
            updateControlsState();
            updateUndoRedoBtnState();
            updateVisualCart();
        });
    }

    // ===== ARTBOARD (the white "paper") =====
    const artboard = new fabric.Rect({
        width: ARTBOARD_W,
        height: ARTBOARD_H,
        fill: '#ffffff',
        shadow: new fabric.Shadow({
            color: 'rgba(0,0,0,0.35)',
            blur: 30,
            offsetX: 0,
            offsetY: 5
        }),
        selectable: false,
        evented: false,
        excludeFromExport: false,
        hoverCursor: 'default',
        rx: 0,
        ry: 0,
    });
    // Tag it so we can identify it
    artboard._isArtboard = true;
    canvas.add(artboard);

    // Center the artboard and set initial zoom
    function fitArtboardToView() {
        // Calculate zoom needed to fit width and height with 5% padding
        const zoomX = (canvas.getWidth() * 0.95) / ARTBOARD_W;
        const zoomY = (canvas.getHeight() * 0.95) / ARTBOARD_H;
        let zoom = Math.min(zoomX, zoomY); 
        
        // Clamp zoom so it doesn't get ridiculously small or large
        zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
        
        canvas.setZoom(zoom);
        
        // Calculate viewport width and height at 1x zoom
        const vpw = canvas.getWidth();
        const vph = canvas.getHeight();
        
        // Center the artboard within the unzoomed viewport dimensions
        const abLeft = (vpw - (ARTBOARD_W * zoom)) / 2;
        const abTop = (vph - (ARTBOARD_H * zoom)) / 2;
        
        artboard.set({ 
            left: abLeft / zoom, 
            top: abTop / zoom 
        });
        
        // Reset pan (vpt[4] and vpt[5]) to 0 when fitting
        const vpt = canvas.viewportTransform;
        vpt[4] = 0;
        vpt[5] = 0;
        canvas.setViewportTransform(vpt);
        
        artboard.setCoords();
        canvas.renderAll();
        updateZoomLabel();
    }
    
    // Run initial fit + load saved state if editing
    setTimeout(() => {
        fitArtboardToView();
        if (window.savedCanvasJson) {
            try {
                const jsonStr = typeof window.savedCanvasJson === 'string'
                    ? window.savedCanvasJson
                    : JSON.stringify(window.savedCanvasJson);
                restoreCanvasState(jsonStr);
            } catch (err) {
                console.error('Failed to load saved canvas json:', err);
            }
        }
    }, 100);

    // ===== ZOOM CONTROLS =====
    const zoomLabel = document.getElementById('zoomLabel');
    
    function updateZoomLabel() {
        if (zoomLabel) {
            zoomLabel.textContent = Math.round(canvas.getZoom() * 100) + '%';
        }
    }

    function zoomToPoint(point, newZoom) {
        newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom));
        canvas.zoomToPoint(point, newZoom);
        canvas.renderAll();
        updateZoomLabel();
    }

    function zoomCenter(newZoom) {
        const center = new fabric.Point(canvas.getWidth() / 2, canvas.getHeight() / 2);
        zoomToPoint(center, newZoom);
    }

    // Zoom buttons
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    const zoomResetBtn = document.getElementById('zoomResetBtn');

    if (zoomInBtn) {
        zoomInBtn.addEventListener('click', () => {
            zoomCenter(canvas.getZoom() * 1.2);
        });
    }
    if (zoomOutBtn) {
        zoomOutBtn.addEventListener('click', () => {
            zoomCenter(canvas.getZoom() / 1.2);
        });
    }
    if (zoomResetBtn) {
        zoomResetBtn.addEventListener('click', () => {
            fitArtboardToView();
        });
    }

    // ===== PAN LIMITS — Keep artboard visible =====
    function clampPan() {
        const zoom = canvas.getZoom();
        const vpt = canvas.viewportTransform;
        const canvasW = canvas.getWidth();
        const canvasH = canvas.getHeight();

        // Artboard bounds in screen space
        const abLeft = artboard.left * zoom + vpt[4];
        const abTop = artboard.top * zoom + vpt[5];
        const abRight = abLeft + ARTBOARD_W * zoom;
        const abBottom = abTop + ARTBOARD_H * zoom;

        // Allow some margin (200px) beyond the artboard edges
        const margin = 200;

        // Clamp: artboard right edge can't go further left than margin
        if (abRight < margin) {
            vpt[4] += (margin - abRight);
        }
        // Clamp: artboard left edge can't go further right than (canvasW - margin)
        if (abLeft > canvasW - margin) {
            vpt[4] -= (abLeft - (canvasW - margin));
        }
        // Clamp: artboard bottom edge can't go further up than margin
        if (abBottom < margin) {
            vpt[5] += (margin - abBottom);
        }
        // Clamp: artboard top edge can't go further down than (canvasH - margin)
        if (abTop > canvasH - margin) {
            vpt[5] -= (abTop - (canvasH - margin));
        }

        canvas.setViewportTransform(vpt);
    }

    // ===== SCROLL / WHEEL HANDLING (Laptop Trackpad Friendly) =====
    // Ctrl + scroll = ZOOM
    // Normal scroll = PAN UP/DOWN
    // Shift + scroll = PAN LEFT/RIGHT
    canvas.on('mouse:wheel', function(opt) {
        const e = opt.e;
        e.preventDefault();
        e.stopPropagation();

        if (e.ctrlKey || e.metaKey) {
            // === ZOOM ===
            const delta = e.deltaY;
            let zoom = canvas.getZoom();
            zoom *= 0.997 ** delta;
            zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
            zoomToPoint(new fabric.Point(e.offsetX, e.offsetY), zoom);
        } else if (e.shiftKey) {
            // === PAN LEFT / RIGHT ===
            canvas.relativePan(new fabric.Point(-e.deltaY, 0));
        } else {
            // === PAN UP / DOWN ===
            canvas.relativePan(new fabric.Point(-e.deltaX, -e.deltaY));
        }
        clampPan();
        canvas.renderAll();
    });

    // Pan with middle mouse button, Alt+drag, or Space+drag
    let isPanning = false;
    let isSpaceDown = false;
    let lastPanPos = { x: 0, y: 0 };

    // Track spacebar for Photoshop/Canva-style panning
    document.addEventListener('keydown', function(e) {
        if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            if (canvas.getActiveObject() && canvas.getActiveObject().isEditing) return;
            e.preventDefault();
            isSpaceDown = true;
            canvas.defaultCursor = 'grab';
            canvas.setCursor('grab');
            canvas.selection = false;
        }
    });
    document.addEventListener('keyup', function(e) {
        if (e.code === 'Space') {
            isSpaceDown = false;
            canvas.defaultCursor = 'default';
            canvas.setCursor('default');
            canvas.selection = true;
        }
    });

    canvas.on('mouse:down', function(opt) {
        if (opt.e.altKey || opt.e.button === 1 || isSpaceDown) {
            isPanning = true;
            lastPanPos = { x: opt.e.clientX, y: opt.e.clientY };
            canvas.selection = false;
            canvas.defaultCursor = 'grabbing';
            canvas.setCursor('grabbing');
        }
    });

    canvas.on('mouse:move', function(opt) {
        if (isPanning) {
            const dx = opt.e.clientX - lastPanPos.x;
            const dy = opt.e.clientY - lastPanPos.y;
            canvas.relativePan(new fabric.Point(dx, dy));
            clampPan();
            lastPanPos = { x: opt.e.clientX, y: opt.e.clientY };
        }
    });

    canvas.on('mouse:up', function(opt) {
        if (isPanning) {
            isPanning = false;
            if (!isSpaceDown) {
                canvas.selection = true;
                canvas.defaultCursor = 'default';
            } else {
                canvas.defaultCursor = 'grab';
                canvas.setCursor('grab');
            }
        }
    });

    // ===== HINT VISIBILITY =====
    function updateHintVisibility() {
        // Count non-artboard objects
        const count = canvas.getObjects().filter(o => !o._isArtboard).length;
        if (dropHint) {
            if (count > 0) {
                dropHint.style.display = 'none';
            } else {
                dropHint.style.display = 'block';
            }
        }
        const clrBtn = document.getElementById('clearBtn');
        if (clrBtn) clrBtn.disabled = count === 0;
        const saveBtn = document.getElementById('saveDesignBtn');
        if (saveBtn) saveBtn.disabled = count === 0;
    }

    // ===== WINDOW RESIZE =====
    window.addEventListener('resize', () => {
        canvas.setWidth(dropZone.clientWidth);
        canvas.setHeight(dropZone.clientHeight);
        canvas.renderAll();
    });

    // ===== DRAG AND DROP =====
    const draggables = document.querySelectorAll('.draggable-item');

    draggables.forEach(draggable => {
        draggable.addEventListener('dragstart', (e) => {
            const type = draggable.getAttribute('data-type');
            const src = draggable.getAttribute('data-src');
            const color = draggable.getAttribute('data-color');
            const itemWidth = draggable.getAttribute('data-width');
            const itemHeight = draggable.getAttribute('data-height');
            const textContent = draggable.getAttribute('data-text');
            const fontFamily = draggable.getAttribute('data-font-family');
            
            const itemData = {
                type: type,
                src: src,
                fill: color,
                width: itemWidth ? parseInt(itemWidth) : 0,
                height: itemHeight ? parseInt(itemHeight) : 0,
                text: textContent || "Text",
                fontFamily: fontFamily || "Arial"
            };
            
            e.dataTransfer.setData('text/plain', JSON.stringify(itemData));
            e.dataTransfer.effectAllowed = 'copy';
        });
    });

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', (e) => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');

        // Convert screen coords to canvas coords (account for zoom + pan)
        const rect = canvas.getElement().getBoundingClientRect();
        const screenX = e.clientX - rect.left;
        const screenY = e.clientY - rect.top;
        
        // Transform to Fabric.js canvas coordinates
        const pointer = canvas.restorePointerVpt(new fabric.Point(screenX, screenY));

        const itemDataStr = e.dataTransfer.getData('text/plain');
        if (!itemDataStr) return;

        try {
            const itemData = JSON.parse(itemDataStr);
            addShapeToCanvas(itemData, pointer);
        } catch (err) {
            console.error("Error parsing dragged item data:", err);
        }
    });

    // ===== ADD SHAPES / IMAGES =====
    function addShapeToCanvas(data, pointer) {
        const commonOptions = {
            left: pointer.x,
            top: pointer.y,
            originX: 'center',
            originY: 'center',
            transparentCorners: false,
            cornerColor: '#ffffff',
            cornerStrokeColor: '#333',
            borderColor: '#3b82f6',
            cornerSize: 10,
            padding: 5,
            cornerStyle: 'circle',
        };

        if (data.type === 'image') {
            fabric.loadSVGFromURL(data.src, function(objects, options) {
                if (!objects || !objects.length) return;
                const validObjects = objects.filter(o => o);
                const svgGroup = fabric.util.groupSVGElements(validObjects, options);
                
                if (data.width && data.height) {
                    const scaleX = data.width / svgGroup.width;
                    const scaleY = data.height / svgGroup.height;
                    const scale = Math.min(scaleX, scaleY);
                    svgGroup.scale(scale);
                } else {
                    const maxDim = 150;
                    const scale = maxDim / Math.max(svgGroup.width, svgGroup.height);
                    svgGroup.scale(scale);
                }

                svgGroup.set(commonOptions);
                svgGroup._isColorableSVG = true;
                svgGroup._packageCategory = getCategoryFromSrc(data.src);
                
                canvas.add(svgGroup);
                canvas.setActiveObject(svgGroup);
                canvas.renderAll();
                updateHintVisibility();
                updateVisualCart();
            });
            return;
        } 
        
        let newObj;

        if (data.type === 'i-text') {
            newObj = new fabric.IText(data.text, {
                ...commonOptions,
                fontFamily: data.fontFamily,
                fill: data.fill || '#333333',
                fontSize: 40,
                fontWeight: 'bold',
                shadow: new fabric.Shadow({
                    color: 'rgba(0,0,0,0.2)',
                    blur: 5,
                    offsetX: 2,
                    offsetY: 2
                })
            });
        }
        else if (data.type === 'rect') {
            newObj = new fabric.Rect({
                ...commonOptions,
                fill: data.fill,
                width: data.width || 150,
                height: data.height || 150,
                rx: 4,
                ry: 4,
                opacity: 0.95
            });
        } 

        if (newObj) {
            newObj._packageCategory = 'custom';
            canvas.add(newObj);
            canvas.setActiveObject(newObj);
            canvas.renderAll();
            updateHintVisibility();
            updateVisualCart();
        }
    }

    function getCategoryFromSrc(src) {
        if (!src) return 'custom';
        src = src.toLowerCase();
        if (src.includes('arch')) return 'arch';
        if (src.includes('backdrop')) return 'backdrop';
        if (src.includes('plinth')) return 'plinths';
        if (src.includes('balloon')) return 'balloons';
        if (src.includes('flower') || src.includes('floral') || src.includes('fern')) return 'florals';
        if (src.includes('neon')) return 'neon';
        return 'custom';
    }

    // ===== CANVAS CONTROLS =====
    const cloneBtn = document.getElementById('cloneBtn');
    const lockBtn = document.getElementById('lockBtn');
    const layerUpBtn = document.getElementById('layerUpBtn');
    const layerDownBtn = document.getElementById('layerDownBtn');
    const toFrontBtn = document.getElementById('toFrontBtn');
    const toBackBtn = document.getElementById('toBackBtn');
    const flipXBtn = document.getElementById('flipXBtn');
    const flipYBtn = document.getElementById('flipYBtn');
    const skewLeftBtn = document.getElementById('skewLeftBtn');
    const skewRightBtn = document.getElementById('skewRightBtn');
    const deleteBtn = document.getElementById('deleteBtn');
    const clearBtn = document.getElementById('clearBtn');
    const saveDesignBtn = document.getElementById('saveDesignBtn');
    const itemColorPicker = document.getElementById('itemColorPicker');

    // Helper to identify outline strokes vs solid fills
    function isOutlineColor(colorStr) {
        if (!colorStr || colorStr === 'none' || colorStr === 'transparent') return false;
        const c = colorStr.toLowerCase();
        return (c === '#000000' || c === '#222222' || c === 'black' || c === '#333333' || c === '#111111');
    }

    if (itemColorPicker) {
        itemColorPicker.addEventListener('input', (e) => {
            const newColor = e.target.value;
            const activeObjs = canvas.getActiveObjects();
            if (activeObjs.length === 0) return;
            
            activeObjs.forEach(obj => {
                if (obj.type === 'i-text' || obj.type === 'rect') {
                    obj.set('fill', newColor);
                } else if (obj._isColorableSVG) {
                    // SVG might be a Group (has _objects) or a single shape
                    const shapes = obj._objects ? obj._objects : [obj];
                    shapes.forEach(path => {
                        if (path.fill && !isOutlineColor(path.fill)) {
                            path.set('fill', newColor);
                        }
                    });
                    obj.dirty = true;
                }
            });
            canvas.renderAll();
        });
    }

    function updateControlsState() {
        const activeObjs = canvas.getActiveObjects().filter(o => !o._isArtboard);
        const hasSelection = activeObjs.length > 0;
        const singleObj = activeObjs.length === 1 ? activeObjs[0] : null;
        const isLocked = !!(singleObj && singleObj._isLocked);

        cloneBtn.disabled = !hasSelection || isLocked;
        if (lockBtn) lockBtn.disabled = !hasSelection;
        layerUpBtn.disabled = !hasSelection || isLocked;
        layerDownBtn.disabled = !hasSelection || isLocked;
        if (toFrontBtn) toFrontBtn.disabled = !hasSelection || isLocked;
        if (toBackBtn) toBackBtn.disabled = !hasSelection || isLocked;
        if (flipXBtn) flipXBtn.disabled = !hasSelection || isLocked;
        if (flipYBtn) flipYBtn.disabled = !hasSelection || isLocked;
        if (skewLeftBtn) skewLeftBtn.disabled = !hasSelection || isLocked;
        if (skewRightBtn) skewRightBtn.disabled = !hasSelection || isLocked;
        deleteBtn.disabled = !hasSelection;

        if (lockBtn) {
            const lockIcon = lockBtn.querySelector('i');
            if (lockIcon) {
                lockIcon.className = isLocked ? 'fas fa-lock' : 'fas fa-lock-open';
            }
        }

        if (itemColorPicker) {
            itemColorPicker.disabled = !hasSelection;
            if (activeObjs.length === 1) {
                const obj = activeObjs[0];
                if (obj.type === 'i-text' || obj.type === 'rect') {
                    itemColorPicker.value = obj.fill || '#000000';
                } else if (obj._isColorableSVG) {
                    let foundColor = '#ffffff';
                    const shapes = obj._objects ? obj._objects : [obj];
                    for (let path of shapes) {
                        if (path.fill && !isOutlineColor(path.fill) && path.fill !== 'transparent' && path.fill !== 'none') {
                            try {
                                const hex = new fabric.Color(path.fill).toHex();
                                if (hex) foundColor = '#' + hex;
                            } catch(e) {}
                            break;
                        }
                    }
                    if (foundColor.length === 4) { // handle #abc
                        foundColor = '#' + foundColor[1]+foundColor[1] + foundColor[2]+foundColor[2] + foundColor[3]+foundColor[3];
                    }
                    if (foundColor.length === 7) {
                        itemColorPicker.value = foundColor;
                    }
                }
            } else {
                itemColorPicker.value = '#ffffff';
            }
        }
    }

    canvas.on('selection:created', updateControlsState);
    canvas.on('selection:updated', updateControlsState);
    canvas.on('selection:cleared', updateControlsState);

    // Layer Controls
    layerUpBtn.addEventListener('click', () => {
        const activeObj = canvas.getActiveObject();
        if (activeObj && !activeObj._isArtboard) {
            saveState();
            activeObj.bringForward();
            canvas.renderAll();
        }
    });

    layerDownBtn.addEventListener('click', () => {
        const activeObj = canvas.getActiveObject();
        if (activeObj && !activeObj._isArtboard) {
            // Don't send behind the artboard
            const idx = canvas.getObjects().indexOf(activeObj);
            if (idx > 1) {
                saveState();
                activeObj.sendBackwards();
                canvas.renderAll();
            }
        }
    });

    if (toFrontBtn) {
        toFrontBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                canvas.bringToFront(activeObj);
                canvas.renderAll();
            }
        });
    }

    if (toBackBtn) {
        toBackBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                canvas.sendToBack(activeObj);
                canvas.moveTo(activeObj, 1);
                canvas.renderAll();
            }
        });
    }

    if (flipXBtn) {
        flipXBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                activeObj.set('flipX', !activeObj.flipX);
                canvas.renderAll();
            }
        });
    }

    if (flipYBtn) {
        flipYBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                activeObj.set('flipY', !activeObj.flipY);
                canvas.renderAll();
            }
        });
    }

    if (skewLeftBtn) {
        skewLeftBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                activeObj.set('skewX', (activeObj.skewX || 0) - 5);
                canvas.renderAll();
            }
        });
    }

    if (skewRightBtn) {
        skewRightBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (activeObj && !activeObj._isArtboard && !activeObj._isLocked) {
                saveState();
                activeObj.set('skewX', (activeObj.skewX || 0) + 5);
                canvas.renderAll();
            }
        });
    }

    if (lockBtn) {
        lockBtn.addEventListener('click', () => {
            const activeObj = canvas.getActiveObject();
            if (!activeObj || activeObj._isArtboard) return;
            saveState();

            if (activeObj._isLocked) {
                activeObj._isLocked = false;
                activeObj.set({
                    selectable: true,
                    evented: true,
                    lockMovementX: false,
                    lockMovementY: false,
                    lockRotation: false,
                    lockScalingX: false,
                    lockScalingY: false,
                    hasControls: true,
                    hoverCursor: 'move',
                    opacity: 1
                });
            } else {
                activeObj._isLocked = true;
                activeObj.set({
                    lockMovementX: true,
                    lockMovementY: true,
                    lockRotation: true,
                    lockScalingX: true,
                    lockScalingY: true,
                    hasControls: false,
                    hoverCursor: 'not-allowed',
                    opacity: 0.75
                });
            }

            canvas.renderAll();
            updateControlsState();
        });
    }

    if (undoBtn) {
        undoBtn.addEventListener('click', () => {
            if (undoStack.length === 0) return;
            redoStack.push(getCurrentState());
            const prev = undoStack.pop();
            restoreCanvasState(prev);
        });
    }

    if (redoBtn) {
        redoBtn.addEventListener('click', () => {
            if (redoStack.length === 0) return;
            undoStack.push(getCurrentState());
            const next = redoStack.pop();
            restoreCanvasState(next);
        });
    }

    // Clone
    cloneBtn.addEventListener('click', () => {
        const activeObj = canvas.getActiveObject();
        if (!activeObj || activeObj._isArtboard) return;

        if (canvas.getActiveObjects().length > 1) {
            alert("Please clone one item at a time.");
            return;
        }

        activeObj.clone((cloned) => {
            saveState();
            canvas.discardActiveObject();
            cloned.set({
                left: cloned.left + 20,
                top: cloned.top + 20,
                evented: true,
            });
            if (cloned.type === 'activeSelection') {
                cloned.canvas = canvas;
                cloned.forEachObject((obj) => canvas.add(obj));
                cloned.setCoords();
            } else {
                canvas.add(cloned);
            }
            canvas.setActiveObject(cloned);
            canvas.renderAll();
        });
    });

    // Delete
    function deleteSelectedObjects() {
        const activeObjects = canvas.getActiveObjects().filter(o => !o._isArtboard);
        if (activeObjects.length) {
            saveState();
            canvas.discardActiveObject();
            activeObjects.forEach(function(object) {
                canvas.remove(object);
            });
            canvas.renderAll();
            updateHintVisibility();
            updateVisualCart();
        }
    }

    deleteBtn.addEventListener('click', deleteSelectedObjects);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        // Editing text (IText) — don't intercept
        if (canvas.getActiveObject() && canvas.getActiveObject().isEditing) return;
        
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            deleteSelectedObjects();
        }
        
        if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
            e.preventDefault();
            cloneBtn.click();
        }

        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
            e.preventDefault();
            if (undoBtn) undoBtn.click();
        }

        if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
            e.preventDefault();
            if (redoBtn) redoBtn.click();
        }

        // Zoom shortcuts
        if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
            e.preventDefault();
            zoomCenter(canvas.getZoom() * 1.2);
        }
        if ((e.ctrlKey || e.metaKey) && e.key === '-') {
            e.preventDefault();
            zoomCenter(canvas.getZoom() / 1.2);
        }
        if ((e.ctrlKey || e.metaKey) && e.key === '0') {
            e.preventDefault();
            fitArtboardToView();
        }
    });

    // Clear Canvas
    clearBtn.addEventListener('click', () => {
        const nonArtboard = canvas.getObjects().filter(o => !o._isArtboard);
        if (nonArtboard.length === 0) return;
        if (confirm("Are you sure you want to clear the entire canvas?")) {
            saveState();
            nonArtboard.forEach(obj => canvas.remove(obj));
            canvas.discardActiveObject();
            canvas.renderAll();
            updateHintVisibility();
            updateVisualCart();
        }
    });

    // ===== SAVE DESIGN (backend save + thumbnail) =====
    saveDesignBtn.addEventListener('click', async () => {
        const nonArtboard = canvas.getObjects().filter(o => !o._isArtboard);
        if (nonArtboard.length === 0) {
            alert("The canvas is empty. Add some elements first!");
            return;
        }

        canvas.discardActiveObject();
        canvas.renderAll();

        const currentVpt = canvas.viewportTransform.slice();
        canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
        canvas.renderAll();

        const dataURL = canvas.toDataURL({
            format: 'png',
            quality: 0.8,
            multiplier: 2,
            left: artboard.left,
            top: artboard.top,
            width: ARTBOARD_W,
            height: ARTBOARD_H,
        });

        canvas.setViewportTransform(currentVpt);
        canvas.renderAll();

        const jsonState = getCurrentState();
        let designName = 'My Balloon Setup';
        if (!window.currentDesignId) {
            const userPrompt = prompt('Enter a name for your design:', 'My Balloon Setup');
            if (userPrompt === null) return;
            if (userPrompt.trim() !== '') designName = userPrompt.trim();
        } else {
            designName = '';
        }

        const originalText = saveDesignBtn.innerHTML;
        saveDesignBtn.innerHTML = '<i class=\"fas fa-spinner fa-spin\"></i> Saving...';
        saveDesignBtn.disabled = true;

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]') ?
                document.querySelector('[name=csrfmiddlewaretoken]').value : '';

            const payload = {
                id: window.currentDesignId || null,
                name: designName,
                canvas_json: jsonState,
                thumbnail: dataURL
            };

            const response = await fetch('/my-designs/save/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('Design saved successfully!');
                window.location.href = '/my-designs/';
            } else {
                alert('Error saving design: ' + data.message);
                saveDesignBtn.innerHTML = originalText;
                saveDesignBtn.disabled = false;
            }
        } catch (error) {
            console.error('Save error:', error);
            alert('Network error. Could not save design.');
            saveDesignBtn.innerHTML = originalText;
            saveDesignBtn.disabled = false;
        }
    });

    // Save state for undo/redo and keep UI synced
    canvas.on('object:added', (e) => {
        if (!isLoadingState && e.target && !e.target._isArtboard) {
            saveState();
            updateHintVisibility();
            updateVisualCart();
        }
    });

    canvas.on('object:modified', (e) => {
        if (!isLoadingState && e.target && !e.target._isArtboard) {
            saveState();
            updateVisualCart();
        }
    });

    // Sidebar color swatches
    document.querySelectorAll('.color-swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
            const color = swatch.dataset.color;
            document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
            swatch.classList.add('active');

            const active = canvas.getActiveObject();
            if (active && !active._isArtboard) {
                if (active._isColorableSVG && active._objects) {
                    active._objects.forEach(obj => obj.set('fill', color));
                } else {
                    active.set('fill', color);
                }
            } else {
                artboard.set('fill', color);
            }
            canvas.renderAll();
            saveState();
        });
    });

    if (customCanvasColor) {
        customCanvasColor.addEventListener('input', (e) => {
            const color = e.target.value;
            const active = canvas.getActiveObject();
            if (active && !active._isArtboard) {
                if (active._isColorableSVG && active._objects) {
                    active._objects.forEach(obj => obj.set('fill', color));
                } else {
                    active.set('fill', color);
                }
            } else {
                artboard.set('fill', color);
            }
            canvas.renderAll();
        });
        customCanvasColor.addEventListener('change', () => saveState());
    }

    // Background image upload/remove
    if (bgImageUpload) {
        bgImageUpload.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
                fabric.Image.fromURL(ev.target.result, (img) => {
                    const scaleX = ARTBOARD_W / img.width;
                    const scaleY = ARTBOARD_H / img.height;
                    const scale = Math.max(scaleX, scaleY);
                    img.set({
                        left: artboard.left,
                        top: artboard.top,
                        scaleX: scale,
                        scaleY: scale,
                        selectable: false,
                        evented: false,
                        _isBgImage: true
                    });
                    canvas.getObjects().forEach(o => {
                        if (o._isBgImage) canvas.remove(o);
                    });
                    canvas.insertAt(img, 1);
                    canvas.renderAll();
                    saveState();
                });
            };
            reader.readAsDataURL(file);
            bgImageUpload.value = '';
        });
    }

    if (removeBgImage) {
        removeBgImage.addEventListener('click', () => {
            canvas.getObjects().forEach(o => {
                if (o._isBgImage) canvas.remove(o);
            });
            canvas.renderAll();
            saveState();
        });
    }

    // Element size W/H controls
    function updateElemSizeInputs() {
        const active = canvas.getActiveObject();
        if (active && !active._isArtboard) {
            if (elemWidthInput) elemWidthInput.value = Math.round(active.getScaledWidth());
            if (elemHeightInput) elemHeightInput.value = Math.round(active.getScaledHeight());
        } else {
            if (elemWidthInput) elemWidthInput.value = 0;
            if (elemHeightInput) elemHeightInput.value = 0;
        }
    }
    canvas.on('selection:created', updateElemSizeInputs);
    canvas.on('selection:updated', updateElemSizeInputs);
    canvas.on('selection:cleared', updateElemSizeInputs);
    canvas.on('object:scaling', updateElemSizeInputs);

    if (elemWidthInput) {
        const applyElemWidth = () => {
            const active = canvas.getActiveObject();
            if (!active || active._isArtboard) return;
            const newW = parseInt(elemWidthInput.value, 10) || 1;
            active.scaleX = newW / active.width;
            active.setCoords();
            canvas.renderAll();
            saveState();
        };
        elemWidthInput.addEventListener('change', applyElemWidth);
        elemWidthInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') applyElemWidth(); });
    }

    if (elemHeightInput) {
        const applyElemHeight = () => {
            const active = canvas.getActiveObject();
            if (!active || active._isArtboard) return;
            const newH = parseInt(elemHeightInput.value, 10) || 1;
            active.scaleY = newH / active.height;
            active.setCoords();
            canvas.renderAll();
            saveState();
        };
        elemHeightInput.addEventListener('change', applyElemHeight);
        elemHeightInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') applyElemHeight(); });
    }

    // Canvas size footer controls
    if (applySizeBtn && canvasWidthInput && canvasHeightInput) {
        applySizeBtn.addEventListener('click', () => {
            const newW = parseInt(canvasWidthInput.value, 10) || ARTBOARD_W;
            const newH = parseInt(canvasHeightInput.value, 10) || ARTBOARD_H;
            if (newW < 100 || newH < 100 || newW > 5000 || newH > 5000) {
                alert('Canvas size must be between 100 and 5000.');
                return;
            }
            ARTBOARD_W = newW;
            ARTBOARD_H = newH;
            artboard.set({ width: ARTBOARD_W, height: ARTBOARD_H });
            artboard.setCoords();
            if (canvasSizeDisp) canvasSizeDisp.textContent = `Canvas: ${ARTBOARD_W} × ${ARTBOARD_H}`;
            fitArtboardToView();
            saveState();
        });
    }

    // User uploads
    const userUploadInput = document.getElementById('userUploadInput');
    const userUploadsGrid = document.getElementById('userUploadsGrid');
    if (userUploadInput && userUploadsGrid) {
        userUploadInput.addEventListener('change', (e) => {
            Array.from(e.target.files).forEach(file => {
                if (!file.type.startsWith('image/')) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                    const dataUrl = ev.target.result;
                    const div = document.createElement('div');
                    div.className = 'draggable-item';
                    div.draggable = true;
                    div.dataset.type = 'image';
                    div.dataset.src = dataUrl;
                    div.dataset.width = '150';
                    div.dataset.height = '150';
                    div.title = file.name;
                    div.innerHTML = `<div class=\"item-preview-img-wrapper\"><img class=\"item-preview-img\" src=\"${dataUrl}\" alt=\"${file.name}\"></div>`;
                    div.addEventListener('dragstart', (de) => {
                        de.dataTransfer.setData('text/plain', JSON.stringify({
                            type: 'image',
                            src: dataUrl,
                            width: 150,
                            height: 150
                        }));
                    });
                    userUploadsGrid.appendChild(div);
                };
                reader.readAsDataURL(file);
            });
            userUploadInput.value = '';
        });
    }

    function getAddonPrice(category) {
        let matchKey = Object.keys(window.addonPrices || {}).find(k => k.toLowerCase().includes(category));
        if (matchKey && window.addonPrices[matchKey]) return parseFloat(window.addonPrices[matchKey]);
        const fallback = { arch: 1500, backdrop: 2000, plinths: 500, balloons: 15, florals: 800, neon: 1200, custom: 100 };
        return fallback[category] || 100;
    }

    function generateCartLabel(category) {
        const labels = { arch: 'Arch Frame', backdrop: 'Backdrop', plinths: 'Plinth', balloons: 'Balloon', florals: 'Floral', neon: 'Neon Sign' };
        return labels[category] || 'Custom Item';
    }

    function updateVisualCart() {
        if (!cartAddonsList || !cartTotalPrice) return;
        const objects = canvas.getObjects().filter(o => !o._isArtboard && !o._isBgImage);
        const counts = {};
        objects.forEach(obj => {
            const cat = obj._packageCategory || 'custom';
            counts[cat] = (counts[cat] || 0) + 1;
        });

        if (cartInclusionsList) cartInclusionsList.innerHTML = '';
        cartAddonsList.innerHTML = '';

        let totalAddonPrice = 0;
        let hasAddons = false;
        if (window.basePackageId && window.packageQuotas) {
            Object.keys(window.packageQuotas).forEach(cat => {
                const limit = window.packageQuotas[cat] || 0;
                const used = counts[cat] || 0;
                if (cartInclusionsList) {
                    const li = document.createElement('li');
                    li.innerHTML = `<span>${generateCartLabel(cat)}</span> <span>${Math.min(used, limit)} / ${limit}</span>`;
                    cartInclusionsList.appendChild(li);
                }
                if (used > limit) {
                    const excess = used - limit;
                    const cost = excess * getAddonPrice(cat);
                    totalAddonPrice += cost;
                    hasAddons = true;
                    const addLi = document.createElement('li');
                    addLi.innerHTML = `<span>Extra ${generateCartLabel(cat)} (x${excess})</span> <span>P${cost.toFixed(2)}</span>`;
                    cartAddonsList.appendChild(addLi);
                }
                delete counts[cat];
            });
        }

        Object.keys(counts).forEach(cat => {
            const used = counts[cat];
            if (used <= 0) return;
            const cost = used * getAddonPrice(cat);
            totalAddonPrice += cost;
            hasAddons = true;
            const addLi = document.createElement('li');
            addLi.innerHTML = `<span>${generateCartLabel(cat)} (x${used})</span> <span>P${cost.toFixed(2)}</span>`;
            cartAddonsList.appendChild(addLi);
        });

        if (!hasAddons) {
            cartAddonsList.innerHTML = '<li class=\"empty-list\" style=\"color:#666;font-style:italic;\">No extra items yet.</li>';
        }
        cartTotalPrice.textContent = `P${totalAddonPrice.toFixed(2)}`;
    }

    // Initial visibility
    updateUndoRedoBtnState();
    updateControlsState();
    updateHintVisibility();
    updateVisualCart();
});
