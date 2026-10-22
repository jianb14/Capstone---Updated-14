document.querySelectorAll('.design-offer-picker').forEach(picker => {
    if (picker.dataset.bound) return;
    picker.dataset.bound = 'true';
    const tabs = Array.from(picker.querySelectorAll('[data-design-tab]'));
    const select = tab => {
        tabs.forEach(button => { const active = button === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
        picker.querySelectorAll('[data-design-panel]').forEach(panel => { panel.hidden = panel.dataset.designPanel !== tab.dataset.designTab; });
    };
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => select(tab));
        tab.addEventListener('keydown', event => {
            let next;
            if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
            if (event.key === 'ArrowLeft') next = tabs[(index + tabs.length - 1) % tabs.length];
            if (event.key === 'Home') next = tabs[0];
            if (event.key === 'End') next = tabs[tabs.length - 1];
            if (next) { event.preventDefault(); select(next); next.focus(); }
        });
    });
    if (tabs[0]) select(tabs[0]);

    const dialog = picker.querySelector('.dl-offer-dialog');
    if (!dialog) return;
    const body = dialog.querySelector('[data-offer-modal-body]');
    let opener;
    picker.addEventListener('click', event => {
        const button = event.target.closest('[data-offer-open]');
        if (!button) return;
        const template = [...picker.querySelectorAll('template[data-offer-content]')].find(item => item.dataset.offerContent === button.dataset.offerOpen);
        if (!template) return;
        opener = button;
        dialog.querySelector('#designOfferDetailsTitle').textContent = button.closest('.pkg-card').querySelector('.pkg-card-title').textContent;
        body.replaceChildren(template.content.cloneNode(true));
        dialog.showModal();
        dialog.scrollTop = 0;
        document.documentElement.classList.add('design-modal-open');
    });
    dialog.addEventListener('click', event => {
        if (event.target.closest('[data-offer-close]')) dialog.close();
        if (event.target === dialog) {
            const box = dialog.getBoundingClientRect();
            if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
        }
    });
    dialog.addEventListener('close', () => {
        if (!document.querySelector('.modal-overlay.show, .dl-offer-dialog[open]')) document.documentElement.classList.remove('design-modal-open');
        opener?.focus({preventScroll: true});
    });
});
