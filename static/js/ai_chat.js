/* Image viewing is local UI only; it does not submit or regenerate a design. */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const widget = document.getElementById('ai-widget');
        const dialog = document.getElementById('ai-image-preview');
        if (!widget || !dialog) return;
        const image = dialog.querySelector('[data-ai-preview-image]');
        const error = dialog.querySelector('[data-ai-preview-error]');
        const download = dialog.querySelector('[data-ai-preview-download]');
        let opener = null;

        widget.addEventListener('click', event => {
            const trigger = event.target.closest('.ai-image-preview-trigger');
            if (!trigger) return;
            const source = trigger.querySelector('img[data-ai-generated-image="1"]');
            if (!source || source.dataset.fallbackShown === '1') return;
            let url;
            try { url = new URL(source.currentSrc || source.src, location.origin); }
            catch (_) { return; }
            if (!['http:', 'https:', 'blob:'].includes(url.protocol)) return;
            opener = trigger;
            image.hidden = false;
            error.hidden = true;
            download.hidden = false;
            image.alt = source.alt || 'Balloorina Design Concept';
            image.src = url.href;
            download.href = url.href;
            if (!dialog.open) dialog.showModal();
            document.body.classList.add('ai-preview-open');
        });

        image.addEventListener('error', () => {
            if (!dialog.open) return;
            image.hidden = true;
            error.hidden = false;
            download.hidden = true;
        });
        dialog.querySelector('[data-ai-preview-close]').addEventListener('click', () => dialog.close());
        dialog.addEventListener('click', event => {
            if (event.target !== dialog) return;
            const rect = dialog.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right ||
                event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
        });
        dialog.addEventListener('close', () => {
            document.body.classList.remove('ai-preview-open');
            image.removeAttribute('src');
            download.removeAttribute('href');
            const target = opener?.isConnected ? opener : document.getElementById('ai-widget-input');
            target?.focus({ preventScroll: true });
            opener = null;
        });
    });
})();
