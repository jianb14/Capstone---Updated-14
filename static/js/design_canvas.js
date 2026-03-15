// static/js/design_canvas.js

document.addEventListener('DOMContentLoaded', function() {
    // ===== CONFIG =====
    const ARTBOARD_W = 1920;   // Artboard width in px  (landscape 16:9)
    const ARTBOARD_H = 1080;   // Artboard height in px
    const MIN_ZOOM = 0.15;
    const MAX_ZOOM = 3;

    // 1. Initialize Fabric.js Canvas
    const dropZone = document.getElementById('canvasDropZone');
    const dropHint = document.getElementById('dropHint');
    
    const width = dropZone.clientWidth;
    const height = dropZone.clientHeight;
    
    const canvas = new fabric.Canvas('designCanvas', {
        width: width,
        height: height,
        selection: true,
        preserveObjectStacking: true,
        backgroundColor: 'transparent',  // let the CSS background show through
    });

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
    
    // Run initial fit
    setTimeout(fitArtboardToView, 100);

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
        if (count > 0) {
            dropHint.style.display = 'none';
        } else {
            dropHint.style.display = 'block';
        }
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
                
                canvas.add(svgGroup);
                canvas.setActiveObject(svgGroup);
                canvas.renderAll();
                updateHintVisibility();
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
            canvas.add(newObj);
            canvas.setActiveObject(newObj);
            canvas.renderAll();
            updateHintVisibility();
        }
    }

    // ===== CANVAS CONTROLS =====
    const cloneBtn = document.getElementById('cloneBtn');
    const layerUpBtn = document.getElementById('layerUpBtn');
    const layerDownBtn = document.getElementById('layerDownBtn');
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
        cloneBtn.disabled = !hasSelection;
        layerUpBtn.disabled = !hasSelection;
        layerDownBtn.disabled = !hasSelection;
        deleteBtn.disabled = !hasSelection;

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
                activeObj.sendBackwards();
                canvas.renderAll();
            }
        }
    });

    // Clone
    cloneBtn.addEventListener('click', () => {
        const activeObj = canvas.getActiveObject();
        if (!activeObj || activeObj._isArtboard) return;

        if (canvas.getActiveObjects().length > 1) {
            alert("Please clone one item at a time.");
            return;
        }

        activeObj.clone((cloned) => {
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
            canvas.discardActiveObject();
            activeObjects.forEach(function(object) {
                canvas.remove(object);
            });
            canvas.renderAll();
            updateHintVisibility();
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
            nonArtboard.forEach(obj => canvas.remove(obj));
            canvas.discardActiveObject();
            canvas.renderAll();
            updateHintVisibility();
        }
    });

    // ===== SAVE DESIGN (exports ONLY the artboard area) =====
    saveDesignBtn.addEventListener('click', () => {
        const nonArtboard = canvas.getObjects().filter(o => !o._isArtboard);
        if (nonArtboard.length === 0) {
            alert("The canvas is empty. Add some elements first!");
            return;
        }

        canvas.discardActiveObject();
        canvas.renderAll();

        // Export only the artboard region
        const dataURL = canvas.toDataURL({
            format: 'png',
            quality: 1,
            multiplier: 2,
            left: artboard.left,
            top: artboard.top,
            width: ARTBOARD_W,
            height: ARTBOARD_H,
        });

        sessionStorage.setItem('savedDesign', dataURL);

        // Also trigger download
        const link = document.createElement('a');
        link.download = 'my-design.png';
        link.href = dataURL;
        link.click();
        
        alert("Design saved and downloaded!");
    });

    // Initial visibility
    updateHintVisibility();
});
