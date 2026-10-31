AccountPages.enhance('my_reviews', 'review_controls.js', function(scope) {
    'use strict';
    scope.capture(['ReviewUI', 'openReviewImage', 'toggleReviewDropdown']);
    const overlaySelector = '.review-dialog, .review-image-dialog';
    const returnFocus = new WeakMap();
    let previousOverflow = '';

    function closeMenus() {
        document.querySelectorAll('.review-dropdown.show').forEach(menu => menu.classList.remove('show'));
        document.querySelectorAll('.review-options .options-btn').forEach(button => button.setAttribute('aria-expanded', 'false'));
    }
    function open(id) {
        const modal = document.getElementById(id);
        if (!modal || modal.classList.contains('show')) return;
        const active = document.activeElement;
        returnFocus.set(modal, active?.closest('.review-options')?.querySelector('.options-btn') || active);
        closeMenus();
        if (!document.querySelector(`${overlaySelector.split(',').map(s => s.trim() + '.show').join(',')}`)) previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        document.body.classList.add('review-modal-open');
        modal.style.removeProperty('display');
        modal.classList.add('show');
        modal.querySelector('.review-dialog__fields')?.scrollTo(0, 0);
        const focus = modal.querySelector('input[name="rating"]:checked') || modal.querySelector('input[name="rating"]') || modal.querySelector('button');
        focus?.focus({preventScroll:true});
    }
    function close(id) {
        const modal = document.getElementById(id);
        if (!modal?.classList.contains('show')) return;
        modal.classList.remove('show');
        modal.style.removeProperty('display');
        if (!document.querySelector('.review-dialog.show, .review-image-dialog.show')) {
            document.body.style.overflow = previousOverflow;
            document.body.classList.remove('review-modal-open');
        }
        returnFocus.get(modal)?.focus({preventScroll:true});
        if (id === 'imageModal') document.getElementById('expandedImg').removeAttribute('src');
    }
    window.ReviewUI = {open, close, closeMenus};
    window.openReviewImage = image => {
        const expanded = document.getElementById('expandedImg');
        expanded.src = image.currentSrc || image.src;
        expanded.alt = image.alt || "Customer's event setup";
        open('imageModal');
    };
    window.toggleReviewDropdown = (event, id) => {
        event.stopPropagation();
        const menu = document.getElementById(`dropdown-${id}`);
        const wasOpen = menu.classList.contains('show');
        closeMenus();
        if (!wasOpen) {
            menu.classList.add('show');
            event.currentTarget.setAttribute('aria-expanded', 'true');
            menu.querySelector('button')?.focus();
        }
    };
    AccountPages.listen(document, 'click', event => {
        const photo = event.target.closest('.review-uploaded-img');
        if (photo) window.openReviewImage(photo);
        if (!event.target.closest('.review-options')) closeMenus();
        const overlay = event.target.closest(overlaySelector);
        if (overlay === event.target && overlay.classList.contains('show')) {
            if (overlay.id === 'reviewModal') window.closeReviewModal();
            else if (overlay.id === 'editReviewModal') window.closeEditModal();
            else window.closeImageModal();
        }
    });
    AccountPages.listen(document, 'keydown', event => {
        const menu = event.target.closest('.review-dropdown.show');
        if (menu && ['ArrowDown','ArrowUp','Home','End','Escape','Tab'].includes(event.key)) {
            const items = [...menu.querySelectorAll('button')];
            if (event.key === 'Escape' || event.key === 'Tab') {
                const trigger = menu.parentElement.querySelector('.options-btn');
                closeMenus();
                if (event.key === 'Escape') { event.preventDefault(); trigger.focus(); }
            } else {
                event.preventDefault();
                const index = items.indexOf(document.activeElement);
                items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
            }
            return;
        }
        const modal = document.querySelector('.review-image-dialog.show, .review-dialog.show');
        if (!modal) return;
        if (event.key === 'Escape') {
            event.preventDefault(); event.stopPropagation();
            if (modal.id === 'reviewModal') window.closeReviewModal();
            else if (modal.id === 'editReviewModal') window.closeEditModal();
            else window.closeImageModal();
        } else if (event.key === 'Tab') {
            const nodes = [...modal.querySelectorAll('button:not(:disabled), textarea, input:not([type="hidden"]):not([type="file"])')]
                .filter(node => node.getClientRects().length && (node.type !== 'radio' || node.checked || !node.closest('.star-rating').querySelector('input:checked')));
            const first = nodes[0], last = nodes[nodes.length-1];
            if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
        }
    });
    // Delegate keyboard activation so images still work after an edited card is replaced.
    function prepareImages() {
        document.querySelectorAll('.review-uploaded-img').forEach(image => {
            image.tabIndex = 0; image.setAttribute('role','button'); image.setAttribute('aria-label','View review photo');
        });
    }
    prepareImages();
    const imageObserver = new MutationObserver(prepareImages);
    imageObserver.observe(document.querySelector('[data-review-page]'), {childList:true, subtree:true});
    scope.cleanup(() => { imageObserver.disconnect(); document.body.classList.remove('review-modal-open'); });
    AccountPages.listen(document, 'keydown', event => {
        if (event.target.matches('.review-uploaded-img') && ['Enter',' '].includes(event.key)) { event.preventDefault(); window.openReviewImage(event.target); }
    });
    document.querySelectorAll('.review-dialog form').forEach(form => {
        form.addEventListener('reset', () => {
            form.querySelectorAll('[aria-invalid]').forEach(control => control.removeAttribute('aria-invalid'));
        });
        form.addEventListener('submit', () => {
            queueMicrotask(() => {
                const invalid = form.querySelector('.has-error');
                invalid?.querySelector('textarea, input[name="rating"]')?.focus();
            });
        });
    });
    document.querySelectorAll('[data-review-upload]').forEach(zone => {
        const input = document.getElementById(zone.dataset.reviewUpload);
        const error = zone.parentElement.querySelector('.review-upload-type-error');
        const sizeError = zone.parentElement.querySelector('.review-upload-size-error');
        const isImage = file => file.type.startsWith('image/') || (!file.type && /\.(png|jpe?g|webp|gif|avif|heic|heif|bmp|svg)$/i.test(file.name));
        let dragDepth = 0;
        function clearDrag() { dragDepth = 0; zone.classList.remove('is-dragging'); }
        // Capture before the existing accumulation handler so both file selection
        // and dropping use the same image validation and four-photo limit.
        input.addEventListener('change', () => {
            const files = [...input.files];
            const images = files.filter(file => isImage(file) && file.size <= 5 * 1024 * 1024);
            error.hidden = files.every(isImage);
            sizeError.hidden = files.every(file => file.size <= 5 * 1024 * 1024);
            if (images.length !== files.length) {
                const transfer = new DataTransfer();
                images.forEach(file => transfer.items.add(file));
                input.files = transfer.files;
            }
        }, true);
        zone.addEventListener('dragenter', event => {
            event.preventDefault();
            dragDepth++;
            zone.classList.add('is-dragging');
        });
        zone.addEventListener('dragover', event => {
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        });
        zone.addEventListener('dragleave', event => {
            event.preventDefault();
            if (--dragDepth <= 0) clearDrag();
        });
        zone.addEventListener('drop', event => {
            event.preventDefault();
            clearDrag();
            if (!event.dataTransfer?.files.length) return;
            input.files = event.dataTransfer.files;
            input.dispatchEvent(new Event('change', {bubbles:true}));
        });
        input.form.addEventListener('reset', () => { clearDrag(); error.hidden = true; sizeError.hidden = true; });
    });

}, -30);
