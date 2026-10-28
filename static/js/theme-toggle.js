/**
 * Theme Toggle - Light/Dark Mode
 * Shared between client and admin sides
 * Saves preference to localStorage
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'balloorina-theme';
    const root = document.documentElement;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const currentTheme = () => root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    let desiredTheme, activeJob = null, latestOrigin = null;

    // Apply saved theme IMMEDIATELY (before DOM ready) to prevent flash
    function applyStoredTheme() {
        let saved;
        try { saved = localStorage.getItem(STORAGE_KEY); } catch (_) { /* Storage may be unavailable. */ }
        if (saved === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    }

    // Run immediately
    applyStoredTheme();
    desiredTheme = currentTheme();

    function applyTheme(theme) {
        if (theme === 'light') root.setAttribute('data-theme', 'light');
        else root.removeAttribute('data-theme');
        try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) { /* Switching still works. */ }
        updateToggleButtons();
    }

    function stopAnimation() {
        activeJob?.animation?.cancel();
        activeJob?.transition?.skipTransition();
        activeJob?.finishFallback?.();
    }

    async function changeTheme(origin) {
        if (desiredTheme === currentTheme()) return;
        const theme = desiredTheme, job = {};
        activeJob = job;
        try {
            if (reducedMotion.matches || !document.body) {
                applyTheme(theme);
            } else if (typeof document.startViewTransition === 'function') {
                const reveal = root.dataset.themeEffect === 'radial';
                if (reveal) root.classList.add('theme-revealing');
                job.transition = document.startViewTransition(() => applyTheme(theme));
                // Icons and storage update with the new snapshot, never one click late.
                await job.transition.updateCallbackDone;
                await job.transition.ready;
                if (reducedMotion.matches || desiredTheme !== theme) job.transition.skipTransition();
                else if (reveal) {
                    const x = Math.min(innerWidth, Math.max(0, origin?.x ?? innerWidth / 2));
                    const y = Math.min(innerHeight, Math.max(0, origin?.y ?? innerHeight / 2));
                    const radius = Math.ceil(Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y)));
                    job.animation = root.animate([
                        { clipPath: `circle(0px at ${x}px ${y}px)` },
                        { clipPath: `circle(${radius}px at ${x}px ${y}px)` }
                    ], { duration: 520, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both',
                        pseudoElement: '::view-transition-new(root)', id: 'theme-reveal' });
                    await job.animation.finished.catch(() => {});
                }
                await job.transition.finished.catch(() => {});
            } else {
                root.classList.add('theme-animating');
                applyTheme(theme);
                await new Promise(resolve => {
                    const timer = setTimeout(resolve, 350);
                    job.finishFallback = () => { clearTimeout(timer); resolve(); };
                });
            }
        } catch (_) {
            // A skipped/interrupted snapshot still runs its update callback.
            if (job.transition) {
                await job.transition.updateCallbackDone.catch(() => {});
                job.transition.finished.catch(() => {});
            }
            if (currentTheme() !== theme) applyTheme(theme);
        } finally {
            job.animation?.cancel();
            root.classList.remove('theme-revealing', 'theme-animating');
            document.querySelectorAll('.theme-toggle-btn').forEach(button => button.classList.remove('is-switching'));
            activeJob = null;
            if (desiredTheme !== currentTheme()) changeTheme(latestOrigin);
        }
    }

    function toggleTheme(source) {
        if (!activeJob) desiredTheme = currentTheme();
        desiredTheme = desiredTheme === 'light' ? 'dark' : 'light';
        const candidate = source?.currentTarget || source;
        const button = candidate instanceof Element ? candidate :
            [...document.querySelectorAll('.theme-toggle-btn')].find(element => element.getClientRects().length);
        const rect = button?.getBoundingClientRect();
        latestOrigin = rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : null;
        if (activeJob) stopAnimation();
        else changeTheme(latestOrigin);
    }

    // Update all toggle buttons on the page
    function updateToggleButtons() {
        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
            const label = isLight ? 'Switch to dark mode' : 'Switch to light mode';
            btn.setAttribute('aria-label', label);
            btn.setAttribute('title', label);
            btn.dataset.themeTarget = isLight ? 'dark' : 'light';
            const sunIcon = btn.querySelector('.theme-icon-sun');
            const moonIcon = btn.querySelector('.theme-icon-moon');
            if (sunIcon && moonIcon) {
                if (isLight) {
                    sunIcon.style.display = 'none';
                    moonIcon.style.display = 'block';
                } else {
                    sunIcon.style.display = 'block';
                    moonIcon.style.display = 'none';
                }
            }
            if (activeJob && !reducedMotion.matches) {
                btn.classList.remove('is-switching');
                void btn.offsetWidth;
                btn.classList.add('is-switching');
            }
        });
    }

    window.addEventListener('storage', event => {
        if (event.key !== STORAGE_KEY && event.key !== null) return;
        desiredTheme = event.newValue === 'light' ? 'light' : 'dark';
        if (activeJob) stopAnimation();
        else applyTheme(desiredTheme);
    });
    reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) stopAnimation(); });

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        // Attach click handlers to all toggle buttons
        document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                toggleTheme(e);
            });
        });

        // Set initial icon state
        updateToggleButtons();

        // Navbar: border/shadow only appears once the page is scrolled.
        // Once on, it stays on until fully back at the top (prevents blinking
        // from small scroll jitters around the threshold).
        const navEl = document.querySelector('nav.navbar');
        if (navEl) {
            const toggleNavScroll = function () {
                if (window.scrollY > 10) {
                    navEl.classList.add('scrolled');
                } else if (window.scrollY <= 0) {
                    navEl.classList.remove('scrolled');
                }
            };
            window.addEventListener('scroll', toggleNavScroll, { passive: true });
            toggleNavScroll();
        }

        // Scroll reveal: staggered per-element fade/slide within each section.
        // Works on any page wrapper with section children (home #home, about #about, services #services ...)
        const revealPages = ['home', 'about', 'services']
            .map(function (id) { return document.getElementById(id); })
            .filter(Boolean);

        if (revealPages.length && 'IntersectionObserver' in window) {
            const REVEAL_SELECTOR = [
                '.section-header > *',
                '.story-media',
                '.story-label',
                '.story-text h2',
                '.story-text p',
                '.story-points li',
                '.journey-list .journey-num-wrap',
                '.journey-list .journey-copy',
                '.values-grid > .value-card',
                '.occasion-chips > .occasion-chip',
                '.stats-card > .stat-item',
                '.features-grid > .feature-card',
                '.hiw-grid > .hiw-step',
                '.testimonial-carousel',
                '.faq-list > .faq-item',
                '.cta-banner > *',
                '.service-item .service-content > *',
                '.service-item .service-image',
                '.comparison-title',
                '.comparison-subtitle',
                '.comparison-table-wrap',
                '.services-tools-inner > .tool-card'
            ].join(', ');

            const revealObserver = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    const el = entry.target;
                    el.classList.add('rv-in');
                    revealObserver.unobserve(el);
                    // After the staggered transition finishes, strip the helper
                    // classes so the element's original hover transitions return
                    const delay = parseFloat(el.style.transitionDelay) || 0;
                    setTimeout(function () {
                        el.classList.remove('rv', 'rv-in');
                        el.style.transitionDelay = '';
                        el.style.willChange = '';
                    }, (delay + 0.75) * 1000);
                });
            }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

            revealPages.forEach(function (page) {
                page.querySelectorAll('section:not(.hero):not(.about-hero)').forEach(function (section) {
                    const targets = section.querySelectorAll(REVEAL_SELECTOR);
                    targets.forEach(function (el, index) {
                        el.classList.add('rv');
                        // Stagger: each element follows the previous one (capped at 0.72s)
                        let delay = Math.min(index * 0.12, 0.72);
                        // Journey rows: sabay ang number at text ng isang step
                        // (parehong delay), para magkasabay silang lumapag
                        if (el.classList.contains('journey-num-wrap') || el.classList.contains('journey-copy')) {
                            const item = el.closest('.journey-item');
                            const itemIdx = item
                                ? Array.prototype.indexOf.call(item.parentNode.children, item)
                                : index;
                            delay = Math.min(itemIdx * 0.18, 0.72);
                        }
                        el.style.transitionDelay = delay.toFixed(2) + 's';
                        revealObserver.observe(el);
                    });
                });
            });
        }
        // "Scroll Down" cue sa about hero: smooth-scroll papunta sa story section,
        // at nagfa-fade out kapag nag-scroll pababa (babalik lang sa top)
        const scrollCue = document.querySelector('.scroll-down');
        if (scrollCue) {
            scrollCue.addEventListener('click', function (e) {
                e.preventDefault();
                const target = document.querySelector(scrollCue.getAttribute('href'));
                if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });

            const HIDE_AT = 80; // px na scroll bago mag-fade out ang cue
            const syncCue = function () {
                if (window.scrollY > HIDE_AT) {
                    scrollCue.classList.add('is-hidden');
                } else {
                    scrollCue.classList.remove('is-hidden');
                }
            };
            window.addEventListener('scroll', syncCue, { passive: true });
            syncCue();
        }
    });

    // Expose globally
    window.toggleTheme = toggleTheme;
})();
