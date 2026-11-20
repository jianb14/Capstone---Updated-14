/* Local invitation only: opening the assistant uses the existing button. */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const fab = document.getElementById('ai-fab');
        const invite = fab?.querySelector('.ai-fab-invite');
        if (!invite) return;
        const text = invite.querySelector('.ai-fab-invite-text');
        const label = Array.from(invite.querySelector('[data-label]').dataset.label);
        const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
        let timer = null;
        let nextStep = null;
        let remaining = 0;
        let deadline = 0;
        let index = 0;
        let cycles = 0;
        let hovered = false;

        function interacting() {
            return hovered || fab.matches(':focus-within');
        }

        function schedule(step, delay) {
            nextStep = step;
            remaining = delay;
            if (interacting()) return;
            deadline = performance.now() + delay;
            timer = window.setTimeout(() => { timer = null; step(); }, delay);
        }

        function syncInteraction() {
            if (interacting()) {
                if (timer !== null) {
                    remaining = Math.max(0, deadline - performance.now());
                    window.clearTimeout(timer);
                    timer = null;
                }
            } else if (nextStep && timer === null) {
                schedule(nextStep, remaining);
            }
        }

        function type() {
            invite.classList.add('is-visible');
            index += 1;
            text.textContent = label.slice(label.length - index).join('');
            invite.dataset.phase = index < label.length ? 'typing' : 'holding';
            schedule(index < label.length ? type : erase, index < label.length ? 85 : 2000);
        }

        function erase() {
            invite.dataset.phase = 'erasing';
            index -= 1;
            text.textContent = label.slice(label.length - index).join('');
            if (index > 0) {
                schedule(erase, 30);
            } else {
                invite.classList.remove('is-visible');
                cycles = (cycles + 1) % 3;
                schedule(type, cycles === 0 ? 60000 : 8000);
            }
        }

        function sync(delay = 8000) {
            window.clearTimeout(timer);
            timer = null;
            nextStep = null;
            index = 0;
            cycles = 0;
            text.textContent = '';
            invite.classList.remove('is-visible');
            if (document.hidden || document.documentElement.hasAttribute('data-welcome-active') ||
                fab.getAttribute('aria-expanded') === 'true') return;
            if (motion.matches) {
                invite.dataset.phase = 'static';
                text.textContent = label.join('');
                invite.classList.add('is-visible');
                return;
            }
            schedule(type, delay);
        }

        fab.addEventListener('pointerenter', event => {
            if (event.pointerType !== 'mouse' && event.pointerType !== 'pen') return;
            hovered = true;
            syncInteraction();
        });
        fab.addEventListener('pointerleave', () => { hovered = false; syncInteraction(); });
        fab.addEventListener('focusin', syncInteraction);
        fab.addEventListener('focusout', syncInteraction);
        new MutationObserver(() => sync()).observe(fab, { attributes: true, attributeFilter: ['aria-expanded'] });
        new MutationObserver(() => sync(1000)).observe(document.documentElement, {
            attributes: true, attributeFilter: ['data-welcome-active'],
        });
        document.addEventListener('visibilitychange', () => sync());
        motion.addEventListener('change', () => sync());
        sync(1000);
    });
})();
