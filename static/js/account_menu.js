(() => {
    'use strict';
    const button = document.querySelector('.profile-avatar-btn');
    const menu = document.getElementById(button?.getAttribute('aria-controls') || 'clientAccountMenu');
    if (!button || !menu) return;
    const root = button.closest('.profile-dropdown');
    const links = () => [...menu.querySelectorAll('a[href]')].filter(link => link.getClientRects().length);
    const usesPopover = typeof menu.showPopover === 'function';
    if (usesPopover) {
        menu.setAttribute('popover','manual');
        menu.classList.add('account-menu-popover');
    }
    function place() {
        if (!usesPopover) return;
        const box = button.getBoundingClientRect();
        menu.style.setProperty('--account-top',`${box.bottom + 12}px`);
        menu.style.setProperty('--account-right',`${Math.max(12,window.innerWidth-box.right)}px`);
    }

    function close(restoreFocus=false) {
        if (usesPopover && menu.matches(':popover-open')) menu.hidePopover();
        menu.classList.remove('show');
        menu.hidden = true;
        button.setAttribute('aria-expanded','false');
        if (restoreFocus) button.focus();
    }
    function open() {
        window.CustomerNotifications?.close();
        menu.hidden = false;
        place();
        menu.classList.add('show');
        if (usesPopover && !menu.matches(':popover-open')) menu.showPopover();
        button.setAttribute('aria-expanded','true');
    }
    window.closeClientAccountMenu = close;
    button.addEventListener('click',event => {
        event.stopPropagation();
        if (menu.hidden) open(); else close();
    });
    button.addEventListener('keydown',event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            open();
            links()[event.key === 'ArrowDown' ? 0 : links().length-1]?.focus();
        }
    });
    root.addEventListener('keydown',event => {
        if (menu.hidden) return;
        if (event.key === 'Escape') { event.preventDefault(); close(true); }
        if (event.target === button) return;
        if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
            event.preventDefault();
            const items = links();
            const index = items.indexOf(document.activeElement);
            items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
        }
    });
    root.addEventListener('focusout',event => {
        if (event.relatedTarget && !root.contains(event.relatedTarget)) close();
    });
    menu.addEventListener('click',event => {
        const link = event.target.closest('a[href]');
        if (!link) return;
        // Selecting the exact page already open should not reload it.
        const samePage = link.href === window.location.href;
        if (samePage && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault();
            if (document.getElementById('accountContent')) window.AccountNavigation?.navigate(link.href);
            close(true);
        } else close();
    });
    document.addEventListener('click',event => { if (!root.contains(event.target)) close(); });
    window.matchMedia('(max-width:968px)').addEventListener('change',() => {
        if (!menu.hidden) close(true);
    });
    window.addEventListener('resize',() => {
        if (menu.hidden) return;
        place();
        const active = document.activeElement;
        if (menu.contains(active) && active.matches('a') && !active.getClientRects().length) links()[0]?.focus();
    });
})();
