/* A short photo introduction. Reloads replay; ordinary in-site navigation stays immediate. */
(() => {
    'use strict';
    const key = 'balloorina-welcome-seen';
    const root = document.documentElement;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const timers = new Set();
    let screen, previousFocus, started = false, finished = false, leaving = false;

    function later(callback, delay) {
        const timer = setTimeout(() => { timers.delete(timer); callback(); }, delay);
        timers.add(timer);
    }
    function cleanup() {
        if (finished) return;
        finished = true;
        timers.forEach(clearTimeout);
        timers.clear();
        root.removeAttribute('data-welcome-active');
        motion.removeEventListener('change', onMotionChange);
        window.removeEventListener('pagehide', cleanup);
        window.removeEventListener('pageshow', onPageShow);
        if (screen?.open) screen.close();
        screen?.remove();
        if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus({preventScroll: true});
    }

    function prepareCollage() {
        const sources = [...screen.querySelector('[data-welcome-images]').content.querySelectorAll('img')];
        const film = screen.querySelector('.welcome-screen__film-strip');
        if (sources.length) screen.querySelectorAll('[data-welcome-back]').forEach(card => {
            card.append(sources[Number(card.dataset.welcomeBack) % sources.length].cloneNode());
        });
        // Six vertical frames give the reference's fast rolling-image passage.
        for (let index = 0; index < 6 && sources.length; index++) {
            const frame = document.createElement('div');
            frame.className = 'welcome-screen__film-frame';
            const photo = sources[index % sources.length].cloneNode();
            photo.setAttribute('data-welcome-freeze', '');
            frame.append(photo);
            film.append(frame);
        }
        screen.querySelectorAll('[data-welcome-lane]').forEach((lane, column) => {
            const group = document.createElement('div');
            group.className = 'welcome-screen__group';
            for (let index = 0; index < Math.min(3, sources.length); index++) {
                const sourceIndex = (column * 2 + index * (column % 2 ? -1 : 1) + sources.length) % sources.length;
                const card = document.createElement('figure');
                card.className = 'welcome-screen__card';
                const photo = sources[sourceIndex].cloneNode();
                const caption = document.createElement('figcaption');
                const label = document.createElement('span');
                label.textContent = 'Selected celebrations';
                const number = document.createElement('span');
                number.textContent = String(sourceIndex + 1).padStart(2, '0');
                caption.append(label, number);
                card.append(photo, caption);
                group.append(card);
            }
            const track = lane.querySelector('.welcome-screen__track');
            track.append(group, group.cloneNode(true));
        });
    }

    function playSequence() {
        // CSS runs one accelerating film movement and one continuous tilt-to-center.
        // Phase changes happen only after those movements settle on the final image.
        later(() => { screen.dataset.welcomePhase = 'portrait'; }, 1850);
        later(() => { screen.dataset.welcomePhase = 'retract'; }, 3850);
        later(() => { screen.dataset.welcomePhase = 'collage'; }, 4800);
        later(() => dismiss(), 7200);
    }

    function splitScene() {
        const scene = screen.querySelector('.welcome-screen__scene');
        const panelLayer = screen.querySelector('.welcome-screen__panels');
        const box = screen.getBoundingClientRect();
        // Preserve all running animation positions so the split starts without a flash or jump.
        const frozen = [...scene.querySelectorAll('[data-welcome-freeze], .welcome-screen__lane, .welcome-screen__content, .welcome-screen__enter')].map(element => {
            const style = getComputedStyle(element);
            const frozenStyle = {transform: style.transform, opacity: style.opacity, clipPath: style.clipPath};
            if (element.classList.contains('welcome-screen__film')) {
                frozenStyle.width = style.width;
                frozenStyle.height = style.height;
            }
            return frozenStyle;
        });
        for (let index = 0; index < 4; index++) {
            const panel = document.createElement('div');
            panel.className = 'welcome-screen__panel';
            panel.style.setProperty('--panel', index);
            const snapshot = scene.cloneNode(true);
            snapshot.classList.add('welcome-screen__snapshot');
            snapshot.inert = true;
            Object.assign(snapshot.style, {
                width: box.width + 'px', height: box.height + 'px', left: -index * box.width / 4 + 'px'
            });
            snapshot.querySelectorAll('[data-welcome-freeze], .welcome-screen__lane, .welcome-screen__content, .welcome-screen__enter').forEach((element, position) => {
                Object.assign(element.style, frozen[position]);
            });
            const ids = new Map();
            snapshot.querySelectorAll('[id]').forEach(element => {
                const original = element.id;
                element.id = 'welcomeExit' + index + '-' + original;
                ids.set(original, element.id);
            });
            snapshot.querySelectorAll('[href^="#"]').forEach(element => {
                const replacement = ids.get(element.getAttribute('href').slice(1));
                if (replacement) element.setAttribute('href', '#' + replacement);
            });
            panel.append(snapshot);
            panelLayer.append(panel);
        }
    }

    function dismiss(immediate = false) {
        if (finished) return;
        if (immediate || motion.matches) { cleanup(); return; }
        if (leaving) return;
        leaving = true;
        timers.forEach(clearTimeout);
        timers.clear();
        // Independent of animationend: never leave the modal trapping the page.
        later(cleanup, 1650);
        try { splitScene(); } catch (_) { cleanup(); return; }
        screen.setAttribute('data-leaving', '');
    }
    function onMotionChange() { if (motion.matches) dismiss(true); }
    function onPageShow(event) { if (event.persisted) cleanup(); }

    function mount() {
        if (started) return;
        started = true;
        screen = document.getElementById('siteWelcome');
        if (!screen) return;
        let seen = false;
        try { seen = sessionStorage.getItem(key) === '1'; } catch (_) { /* Storage is optional. */ }
        const navigation = performance.getEntriesByType('navigation')[0]?.type;
        const reloading = navigation === 'reload' || performance.navigation?.type === 1;
        if ((seen && !reloading) || navigation === 'back_forward' || typeof screen.showModal !== 'function' ||
            getComputedStyle(screen).getPropertyValue('--welcome-ready').trim() !== '1') {
            screen.remove();
            return;
        }

        previousFocus = document.activeElement;
        screen.addEventListener('error', event => {
            const card = event.target.closest?.('.welcome-screen__card');
            if (card) card.style.visibility = 'hidden';
        }, true);
        screen.querySelectorAll('[data-welcome-skip], [data-welcome-enter]').forEach(button => button.addEventListener('click', () => dismiss()));
        screen.addEventListener('cancel', event => { event.preventDefault(); dismiss(true); });
        screen.addEventListener('close', cleanup, {once: true});
        screen.addEventListener('animationend', event => {
            if (event.animationName === 'welcome-panel-exit' && event.target === screen.querySelector('.welcome-screen__panel:last-child')) cleanup();
        });
        window.addEventListener('pagehide', cleanup);
        window.addEventListener('pageshow', onPageShow);
        motion.addEventListener('change', onMotionChange);
        later(cleanup, 10000);
        try {
            prepareCollage();
            screen.showModal();
            screen.focus({preventScroll: true});
            root.setAttribute('data-welcome-active', '');
            try { sessionStorage.setItem(key, '1'); } catch (_) { /* Keep working without storage. */ }
            screen.querySelector('[data-welcome-announcement]').textContent =
                'Welcome to ' + screen.querySelector('#welcomeTitle').getAttribute('aria-label') + '.';
        } catch (_) {
            cleanup();
            return;
        }
        if (motion.matches) { later(cleanup, 180); return; }
        playSequence();
    }
    window.BalloorinaWelcome = {mount};
})();
