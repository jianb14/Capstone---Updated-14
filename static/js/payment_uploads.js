/* Delegated handlers also cover the dynamically loaded Payment Settings form. */
(() => {
    'use strict';
    if (window.PaymentUploads) return;
    const previews = new Map();
    function release(input) {
        const url = previews.get(input);
        if (url) URL.revokeObjectURL(url);
        previews.delete(input);
    }
    function selected(input) {
        const root = input.closest('[data-payment-upload]');
        const preview = root.querySelector('[data-upload-preview]');
        const feedback = root.querySelector('[data-upload-feedback]');
        const reset = root.querySelector('[data-upload-reset]');
        release(input);
        preview.hidden = true;
        reset.hidden = true;
        preview.querySelector('img').removeAttribute('src');
        input.removeAttribute('aria-invalid');
        input.setCustomValidity('');
        feedback.textContent = '';
        const file = input.files[0];
        if (!file) return;
        if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 5 * 1024 * 1024) {
            input.value = '';
            input.setAttribute('aria-invalid', 'true');
            feedback.textContent = 'Choose a PNG or JPEG image no larger than 5 MB.';
            input.setCustomValidity(feedback.textContent);
            reset.hidden = false;
            return;
        }
        const url = URL.createObjectURL(file);
        previews.set(input, url);
        const image = preview.querySelector('img');
        image.onerror = () => {
            if (previews.get(input) !== url) return;
            input.value = '';
            selected(input);
            input.setAttribute('aria-invalid', 'true');
            feedback.textContent = 'This image could not be opened. Choose a valid PNG or JPEG.';
            input.setCustomValidity(feedback.textContent);
            reset.hidden = false;
        };
        image.src = url;
        preview.querySelector('[data-upload-filename]').textContent = file.name;
        preview.querySelector('[data-upload-size]').textContent = file.size >= 1024 * 1024
            ? `${(file.size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
        preview.hidden = false;
    }
    function cleanup() {
        for (const input of previews.keys()) if (!input.isConnected) release(input);
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-upload-browse],[data-upload-remove]');
        const root = button?.closest('[data-payment-upload]');
        if (!root) return;
        const input = root.querySelector('input[type=file]');
        if (button.hasAttribute('data-upload-browse')) input.click();
        else {
            input.value = '';
            selected(input);
            root.querySelector('[data-upload-browse]').focus({preventScroll:true});
        }
        cleanup();
    });
    document.addEventListener('change', event => {
        if (event.target.matches('[data-payment-upload] input[type=file]')) selected(event.target);
        cleanup();
    });
    for (const type of ['dragover', 'dragleave', 'drop']) document.addEventListener(type, event => {
        const zone = event.target.closest('[data-payment-upload] [data-upload-zone]');
        if (!zone) return;
        event.preventDefault();
        if (type === 'dragleave' && zone.contains(event.relatedTarget)) return;
        zone.classList.toggle('is-dragging', type === 'dragover');
        if (type !== 'drop' || !event.dataTransfer?.files.length) return;
        const input = zone.querySelector('input[type=file]');
        if (event.dataTransfer.files.length > 1) {
            zone.closest('[data-payment-upload]').querySelector('[data-upload-feedback]').textContent = 'Choose one image at a time.';
            return;
        }
        input.files = event.dataTransfer.files;
        input.dispatchEvent(new Event('change', {bubbles:true}));
    });
    document.addEventListener('invalid', event => {
        const field = event.target.closest('.pu-proof-field');
        if (field) {
            event.preventDefault();
            event.target.setAttribute('aria-invalid', 'true');
            let error = field.querySelector('.pu-field-error');
            if (!error) {
                error = document.createElement('p');
                error.className = 'pu-field-error';
                error.id = event.target.id + '_errors';
                error.setAttribute('role', 'alert');
                field.append(error);
            }
            event.target.setAttribute('aria-describedby', error.id);
            error.textContent = event.target.validity.valueMissing
                ? field.querySelector('label').textContent.replace('*', '').trim() + ' is required.'
                : event.target.validationMessage;
            if (!field.closest('form').querySelector('.pu-proof-field input[aria-invalid="true"]:focus')) event.target.focus();
        }
        const root = event.target.closest('[data-payment-upload]');
        if (!root) return;
        event.preventDefault();
        event.target.setAttribute('aria-invalid', 'true');
        root.querySelector('[data-upload-feedback]').textContent = event.target.validity.customError
            ? event.target.validationMessage : 'Choose at least one image.';
        root.querySelector('[data-upload-browse]').focus();
    }, true);
    document.addEventListener('input', event => {
        const field = event.target.closest('.pu-proof-field');
        if (!field || !event.target.hasAttribute('aria-invalid') || !event.target.validity.valid) return;
        event.target.removeAttribute('aria-invalid');
        field.querySelector('.pu-field-error')?.remove();
        event.target.removeAttribute('aria-describedby');
    });
    window.addEventListener('pagehide', () => { for (const input of previews.keys()) release(input); });
    window.PaymentUploads = {cleanup};
})();
