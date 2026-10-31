/* Compact action labels, outside scroll containers and scoped to account mounts. */
['customer_profile', 'my_payments'].forEach(page => AccountPages.register(page, 'action-tooltips', scope => {
    'use strict';
    const tooltip = document.createElement('div');
    tooltip.id = 'account-action-tooltip';
    tooltip.className = 'account-action-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.hidden = true;
    const popover = typeof tooltip.showPopover === 'function';
    if (popover) tooltip.setAttribute('popover', 'manual');
    document.body.append(tooltip);
    let active;

    function hide() {
        if (active) {
            const ids = (active.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== tooltip.id);
            if (ids.length) active.setAttribute('aria-describedby', ids.join(' '));
            else active.removeAttribute('aria-describedby');
        }
        active = null;
        if (popover && tooltip.matches(':popover-open')) tooltip.hidePopover();
        tooltip.hidden = true;
    }
    function position() {
        if (!active) return;
        const anchor = active.getBoundingClientRect(), box = tooltip.getBoundingClientRect();
        if (anchor.bottom <= 0 || anchor.top >= innerHeight || anchor.right <= 0 || anchor.left >= innerWidth) {
            hide(); return;
        }
        const center = anchor.left + anchor.width / 2;
        const left = Math.max(8, Math.min(center - box.width / 2, innerWidth - box.width - 8));
        const above = anchor.top >= box.height + 16;
        tooltip.dataset.placement = above ? 'top' : 'bottom';
        tooltip.style.left = left + 'px';
        tooltip.style.top = (above ? anchor.top - box.height - 9 : anchor.bottom + 9) + 'px';
        tooltip.style.setProperty('--account-tip-arrow-x', Math.max(10, Math.min(center - left, box.width - 10)) + 'px');
        tooltip.style.visibility = '';
    }
    function show(target) {
        if (!target || target === active || target.disabled || !target.dataset.tooltip) return;
        hide();
        active = target;
        tooltip.textContent = target.dataset.tooltip;
        const ids = (target.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        target.setAttribute('aria-describedby', [...ids, tooltip.id].join(' '));
        tooltip.hidden = false;
        tooltip.style.visibility = 'hidden';
        if (popover) tooltip.showPopover();
        position();
    }
    const control = event => event.target.closest('.account-table [data-tooltip]');
    AccountPages.listen(scope.root, 'pointerover', event => { if (event.pointerType !== 'touch') show(control(event)); });
    AccountPages.listen(scope.root, 'pointermove', event => { if (event.pointerType !== 'touch') show(control(event)); });
    AccountPages.listen(scope.root, 'pointerout', event => {
        if (active && !active.contains(event.relatedTarget) && document.activeElement !== active) hide();
    });
    AccountPages.listen(scope.root, 'focusin', event => show(control(event)));
    AccountPages.listen(scope.root, 'focusout', () => hide());
    AccountPages.listen(scope.root, 'click', () => hide());
    AccountPages.listen(scope.root, 'keydown', event => {
        if (event.key === 'Escape' && active) { hide(); event.stopPropagation(); }
    });
    AccountPages.listen(scope.root, 'account:list-updated', hide);
    AccountPages.listen(window, 'scroll', () => {
        if (active?.matches(':hover') || active === document.activeElement) position();
        else hide();
    }, true);
    AccountPages.listen(window, 'resize', hide);
    scope.cleanup(() => { hide(); tooltip.remove(); });
}, 20));
