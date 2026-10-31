/* Vanilla DOM circular carousel; no React or animation dependencies.
 * Cylinder geometry/motion reference: React Bits Circular Carousel.
 * See docs/react-bits-carousel-notice.txt for the reference's license.
 */
(() => {
    'use strict';
    const root = document.querySelector('.creation-carousel');
    if (!root || root.dataset.initialized) return;
    root.dataset.initialized = 'true';
    const cards = [...root.querySelectorAll('[data-creation]')];
    if (!cards.length) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    const viewport = root.querySelector('.creation-carousel__viewport');
    const ring = root.querySelector('.home-creations-ring');
    const camera = root.querySelector('.creation-carousel__camera');
    const scene = root.querySelector('.creation-carousel__stage');
    const navigation = root.querySelector('.creation-carousel__navigation');
    const rotationButton = root.querySelector('[data-carousel-pause]');
    const positionLabel = root.querySelector('.creation-carousel__counter');
    const live = root.querySelector('.creation-carousel__live');
    const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
    const mod = (n, count) => ((n % count) + count) % count;
    const radians = Math.PI / 180;
    const enhanced = cards.length > 1 && CSS.supports('transform-style', 'preserve-3d');
    const slots = [];
    let angle = 0, velocity = 0, target = null, fit = 1;
    let frame = 0, lastTime = 0, resizeFrame = 0, resumeTimer = 0, wheelTimer = 0;
    let visible = !('IntersectionObserver' in window), entered = false, introStart = null;
    let hover = false, keyboard = false, paused = false, modalOpen = false;
    let press = null, suppressClickUntil = 0, holdUntil = 0, active = -1;
    let yaw = 0, pitch = 0, aimYaw = 0, aimPitch = 0;
    let rotation = null, rotationOrigin = 0;
    let shadeAnimations = [];
    let introSettled = false, lastDepthUpdate = -Infinity, cameraTransform = '';
    const cardWidth = 280, cardHeight = 280, gap = 24;
    const rotationSpeed = -14;
    // Repeat only the existing photos to close the ring, like a looping slider.
    // Duplicates are visual only; the viewer and accessible collection stay at six.
    const repetitions = Math.ceil(10 / cards.length);
    const slotCount = enhanced ? cards.length * repetitions : cards.length;
    const step = 360 / slotCount;
    const radius = slotCount * (cardWidth + gap) / (Math.PI * 2);
    const introLength = 1350;
    const isIntro = now => introStart !== null && now - introStart < introLength;
    const blocked = () => paused || motion.matches || hover || keyboard || modalOpen;
    let openFromCarousel = card => card.click();
    let canAnimateShade = false;
    try {
        canAnimateShade = new KeyframeEffect(null, [], { pseudoElement: '::after' }).pseudoElement === '::after';
    } catch (_) { /* Older engines keep the sampled depth tint instead. */ }
    const depthAt = degrees => Math.pow((1 - Math.cos(degrees * radians)) / 2, 1.25) * .65;

    function activeSlot() { return mod(Math.round(-angle / step), slotCount); }
    function announce() { live.textContent = `Creation ${mod(activeSlot(), cards.length) + 1} of ${cards.length}`; }
    function readRotation() {
        if (rotation) angle = rotationOrigin + rotationSpeed * (Number(rotation.currentTime) || 0) / 1000;
    }
    function stopRotation() {
        if (!rotation) return;
        readRotation();
        // Commit the exact visible angle before handing control back to drag/spring motion.
        ring.style.transform = `rotateY(${angle}deg)`;
        slots.forEach((slot, i) => {
            slot.depth = depthAt(i * step + angle).toFixed(3);
            slot.card.style.setProperty('--creation-depth', slot.depth);
        });
        shadeAnimations.forEach(animation => animation.cancel());
        shadeAnimations = [];
        rotation.cancel();
        rotation = null;
    }
    function startRotation() {
        if (rotation || typeof ring.animate !== 'function') return;
        rotationOrigin = angle;
        rotation = ring.animate([
            { transform: `rotateY(${rotationOrigin}deg)` },
            { transform: `rotateY(${rotationOrigin - 360}deg)` }
        ], { duration: 360 / Math.abs(rotationSpeed) * 1000, iterations: Infinity, easing: 'linear' });
        rotation.id = 'creation-ring-rotation';
        const start = document.timeline.currentTime;
        rotation.startTime = start;
        if (canAnimateShade) {
            // Opacity follows the same clock as rotation, with no inherited style
            // invalidations on the main thread during steady autoplay.
            slots.forEach((slot, index) => {
                const keyframes = Array.from({ length: 49 }, (_, i) => ({
                    offset: i / 48, opacity: depthAt(index * step + rotationOrigin - i * 360 / 48)
                }));
                slot.card.querySelectorAll('.creation-strip').forEach(strip => {
                    const shade = strip.animate(keyframes, {
                        duration: 360 / Math.abs(rotationSpeed) * 1000,
                        iterations: Infinity, easing: 'linear', pseudoElement: '::after'
                    });
                    shade.startTime = start;
                    shadeAnimations.push(shade);
                });
            });
        }
    }
    function stop() {
        stopRotation();
        cancelAnimationFrame(frame);
        frame = 0;
        lastTime = 0;
    }
    function wake() {
        if (enhanced && visible && entered && !document.hidden && !modalOpen && !frame) frame = requestAnimationFrame(tick);
    }
    function hold(duration = 2400) {
        holdUntil = performance.now() + duration;
        clearTimeout(resumeTimer);
        resumeTimer = setTimeout(wake, duration + 20);
    }
    function updateRotationButton() {
        const stopped = paused || motion.matches;
        rotationButton.setAttribute('aria-pressed', String(stopped));
        rotationButton.setAttribute('aria-label', motion.matches ? 'Automatic rotation disabled for reduced motion' : stopped ? 'Resume automatic rotation' : 'Pause automatic rotation');
        rotationButton.disabled = motion.matches;
    }
    function draw(now = performance.now()) {
        if (!enhanced) return;
        readRotation();
        const nextCamera = `translateZ(${-radius}px) rotateX(${(-5 + pitch).toFixed(4)}deg) rotateY(${yaw.toFixed(4)}deg)`;
        if (nextCamera !== cameraTransform) {
            camera.style.transform = nextCamera;
            cameraTransform = nextCamera;
        }
        if (!rotation) ring.style.transform = `rotateY(${angle}deg)`;
        const elapsed = introStart === null ? introLength : now - introStart;
        const intro = isIntro(now) && !motion.matches;
        const positionCards = intro || !introSettled;
        // The cylinder's geometry is static after entry. During gestures, sample
        // the slower depth tint without invalidating inherited styles every frame.
        if (positionCards || (!shadeAnimations.length && now - lastDepthUpdate >= 80)) {
            slots.forEach((slot, i) => {
                const facing = Math.cos((i * step + angle) * radians);
                if (positionCards) {
                    const distance = Math.acos(clamp(facing, -1, 1)) / Math.PI;
                    const progress = intro ? clamp((elapsed - distance * 380) / 900, 0, 1) : 1;
                    const lift = Math.pow(1 - progress, 4) * 260;
                    slot.item.style.transform = `rotateY(${i * step}deg) translateZ(${radius}px) translateY(${lift}px)`;
                    const entrance = clamp(progress * 3, 0, 1).toFixed(3);
                    if (entrance !== slot.entrance) {
                        slot.card.style.setProperty('--creation-entrance', entrance);
                        slot.entrance = entrance;
                    }
                }
                const depth = depthAt(i * step + angle).toFixed(3);
                if (depth !== slot.depth) {
                    slot.card.style.setProperty('--creation-depth', depth);
                    slot.depth = depth;
                }
            });
            lastDepthUpdate = now;
            introSettled = !intro;
        }
        const nextActive = mod(activeSlot(), cards.length);
        if (active !== nextActive) {
            active = nextActive;
            positionLabel.firstChild.textContent = `${String(active + 1).padStart(2, '0')} `;
            root.dataset.activeIndex = String(active);
        }
    }
    function tick(now) {
        frame = 0;
        const dt = lastTime ? Math.min((now - lastTime) / 1000, .04) : 1 / 60;
        lastTime = now;
        const intro = isIntro(now);
        const cruise = !blocked() && !press && now >= holdUntil && !intro ? rotationSpeed : 0;
        if (rotation) {
            readRotation();
            if (!cruise || target !== null) stopRotation();
        }
        if (!rotation && !press && !intro) {
            if (target !== null) {
                // Critically damped spring, integrated in small steps for stable resizing/frame drops.
                let remaining = dt;
                while (remaining > 0) {
                    const h = Math.min(remaining, 1 / 120);
                    velocity += ((target - angle) * 130 - velocity * 23) * h;
                    angle += velocity * h;
                    remaining -= h;
                }
                if (Math.abs(target - angle) < .015 && Math.abs(velocity) < .1) {
                    angle = target;
                    target = null;
                    velocity = 0;
                }
            } else {
                velocity += (cruise - velocity) * (1 - Math.exp(-dt / .3));
                angle += velocity * dt;
                if (!cruise && Math.abs(velocity) < .08) velocity = 0;
            }
            // Constant autoplay runs on the compositor. A busy main thread can
            // no longer stall the rotation; gestures still use the same angle.
            if (cruise && target === null && Math.abs(velocity - cruise) < .05) {
                velocity = cruise;
                startRotation();
            }
        }
        const ease = 1 - Math.exp(-dt / .3);
        yaw += (aimYaw - yaw) * ease;
        pitch += (aimPitch - pitch) * ease;
        draw(now);
        const unsettled = Math.abs(aimYaw - yaw) > .01 || Math.abs(aimPitch - pitch) > .01;
        if (intro || target !== null || Math.abs(velocity) > .01 || cruise || unsettled) wake();
        else lastTime = 0;
    }
    function goTo(destination, immediate = false) {
        if (!enhanced) return;
        stopRotation();
        let next = -destination * step;
        next += 360 * Math.round((angle - next) / 360);
        if (immediate || motion.matches) {
            angle = next;
            target = null;
            velocity = 0;
            draw();
        } else target = next;
        hold();
        wake();
    }
    function goBy(direction) {
        readRotation();
        const base = target === null ? Math.round(-angle / step) : Math.round(-target / step);
        goTo(base + direction);
        live.textContent = `Creation ${mod(base + direction, cards.length) + 1} of ${cards.length}`;
    }
    function focusPhoto(index) {
        const nearest = Math.round(-angle / step);
        const destination = index + cards.length * Math.round((nearest - index) / cards.length);
        goTo(destination, true);
    }
    function getPhotoRect(card) {
        const surfaces = [...card.querySelectorAll('.creation-strip')];
        if (!surfaces.length) return card.querySelector('img').getBoundingClientRect();
        const rects = surfaces.map(el => el.getBoundingClientRect());
        const left = Math.min(...rects.map(rect => rect.left));
        const top = Math.min(...rects.map(rect => rect.top));
        const right = Math.max(...rects.map(rect => rect.right));
        const bottom = Math.max(...rects.map(rect => rect.bottom));
        return { left, top, right, bottom, width: right - left, height: bottom - top };
    }
    function frontCard(index) {
        if (!enhanced) return cards[index];
        return slots.reduce((best, slot, i) => {
            if (i % cards.length !== index) return best;
            const distance = Math.abs(Math.atan2(Math.sin((angle + i * step) * radians), Math.cos((angle + i * step) * radians)));
            return !best || distance < best.distance ? { card: slot.card, distance } : best;
        }, null).card;
    }
    function measure() {
        resizeFrame = 0;
        if (!enhanced) return;
        const width = viewport.clientWidth;
        // Desktop shows the whole cylinder. Mobile keeps tappable cards and side peeks.
        fit = width <= 640 ? clamp(width / 500, .64, .92) : Math.min(1, width * .94 / (radius * 2));
        scene.style.transform = `scale(${fit})`;
        draw();
        wake();
    }
    function scheduleMeasure() { if (!resizeFrame) resizeFrame = requestAnimationFrame(measure); }

    function createStrips(card) {
        const photo = card.querySelector('.creation-photo');
        const fragments = document.createDocumentFragment();
        const slices = 8;
        for (let i = 0; i < slices; i++) {
            const start = i * cardWidth / slices;
            const end = (i + 1) * cardWidth / slices;
            const width = end - start + (i < slices - 1 ? .8 : 0);
            const middle = (start + end) / 2 - cardWidth / 2;
            const theta = middle / radius;
            const strip = document.createElement('span');
            strip.className = 'creation-strip';
            strip.setAttribute('aria-hidden', 'true');
            Object.assign(strip.style, {
                width: `${width}px`, height: `${cardHeight}px`, left: `${-width / 2}px`, top: `${-cardHeight / 2}px`,
                transform: `translate3d(${radius * Math.sin(theta)}px, 0, ${radius * (Math.cos(theta) - 1)}px) rotateY(${theta / radians}deg)`,
                borderRadius: i === 0 ? '12px 0 0 12px' : i === slices - 1 ? '0 12px 12px 0' : '0'
            });
            const image = document.createElement('span');
            image.className = 'creation-strip__image';
            Object.assign(image.style, { width: `${cardWidth}px`, height: `${cardHeight}px`, left: `${-start}px` });
            strip.append(image);
            fragments.append(strip);
        }
        photo.append(fragments);
    }
    if (enhanced) {
        for (let repeat = 0; repeat < repetitions; repeat++) {
            cards.forEach((original, index) => {
                const item = repeat ? original.closest('.creation-item').cloneNode(true) : original.closest('.creation-item');
                const card = item.querySelector('.creation-card');
                if (repeat) {
                    // Clone the semantic markup, not the already-built geometry.
                    item.querySelectorAll('.creation-strip').forEach(strip => strip.remove());
                    item.setAttribute('aria-hidden', 'true');
                    card.removeAttribute('data-creation');
                    ring.append(item);
                }
                card.tabIndex = -1;
                card.dataset.photoIndex = index;
                createStrips(card);
                slots.push({ item, card });
            });
        }
        root.classList.add('carousel-ready');
        viewport.tabIndex = 0;
        navigation.hidden = false;
        measure();
        updateRotationButton();
    }
    function loadPhotos() {
        cards.forEach((card, index) => {
            const image = card.querySelector('img');
            const copies = enhanced ? slots.filter((slot, i) => i % cards.length === index).map(slot => slot.card) : [card];
            const loaded = () => copies.forEach(copy => {
                copy.querySelectorAll('.creation-strip__image').forEach(surface => {
                    surface.style.backgroundImage = `url(${JSON.stringify(image.currentSrc || image.src)})`;
                });
            });
            const failed = () => copies.forEach(copy => {
                copy.querySelector('.creation-photo').classList.add('is-unavailable');
                copy.querySelector('.creation-unavailable').hidden = false;
            });
            image.addEventListener('load', loaded, { once: true });
            image.addEventListener('error', failed, { once: true });
            image.loading = 'eager';
            if (image.complete) image.naturalWidth ? loaded() : failed();
        });
    }
    function enter() {
        if (!entered) {
            entered = true;
            introStart = motion.matches ? null : performance.now();
            introSettled = false;
            root.classList.add('is-visible');
        }
        wake();
    }
    if ('IntersectionObserver' in window) {
        const preload = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) { loadPhotos(); preload.disconnect(); }
        }, { rootMargin: '600px' });
        preload.observe(root);
        const visibility = new IntersectionObserver(([entry]) => {
            visible = entry.isIntersecting;
            if (visible) enter();
            else { cancelDrag(); stop(); }
        }, { threshold: .08 });
        visibility.observe(viewport);
    } else { loadPhotos(); enter(); }
    if ('ResizeObserver' in window) new ResizeObserver(scheduleMeasure).observe(viewport);
    window.addEventListener('resize', scheduleMeasure, { passive: true });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) { cancelDrag(); stop(); }
        else wake();
    });
    window.addEventListener('blur', () => { cancelDrag(); hover = false; aimYaw = aimPitch = 0; });

    function cancelDrag() {
        if (!press) return;
        const id = press.id;
        const dragged = press.dragged;
        press = null;
        root.classList.remove('is-dragging');
        if (viewport.hasPointerCapture(id)) viewport.releasePointerCapture(id);
        if (dragged) {
            suppressClickUntil = performance.now() + 450;
            target = Math.round(angle / step) * step;
            velocity = 0;
        }
        wake();
    }
    if (enhanced) {
        viewport.addEventListener('pointerenter', event => {
            if (event.pointerType !== 'mouse') return;
            hover = true;
            wake();
        });
        viewport.addEventListener('pointerleave', () => { hover = false; aimYaw = aimPitch = 0; wake(); });
        viewport.addEventListener('pointerdown', event => {
            if (!event.isPrimary) { cancelDrag(); return; }
            if (event.button !== 0) return;
            stopRotation();
            if (isIntro(performance.now())) { introStart = null; draw(); }
            press = { id: event.pointerId, x: event.clientX, y: event.clientY, lastX: event.clientX, time: performance.now(), dragged: false };
            target = null;
            velocity = 0;
            hold();
        });
        viewport.addEventListener('pointermove', event => {
            if (!press) {
                if (event.pointerType === 'mouse' && !motion.matches) {
                    const rect = viewport.getBoundingClientRect();
                    aimYaw = ((event.clientX - rect.left) / rect.width - .5) * 4;
                    aimPitch = -((event.clientY - rect.top) / rect.height - .5) * 2;
                    wake();
                }
                return;
            }
            if (event.pointerId !== press.id) return;
            const dx = event.clientX - press.x, dy = event.clientY - press.y;
            if (!press.dragged) {
                if (Math.max(Math.abs(dx), Math.abs(dy)) < 6) return;
                if (Math.abs(dy) > Math.abs(dx) && event.pointerType !== 'mouse') { cancelDrag(); return; }
                press.dragged = true;
                viewport.setPointerCapture(event.pointerId);
                root.classList.add('is-dragging');
            }
            event.preventDefault();
            const now = performance.now();
            const change = (event.clientX - press.lastX) * 180 / (Math.PI * radius * fit);
            const speed = change / Math.max((now - press.time) / 1000, .008);
            angle += change;
            velocity = clamp(velocity * .35 + speed * .65, -360, 360);
            press.lastX = event.clientX;
            press.time = now;
            draw();
        });
        viewport.addEventListener('pointerup', event => {
            if (!press || event.pointerId !== press.id) return;
            const dragged = press.dragged;
            const recent = performance.now() - press.time < 100;
            press = null;
            root.classList.remove('is-dragging');
            if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
            if (dragged) {
                suppressClickUntil = performance.now() + 450;
                const coast = !motion.matches && recent ? clamp(velocity * .16, -step * 2, step * 2) : 0;
                const destination = Math.round((angle + coast) / step) * step;
                if (motion.matches) { angle = destination; target = null; velocity = 0; draw(); }
                else target = destination;
                hold();
                live.textContent = `Creation ${mod(Math.round(-destination / step), cards.length) + 1} of ${cards.length}`;
            }
            wake();
        });
        viewport.addEventListener('pointercancel', cancelDrag);
        viewport.addEventListener('lostpointercapture', event => {
            // Touch starts with implicit capture on the image strip. Transferring
            // it to the viewport emits a bubbling loss from that strip, not a cancellation.
            if (event.target === viewport && !viewport.hasPointerCapture(event.pointerId)) cancelDrag();
        });
        viewport.addEventListener('dragstart', event => event.preventDefault());
        viewport.addEventListener('click', event => {
            if (performance.now() < suppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); }
        }, true);
        viewport.addEventListener('wheel', event => {
            if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) || event.ctrlKey) return;
            event.preventDefault();
            stopRotation();
            const multiplier = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientWidth : 1;
            angle -= event.deltaX * multiplier * 180 / (Math.PI * radius * fit);
            velocity = 0;
            target = null;
            hold();
            draw();
            clearTimeout(wheelTimer);
            wheelTimer = setTimeout(() => { goTo(Math.round(-angle / step)); announce(); }, 140);
        }, { passive: false });
        viewport.addEventListener('focus', () => { keyboard = viewport.matches(':focus-visible'); wake(); });
        viewport.addEventListener('blur', () => { keyboard = false; wake(); });
        viewport.addEventListener('keydown', event => {
            if (event.altKey || event.ctrlKey || event.metaKey) return;
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter', ' '].includes(event.key)) return;
            event.preventDefault();
            keyboard = true;
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') goBy(event.key === 'ArrowLeft' ? -1 : 1);
            else if (event.key === 'Home' || event.key === 'End') {
                const destination = event.key === 'Home' ? 0 : cards.length - 1;
                goTo(destination);
                live.textContent = `Creation ${destination + 1} of ${cards.length}`;
            }
            else openFromCarousel(frontCard(mod(activeSlot(), cards.length)));
        });
        root.querySelector('[data-carousel-previous]').addEventListener('click', () => goBy(-1));
        root.querySelector('[data-carousel-next]').addEventListener('click', () => goBy(1));
        rotationButton.addEventListener('click', () => {
            readRotation();
            paused = !paused;
            if (!paused) holdUntil = 0;
            else target = Math.round(angle / step) * step;
            updateRotationButton();
            wake();
        });
    }
    motion.addEventListener('change', () => {
        stopRotation();
        introStart = null;
        introSettled = false;
        velocity = 0;
        target = null;
        yaw = pitch = aimYaw = aimPitch = 0;
        updateRotationButton();
        draw();
        wake();
    });

    const viewer = document.getElementById('creationViewer');
    if (!viewer || typeof viewer.showModal !== 'function') return;
    const image = viewer.querySelector('.creation-viewer__image');
    const stage = viewer.querySelector('.creation-viewer__stage');
    const status = viewer.querySelector('.creation-viewer__status');
    const caption = viewer.querySelector('.creation-viewer__caption');
    const counter = viewer.querySelector('.creation-viewer__counter');
    const previous = viewer.querySelector('.creation-viewer__previous');
    const next = viewer.querySelector('.creation-viewer__next');
    const close = viewer.querySelector('.creation-viewer__close');
    let index = 0;
    let request = 0;
    let opener = null;
    let overflow = '';
    let animation = null;
    let touch = null;
    let closing = false;
    let closeTimer = 0;

    function stopAnimation() {
        if (animation) animation.cancel();
        animation = null;
    }

    function animatePhoto(from, opening) {
        stopAnimation();
        if (motion.matches || !viewer.open || image.hidden) return;
        const target = image.getBoundingClientRect();
        const source = from || target;
        const dx = (source.left + source.width / 2) - (target.left + target.width / 2);
        const dy = (source.top + source.height / 2) - (target.top + target.height / 2);
        const scale = target.width ? source.width / target.width : 1;
        const origin = from ? `translate(${dx}px, ${dy}px) scale(${scale})` : 'translateY(8px) scale(.985)';
        animation = image.animate(opening ? [
            { transform: origin, opacity: from ? .7 : 0 },
            { transform: 'none', opacity: 1 }
        ] : [
            { transform: 'none', opacity: 1 },
            { transform: origin, opacity: .15 }
        ], { duration: opening ? 320 : 180, easing: 'cubic-bezier(.2,.7,.25,1)' });
    }

    function showPhoto(destination, sourceRect) {
        index = (destination + cards.length) % cards.length;
        if (!sourceRect) focusPhoto(index);
        const currentRequest = ++request;
        stopAnimation();
        image.hidden = true;
        stage.setAttribute('aria-busy', 'true');
        status.textContent = 'Loading photo…';
        status.hidden = false;
        counter.textContent = `${index + 1} / ${cards.length}`;
        caption.textContent = cards[index].dataset.caption || '';
        caption.hidden = !caption.textContent;
        previous.disabled = next.disabled = cards.length < 2;
        const loader = new Image();
        loader.onload = () => {
            if (currentRequest !== request || !viewer.open || closing) return;
            image.src = loader.src;
            image.alt = cards[index].querySelector('img').alt;
            image.hidden = false;
            status.hidden = true;
            stage.setAttribute('aria-busy', 'false');
            requestAnimationFrame(() => {
                if (currentRequest === request && viewer.open && !closing) animatePhoto(sourceRect, true);
            });
        };
        loader.onerror = () => {
            if (currentRequest !== request || !viewer.open || closing) return;
            stage.setAttribute('aria-busy', 'false');
            status.textContent = 'This photo could not be loaded. Try the next photo.';
            status.hidden = false;
        };
        loader.src = cards[index].href;
    }

    function openPhoto(card, destination) {
        const source = getPhotoRect(card);
        modalOpen = true;
        stop();
        opener = card;
        closing = false;
        clearTimeout(closeTimer);
        overflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        viewer.showModal();
        showPhoto(destination, source);
    }

    function finishClose() {
        clearTimeout(closeTimer);
        if (viewer.open) viewer.close();
    }

    function closePhoto() {
        if (!viewer.open || closing) return;
        closing = true;
        ++request;
        if (motion.matches || image.hidden) return finishClose();
        const destination = getPhotoRect(frontCard(index));
        // Only return to a thumbnail when it is actually in the viewport.
        const visible = destination.bottom > 0 && destination.top < innerHeight;
        animatePhoto(visible ? destination : null, false);
        closeTimer = setTimeout(finishClose, 180);
    }

    openFromCarousel = card => openPhoto(card, Number(card.dataset.photoIndex || cards.indexOf(card)));
    root.addEventListener('click', event => {
        const card = event.target.closest('.creation-card');
        if (!card || !root.contains(card) || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        openFromCarousel(card);
    });
    previous.addEventListener('click', () => { if (!closing) showPhoto(index - 1); });
    next.addEventListener('click', () => { if (!closing) showPhoto(index + 1); });
    close.addEventListener('click', closePhoto);
    viewer.addEventListener('cancel', event => { event.preventDefault(); closePhoto(); });
    viewer.addEventListener('keydown', event => {
        if (event.key === 'Tab') {
            const controls = [...viewer.querySelectorAll('button:not(:disabled), [tabindex="0"]')].filter(el => el.getClientRects().length);
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
            return;
        }
        if (closing || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
        event.preventDefault();
        showPhoto(index + (event.key === 'ArrowLeft' ? -1 : 1));
    });
    viewer.addEventListener('click', event => {
        if (event.target !== viewer) return;
        const rect = viewer.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closePhoto();
    });
    viewer.addEventListener('close', () => {
        ++request;
        stopAnimation();
        clearTimeout(closeTimer);
        closing = false;
        touch = null;
        document.body.style.overflow = overflow;
        if (enhanced) viewport.focus({ preventScroll: true });
        else if (opener && opener.isConnected) opener.focus({ preventScroll: true });
        modalOpen = false;
        hold();
        wake();
    });
    stage.addEventListener('touchstart', event => {
        touch = event.touches.length === 1 ? { x: event.touches[0].clientX, y: event.touches[0].clientY } : null;
    }, { passive: true });
    stage.addEventListener('touchmove', event => { if (event.touches.length !== 1) touch = null; }, { passive: true });
    stage.addEventListener('touchcancel', () => { touch = null; }, { passive: true });
    stage.addEventListener('touchend', event => {
        if (!touch || closing || !event.changedTouches.length) return;
        const dx = event.changedTouches[0].clientX - touch.x;
        const dy = event.changedTouches[0].clientY - touch.y;
        touch = null;
        if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.4) showPhoto(index + (dx < 0 ? 1 : -1));
    }, { passive: true });
    motion.addEventListener('change', () => {
        stopAnimation();
        if (closing) finishClose();
    });
})();
