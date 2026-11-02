/* Reveal each part of the library in order, including refreshed search results. */
(() => {
    'use strict';
    const root = document.querySelector('.design-library-workspace');
    if (!root || !window.IntersectionObserver || !Element.prototype.animate) return;

    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const seen = new WeakSet(), running = new Map();
    const selector = [
        '.designs-header-copy > *', '.designs-header > .create-new-btn',
        '.design-limit-note', '.design-storage-count', '.designs-search-wrapper',
        '.designs-sort', '.design-card', '.design-library-empty',
        '.account-table-footer', '.design-stat-card'
    ].join(',');

    function finish(element) {
        running.get(element)?.cancel();
        running.delete(element);
    }
    const observer = new IntersectionObserver(entries => {
        const groups = new Map();
        entries.filter(entry => entry.isIntersecting && entry.target.getClientRects().length)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top ||
                a.boundingClientRect.left - b.boundingClientRect.left)
            .forEach(entry => {
                const element = entry.target;
                observer.unobserve(element);
                if (reduced.matches || !element.isConnected) return;
                const group = element.closest('.designs-header,.designs-filter-group,.designs-grid,.designs-stats-bar') || root;
                const index = groups.get(group) || 0;
                groups.set(group, index + 1);
                const animation = element.animate([
                    {opacity: 0, transform: `translateY(${innerWidth <= 600 ? 12 : 20}px)`},
                    {opacity: 1, transform: 'none'}
                ], {
                    id: 'design-entry', duration: 620,
                    delay: Math.min(index * 85, 595) + (group.matches('.designs-grid') ? 160 : 0),
                    easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards'
                });
                running.set(element, animation);
                // Release transforms so card menus retain their usual positioning.
                animation.onfinish = () => finish(element);
            });
    }, {threshold: .08, rootMargin: '0px 0px -24px 0px'});

    function register() {
        running.forEach((_, element) => { if (!element.isConnected) finish(element); });
        if (reduced.matches) return;
        root.querySelectorAll(selector).forEach(element => {
            if (seen.has(element)) return;
            seen.add(element);
            observer.observe(element);
        });
    }
    register();
    new MutationObserver(register).observe(root, {childList: true, subtree: true});

    function settle(event) {
        let element = event.target;
        while (element && element !== root) {
            // Interacting with an entering card should immediately reveal it.
            if (element.matches(selector)) observer.unobserve(element);
            finish(element);
            element = element.parentElement;
        }
    }
    root.addEventListener('pointerdown', settle, true);
    root.addEventListener('focusin', settle, true);
    reduced.addEventListener('change', () => {
        if (!reduced.matches) { register(); return; }
        observer.disconnect();
        running.forEach((_, element) => finish(element));
    });
})();
