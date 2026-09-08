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

        // Scroll reveal: staggered per-element fade/slide within each home section
        // (header text first, then cards/items one by one)
        const homePage = document.getElementById('home');
        if (homePage && 'IntersectionObserver' in window) {
            const REVEAL_SELECTOR = [
                '.section-header > *',
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

            homePage.querySelectorAll('section:not(.hero)').forEach(function (section) {
                const targets = section.querySelectorAll(REVEAL_SELECTOR);
                targets.forEach(function (el, index) {
                    el.classList.add('rv');
                    // Stagger: each element follows the previous one (capped at 0.72s)
                    el.style.transitionDelay = (Math.min(index * 0.12, 0.72)).toFixed(2) + 's';
                    revealObserver.observe(el);
                });
            });
        }
    });

    // Expose globally
    window.toggleTheme = toggleTheme;
})();
