/* Loading follows existing content geometry. Widget-owned DOM is never a loader host. */
(() => {
    'use strict';
    if (window.SiteLoading) return;
    const states = new Map(), images = new WeakMap();
    const owned = '.site-loading-portal,.site-loading-slot,.site-loading-status';
    const protectedContent = 'script,style,template,noscript,[hidden],thead,header,footer,nav,label,[role="toolbar"],[role="tablist"],.pagination,.ac-pagination,.account-pagination,[data-list-page],[data-skeleton-preserve],[data-skeleton-ignore]';
    let frame = 0, sequence = 0;
    const visible = el => el.isConnected && !!el.getClientRects().length && !el.closest('[hidden],dialog:not([open])') && getComputedStyle(el).visibility !== 'hidden';
    const rect = el => el.getBoundingClientRect();
    const topLayer = el => el.closest('dialog[open],[popover]') || document.body;
    function schedule() {
        if (!frame && [...states.values()].some(state => state.shown)) frame = requestAnimationFrame(() => {
            frame = 0;
            for (const state of [...states.values()]) if (state.shown) paint(state);
        });
    }
    function clippedBounds(target, bounds) {
        let left = Math.max(0, bounds.left), top = Math.max(0, bounds.top);
        let right = Math.min(innerWidth, bounds.right), bottom = Math.min(innerHeight, bounds.bottom);
        for (let parent = target.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
            const style = getComputedStyle(parent), box = rect(parent);
            if (/auto|scroll|hidden|clip/.test(style.overflowX)) {
                left = Math.max(left, box.left + parent.clientLeft); right = Math.min(right, box.left + parent.clientLeft + parent.clientWidth);
            }
            if (/auto|scroll|hidden|clip/.test(style.overflowY)) {
                top = Math.max(top, box.top + parent.clientTop); bottom = Math.min(bottom, box.top + parent.clientTop + parent.clientHeight);
            }
        }
        return {left, top, right: Math.max(left, right), bottom: Math.max(top, bottom)};
    }
    function geometry(source, variant) {
        const bounds = rect(source), shapes = [], seen = new Set();
        const controls = [...source.querySelectorAll('button,header,footer,[role="toolbar"],.leaflet-control-container a,input,textarea,select')]
            .filter(el => visible(el) && (!el.matches('input,textarea,select') || variant !== 'form' || el.value)).map(rect);
        const add = (box, kind, radius = 4, element = source) => {
            let left = Math.max(bounds.left,box.left), top = Math.max(bounds.top,box.top);
            let right = Math.min(bounds.right,box.right), bottom = Math.min(bounds.bottom,box.bottom);
            for (let parent = element; parent && source.contains(parent); parent = parent.parentElement) {
                const style = getComputedStyle(parent), area = rect(parent);
                if (/auto|scroll|hidden|clip/.test(style.overflowX)) { left = Math.max(left,area.left+parent.clientLeft); right = Math.min(right,area.left+parent.clientLeft+parent.clientWidth); }
                if (/auto|scroll|hidden|clip/.test(style.overflowY)) { top = Math.max(top,area.top+parent.clientTop); bottom = Math.min(bottom,area.top+parent.clientTop+parent.clientHeight); }
            }
            if (right - left < 2 || bottom - top < 2 || shapes.length >= 320) return;
            let pieces = [{left,top,right,bottom}];
            for (const control of controls) pieces = pieces.flatMap(piece => {
                const x1 = Math.max(piece.left,control.left), y1 = Math.max(piece.top,control.top);
                const x2 = Math.min(piece.right,control.right), y2 = Math.min(piece.bottom,control.bottom);
                if (x2 <= x1 || y2 <= y1) return [piece];
                return [{...piece,bottom:y1},{...piece,top:y2},{left:piece.left,right:x1,top:y1,bottom:y2},{left:x2,right:piece.right,top:y1,bottom:y2}]
                    .filter(part => part.right-part.left >= 2 && part.bottom-part.top >= 2);
            });
            for (const piece of pieces) {
                const key = [piece.left,piece.top,piece.right,piece.bottom].map(Math.round).join(':');
                if (seen.has(key) || shapes.length >= 320) continue;
                seen.add(key); shapes.push({x:piece.left-bounds.left,y:piece.top-bounds.top,width:piece.right-piece.left,height:piece.bottom-piece.top,kind,radius});
            }
        };
        // Use actual result rows; their headers, filters and page controls stay readable.
        const bodies = [...source.querySelectorAll('tbody')].filter(el => visible(el) && rect(el).height);
        const roots = bodies.length ? bodies : [source];
        const skip = el => {
            const blocker = el.closest(protectedContent), decoration = el.closest(owned), form = el.closest('form');
            return !visible(el) || !!(blocker && (source === blocker || source.contains(blocker))) || !!(decoration && decoration !== source && source.contains(decoration)) || (variant !== 'form' && !!(form && (source === form || source.contains(form))));
        };
        for (const root of roots) {
            for (const media of root.querySelectorAll('img,canvas,video,svg:not(:has(symbol)),input:not([type="hidden"]),textarea,select')) {
                if (skip(media) || media.closest('button') || media instanceof SVGElement && media.closest('svg') !== media) continue;
                if (media.matches('input,textarea,select') && (variant !== 'form' || media.value)) continue;
                add(rect(media), media.matches('input,textarea,select') ? 'field' : 'media', parseFloat(getComputedStyle(media).borderRadius) || 4, media);
            }
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const parent = node.parentElement;
                if (!node.textContent.trim() || !parent || skip(parent) || parent.closest('button,input,textarea,select,svg')) continue;
                const range = document.createRange(); range.selectNodeContents(node);
                for (const box of range.getClientRects()) add(box,'text',4,parent);
            }
        }
        // A frame with no content yet (map/canvas/photo) uses its own exact bounds.
        // Empty dialogs keep their existing loading message; no invented form/grid is inserted.
        if (!shapes.length && ['image','canvas','chart','inline'].includes(variant) && bounds.width && bounds.height) add(bounds, 'frame', 6);
        return {bounds, shapes};
    }
    function paint(state) {
        const {target, source, layer, portal, slot} = state;
        if (!visible(target) || !source.isConnected) { state.finish(); return; }
        const data = geometry(source, state.variant);
        if (slot) { slot.style.height = `${data.bounds.height}px`; slot.style.width = `${rect(target).width}px`; }
        const bounds = rect(slot || target), clip = clippedBounds(slot || target, bounds), origin = rect(portal);
        layer.style.left = `${bounds.left - origin.left}px`; layer.style.top = `${bounds.top - origin.top}px`;
        layer.style.width = `${bounds.width}px`; layer.style.height = `${bounds.height}px`;
        layer.style.clipPath = `inset(${Math.max(0,clip.top-bounds.top)}px ${Math.max(0,bounds.right-clip.right)}px ${Math.max(0,bounds.bottom-clip.bottom)}px ${Math.max(0,clip.left-bounds.left)}px)`;
        // Keep pieces mounted while scrolling/resizing; update only changed geometry.
        // Recreating them resets shimmer and can leave observers holding detached nodes.
        state.shapeKeys ||= [];
        while (layer.children.length > data.shapes.length) layer.lastElementChild.remove();
        data.shapes.forEach((shape,index) => {
            let piece = layer.children[index];
            if (!piece) { piece = document.createElement('span'); piece.className = 'site-skeleton-shape'; layer.append(piece); }
            const key = JSON.stringify(shape);
            if (state.shapeKeys[index] !== key) {
                piece.dataset.skeletonKind = shape.kind;
                piece.style.cssText = `left:${shape.x}px;top:${shape.y}px;width:${shape.width}px;height:${shape.height}px;border-radius:${shape.radius}px`;
                state.shapeKeys[index] = key;
            }
        });
        state.shapeKeys.length = data.shapes.length;
        // Follow short entrance/transition animations without running a permanent loop.
        const running = animations => animations.some(animation => animation.playState === 'running' && animation.effect?.getTiming().iterations !== Infinity);
        let moving = running(target.getAnimations?.({subtree:true}) || []);
        for (let parent = target.parentElement; parent && !moving; parent = parent.parentElement) moving = running(parent.getAnimations?.() || []);
        if (moving) schedule();
    }
    function start(region, options = {}) {
        const target = typeof region === 'string' ? document.querySelector(region) : region;
        if (!(target instanceof HTMLElement)) return {finish() {}};
        states.get(target)?.finish();
        if (options.signal?.aborted) return {finish() {}};
        const originalBusy = target.getAttribute('aria-busy');
        const status = document.createElement('span'); status.className = 'site-loading-status';
        status.setAttribute('role','status'); status.textContent = options.label || 'Loading content...';
        topLayer(target).append(status); target.setAttribute('aria-busy','true');
        let ended = false, delay, timeout, resize;
        const state = {
            target, status, source: target, variant: options.variant || 'content', shown: false,
            finish() {
                if (ended) return;
                ended = true; clearTimeout(delay); clearTimeout(timeout); resize?.disconnect();
                options.signal?.removeEventListener('abort', state.finish);
                state.portal?.remove(); state.slot?.remove(); status.remove();
                if (states.get(target) !== state) return;
                states.delete(target);
                if (originalBusy && originalBusy !== 'true') target.setAttribute('aria-busy',originalBusy);
                else target.removeAttribute('aria-busy');
            }
        };
        states.set(target,state);
        function show() {
            if (ended) return;
            if (!visible(target)) { state.finish(); return; }
            if (options.mode === 'append') {
                const rows = [...target.querySelectorAll('.notif-item,[data-message],.sc-session')].filter(el => visible(el) && rect(el).height);
                state.source = rows.at(-1) || target;
                state.slot = document.createElement('div'); state.slot.className = 'site-loading-slot'; state.slot.setAttribute('aria-hidden','true');
                target.after(state.slot);
            }
            if (!state.slot && (!rect(target).height || !geometry(target,state.variant).shapes.length)) {
                // First-time empty panels have no known records to imitate. A compact
                // loading line lives beside the region rather than inventing a form/list.
                state.slot = document.createElement('div'); state.slot.className = 'site-loading-slot site-loading-empty';
                state.slot.setAttribute('aria-hidden','true');
                const label = document.createElement('span'); label.className = 'site-loading-label';
                label.textContent = options.label || 'Loading content...'; state.slot.append(label);
                target.after(state.slot); state.source = state.slot;
            }
            const portal = state.portal = document.createElement('div'); portal.className = 'site-loading-portal';
            const layer = state.layer = document.createElement('div'); layer.className = 'site-skeleton-layer';
            layer.dataset.skeletonFor = target.id || `region-${++sequence}`;
            layer.dataset.skeletonLayout = state.variant; layer.dataset.skeletonMode = options.mode || 'replace';
            layer.setAttribute('aria-hidden','true'); portal.append(layer); topLayer(target).append(portal);
            state.shown = true; paint(state);
            if (window.ResizeObserver) { resize = new ResizeObserver(schedule); resize.observe(target); }
        }
        const wait = options.delay ?? 180;
        if (wait === 0) show(); else delay = setTimeout(show,wait);
        timeout = setTimeout(state.finish,options.timeout || 30000);
        options.signal?.addEventListener('abort',state.finish,{once:true});
        return {finish:state.finish};
    }
    function clear(root = document) {
        for (const state of [...states.values()]) if (root === state.target || root?.contains(state.target)) state.finish();
    }
    function image(img) {
        if (img.closest(owned + ',nav,.hero-balloons,.logo-container,[aria-hidden="true"],[data-skeleton-ignore]')) return;
        const key = (img.getAttribute('src') || '') + (img.getAttribute('srcset') || '');
        const previous = images.get(img); if (previous?.key === key) return;
        previous?.finish();
        let timer, ended = false;
        const state = {key,finish() {
            if (ended) return;
            ended = true; clearTimeout(timer); img.classList.remove('site-image-loading');
            img.removeEventListener('load',state.finish); img.removeEventListener('error',state.finish);
        }};
        images.set(img,state);
        if (!key || img.complete) return;
        img.addEventListener('load',state.finish,{once:true}); img.addEventListener('error',state.finish,{once:true});
        timer = setTimeout(() => { if (img.complete || !img.isConnected) state.finish(); else img.classList.add('site-image-loading'); },180);
    }
    function scan(root) {
        if (!(root instanceof Element) || root.closest(owned)) return;
        if (root.matches('img')) image(root); root.querySelectorAll('img').forEach(image);
    }
    const observer = new MutationObserver(records => {
        let changed = false;
        for (const record of records) {
            const el = record.target instanceof Element ? record.target : record.target.parentElement;
            if (el?.closest(owned)) continue;
            if (record.type === 'attributes' && el?.matches('img') && ['src','srcset'].includes(record.attributeName)) image(el);
            for (const node of record.addedNodes || []) if (node instanceof Element) scan(node);
            changed = true;
        }
        if (changed) {
            for (const state of [...states.values()]) if (!visible(state.target)) state.finish();
            schedule();
        }
    });
    observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['src','srcset','hidden','open','class','style']});
    window.SiteLoading = {start,clear,scan}; scan(document.documentElement);
    window.addEventListener('scroll',schedule,{capture:true,passive:true}); window.addEventListener('resize',schedule,{passive:true});
    document.addEventListener('animationstart',schedule,true); document.addEventListener('transitionrun',schedule,true);
    document.fonts?.addEventListener('loadingdone',schedule);
    document.addEventListener('close',event => { if (event.target instanceof HTMLDialogElement && !event.target.open) clear(event.target); },true);
    document.addEventListener('account:unmounting',event => clear(event.detail.root));
    window.addEventListener('pagehide',() => clear()); window.addEventListener('pageshow',event => { if (event.persisted) clear(); });
})();
