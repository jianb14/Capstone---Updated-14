AccountPages.enhance('my_reviews', 'review_motion.js', function(scope) {
    'use strict';
    const page = document.querySelector('[data-review-page]');
    if (!page || !window.IntersectionObserver || !Element.prototype.animate) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const seen = new WeakSet();
    const running = new Map();
    const selector = [
        '.mr-header-text', '.mr-community-link', '.mr-stat',
        '.pending-reviews-heading', '.published-heading',
        '.reviews-title-wrap', '[data-review-filter]',
        '.pending-review-card', '.review-card', '.review-empty-state',
        '.pagination-container', '#loadMoreBtn'
    ].join(',');

    function finish(element) {
        const animation = running.get(element);
        if (animation) { animation.cancel(); running.delete(element); }
    }
    const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting && entry.target.getClientRects().length && !entry.target.hidden);
        visible.sort((a,b) => a.boundingClientRect.top - b.boundingClientRect.top || a.boundingClientRect.left - b.boundingClientRect.left);
        visible.forEach((entry,index) => {
            const element = entry.target;
            observer.unobserve(element);
            if (reduced.matches || !element.isConnected) return;
            const animation = element.animate([
                {opacity:0, transform:`translateY(${window.innerWidth <= 600 ? 8 : 12}px)`},
                {opacity:1, transform:'none'}
            ], {
                id:'review-entry', duration:480, delay:Math.min(index * 45,225),
                easing:'cubic-bezier(0.22, 1, 0.36, 1)', fill:'backwards'
            });
            running.set(element,animation);
            // Remove the effect entirely so cards and menus keep their normal stacking.
            animation.onfinish = () => finish(element);
        });
    }, {threshold:.01, rootMargin:'0px 0px 32px 0px'});

    function register() {
        running.forEach((animation,element) => { if (!element.isConnected) finish(element); });
        page.querySelectorAll(selector).forEach(element => {
            if (seen.has(element)) return;
            seen.add(element);
            if (!reduced.matches) observer.observe(element);
        });
    }
    register();
    // Async saves, pagination, empty states and Load More use the same entrance.
    const mutation = new MutationObserver(register);
    mutation.observe(page,{childList:true,subtree:true});
    scope.cleanup(() => mutation.disconnect());
    page.addEventListener('reviews:updated',register);
    // Interaction takes priority over movement, including keyboard focus.
    function settleTarget(event) {
        let element = event.target;
        while (element && element !== page) { finish(element); element = element.parentElement; }
    }
    page.addEventListener('pointerdown',settleTarget,true);
    page.addEventListener('focusin',settleTarget,true);
    AccountPages.listen(reduced, 'change',() => {
        if (!reduced.matches) return;
        observer.disconnect();
        running.forEach((animation,element) => finish(element));
    });

    scope.cleanup(() => { observer.disconnect(); running.forEach((animation) => animation.cancel()); });

}, 20);
