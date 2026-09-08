/**
 * Theme Toggle - Light/Dark Mode
 * Shared between client and admin sides
 * Saves preference to localStorage
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'balloorina-theme';

    // Apply saved theme IMMEDIATELY (before DOM ready) to prevent flash
    function applyStoredTheme() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    }

    // Run immediately
    applyStoredTheme();

    // Toggle theme
    function toggleTheme() {
        const apply = function () {
            const isCurrentlyLight = document.documentElement.getAttribute('data-theme') === 'light';
            if (isCurrentlyLight) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem(STORAGE_KEY, 'dark');
            } else {
                document.documentElement.setAttribute('data-theme', 'light');
                localStorage.setItem(STORAGE_KEY, 'light');
            }
        };

        // Smooth crossfade via View Transitions API (modern browsers)
        if (document.startViewTransition) {
            document.startViewTransition(apply);
        } else {
            // Fallback: briefly enable a global color transition
            document.documentElement.classList.add('theme-animating');
            apply();
            setTimeout(function () {
                document.documentElement.classList.remove('theme-animating');
            }, 400);
        }
        updateToggleButtons();
    }

    // Update all toggle buttons on the page
    function updateToggleButtons() {
        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
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
        });
    }

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        // Attach click handlers to all toggle buttons
        document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                toggleTheme();
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
        // Works on any page wrapper with section children (home #home, about #about, ...)
        const revealPages = ['home', 'about']
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
                '.home-gallery-grid > .gallery-item',
                '.marquee-track .testimonial-card',
                '.faq-list > .faq-item',
                '.cta-banner > *'
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
