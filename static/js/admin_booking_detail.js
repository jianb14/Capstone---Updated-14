/* Single-file delivery upload; the existing authenticated POST remains authoritative. */
(() => {
    'use strict';
    const form = document.querySelector('.design-upload-form');
    if (!form) return;
    const input = form.querySelector('[name=design_image]');
    const zone = form.querySelector('[data-design-dropzone]');
    const status = form.querySelector('.design-file-status');
    const selected = form.querySelector('.design-selected-file');
    const browse = zone.querySelector('button');
    function message(text) { status.textContent = text; status.hidden = !text; }
    function showSelection() {
        const file = input.files[0];
        selected.hidden = !file;
        selected.querySelector('span').textContent = file ? file.name : '';
        if (file) message('');
    }
    function validate(file) {
        if (!file) return 'Please choose a design image.';
        if (!['image/jpeg','image/png','image/webp'].includes(file.type)) return 'Choose a JPG, PNG or WEBP image.';
        if (file.size > 5 * 1024 * 1024) return 'The design image must be 5MB or smaller.';
        return '';
    }
    input.addEventListener('change', () => {
        const error = validate(input.files[0]);
        if (error) input.value = '';
        showSelection(); message(error);
    });
    input.addEventListener('invalid', event => {
        event.preventDefault(); message('Please choose a design image.'); browse.focus();
    });
    zone.addEventListener('click', () => input.click());
    ['dragenter','dragover'].forEach(type => zone.addEventListener(type, event => {
        event.preventDefault(); zone.classList.add('is-dragging');
    }));
    zone.addEventListener('dragleave', event => {
        if (!zone.contains(event.relatedTarget)) zone.classList.remove('is-dragging');
    });
    zone.addEventListener('drop', event => {
        event.preventDefault(); zone.classList.remove('is-dragging');
        const files = event.dataTransfer.files;
        if (files.length !== 1) { message('Choose one design image at a time.'); return; }
        const error = validate(files[0]);
        if (error) { message(error); return; }
        const transfer = new DataTransfer(); transfer.items.add(files[0]); input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles:true }));
    });
    selected.querySelector('button').addEventListener('click', () => {
        input.value = ''; showSelection(); message(''); browse.focus();
    });
    form.addEventListener('reset', () => queueMicrotask(() => { showSelection(); message(''); }));
    form.classList.add('is-enhanced'); zone.hidden = false; showSelection();
})();
