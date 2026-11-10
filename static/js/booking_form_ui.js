/* Shared presentation for the create, edit and request-change booking wizards. */
AccountPages.enhance('customer_profile', 'booking_form_ui.js', function(scope) {
    'use strict';
    scope.capture(['BookingFormUI']);
    const paths = {
        info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
        image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>',
        upload:'<path d="M7 18H6a4 4 0 0 1-.6-8A6.5 6.5 0 0 1 18 8a5 5 0 0 1 0 10h-1M12 20V10m-4 4 4-4 4 4"/>',
        calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18M7 15h2m4 0h2m-8 3h2"/>',
        clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
        clipboard:'<path d="M9 5H6a2 2 0 0 0-2 2v13h16V7a2 2 0 0 0-2-2h-3"/><rect x="9" y="3" width="6" height="4" rx="1"/>',
        file:'<path d="M14 3H5v18h14V8zm0 0v5h5M8 12h8m-8 4h8"/>',
        map:'<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3zm6-3v15m6-12v15"/>',
        pin:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
        target:'<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
        palette:'<path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-3.7 1.7 1.7 0 0 1 1-3.1h2a4 4 0 0 0 4-4C21 6 17 3 12 3Z"/><path d="M7.5 10h.01M10 6.5h.01m4 0h.01m3 3h.01"/>',
        wand:'<path d="m4 20 12-12 4 4L8 24M14 10l4 4M5 3v4M3 5h4m12-4v4m-2-2h4M4 13v4m-2-2h4" transform="translate(0 -2)"/>',
        text:'<path d="M4 4h16M12 4v16m-4 0h8"/>',
        pencil:'<path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15Z"/>',
        comment:'<path d="M21 11a9 9 0 0 1-9 9H3l2-5a9 9 0 1 1 16-4Z"/>',
        check:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m7 12 3 3 7-7"/>',
        warning:'<path d="m12 3 10 18H2Zm0 6v5m0 3h.01"/>',
        left:'<path d="m12 5-7 7 7 7M5 12h15"/>',
        right:'<path d="m12 5 7 7-7 7M4 12h15"/>',
        chevron:'<path d="m9 5 7 7-7 7"/>',
        down:'<path d="m6 9 6 6 6-6"/>',
        close:'<path d="m6 6 12 12M18 6 6 18"/>',
        ban:'<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>'
    };
    const icon = name => `<svg class="form-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name] || paths.info}</svg>`;
    const nameFor = el => {
        const c=el.className;
        if(c.includes('pencil') || c.includes('pen'))return 'pencil';
        for (const [part,name] of [['cloud','upload'],['images','image'],['image','image'],['calendar','calendar'],['clock','clock'],['clipboard','clipboard'],['file','file'],['location-crosshairs','target'],['map-pin','pin'],['thumbtack','pin'],['map','map'],['palette','palette'],['wand','wand'],['font','text'],['comment','comment'],['square-check','check'],['triangle','warning'],['arrow-left','left'],['chevron-left','left'],['arrow-right','right'],['chevron-right','right'],['chevron-down','down'],['ban','ban'],['xmark','close']]) {
            if(c.includes(part))return name;
        }
        return 'info';
    };
    function emptyPreview() {
        const box=document.createElement('div');box.className='preview-item-empty';
        box.innerHTML=icon('image')+'<div><strong>Preview not available yet</strong><p>You can still choose this item and continue.</p></div>';
        return box;
    }
    function setupPackageGallery(root, imagesForCard, clearPackage) {
        const modal = root.closest('.modal-overlay');
        const box = root.closest('.booking-modal-box');
        const gallery = document.createElement('section');
        gallery.className = 'package-gallery';
        gallery.hidden = true;
        gallery.id = root.id + '-gallery';
        gallery.setAttribute('aria-label', 'Sample setups');
        gallery.innerHTML = `
            <div class="package-gallery-header">
                <button type="button" class="package-gallery-back">${icon('left')}Back to packages</button>
                <span>Sample setups</span>
            </div>
            <div class="package-gallery-layout">
                <div class="package-gallery-visual">
                    <div class="package-gallery-stage"></div>
                    <div class="package-gallery-controls">
                        <button type="button" data-image-direction="-1" aria-label="Previous image">${icon('left')}</button>
                        <span class="package-gallery-count" aria-live="polite"></span>
                        <button type="button" data-image-direction="1" aria-label="Next image">${icon('right')}</button>
                    </div>
                </div>
                <div class="package-gallery-details">
                    <h3 tabindex="-1"></h3>
                    <div class="package-gallery-price"></div>
                    <p class="package-gallery-label">What's included</p>
                    <ul class="package-gallery-inclusions"></ul>
                    <p class="preview-note">Sample setup. Actual styling may vary with your theme and venue.</p>
                </div>
            </div>
            <div class="modal-actions"><button type="button" class="btn-submit package-gallery-select">Select this package</button></div>`;
        root.after(gallery);
        const heading = gallery.querySelector('h3');
        const stage = gallery.querySelector('.package-gallery-stage');
        const controls = gallery.querySelector('.package-gallery-controls');
        const count = gallery.querySelector('.package-gallery-count');
        const select = gallery.querySelector('.package-gallery-select');
        let active = null, pendingSelection = null, images = [], imageIndex = 0, scrollTop = 0;

        function close(restoreFocus = true) {
            if (gallery.hidden) return;
            gallery.hidden = true;
            root.hidden = false;
            box.scrollTop = scrollTop;
            if (restoreFocus) active?.view.focus({preventScroll: true});
            active = null;
            pendingSelection = null;
        }
        function renderImage() {
            stage.replaceChildren();
            controls.hidden = images.length < 2;
            count.textContent = images.length ? `${imageIndex + 1} of ${images.length}` : '';
            if (!images.length) {
                stage.append(emptyPreview());
                return;
            }
            const image = document.createElement('img');
            image.className = 'package-gallery-image';
            image.alt = `${active.label} sample setup ${imageIndex + 1}`;
            image.addEventListener('error', () => {
                if (image.parentNode === stage) stage.replaceChildren(emptyPreview());
            }, {once: true});
            image.src = images[imageIndex];
            stage.append(image);
        }
        function moveImage(direction) {
            if (images.length < 2) return;
            imageIndex = (imageIndex + direction + images.length) % images.length;
            renderImage();
        }
        function open(entry) {
            active = entry;
            scrollTop = box.scrollTop;
            images = imagesForCard(entry.card).filter(Boolean).slice(0, 2);
            imageIndex = 0;
            heading.textContent = entry.label;
            gallery.querySelector('.package-gallery-price').textContent = entry.card.querySelector('.price').textContent.trim();
            gallery.querySelector('.package-gallery-inclusions').replaceChildren(
                ...Array.from(entry.card.querySelectorAll('.features li'), item => item.cloneNode(true))
            );
            select.textContent = entry.card.dataset.package ? 'Select this package' : 'Select this item';
            select.disabled = entry.card.classList.contains('disabled');
            root.hidden = true;
            gallery.hidden = false;
            renderImage();
            box.scrollTop = 0;
            heading.focus({preventScroll: true});
        }
        gallery.querySelector('.package-gallery-back').addEventListener('click', () => close());
        gallery.querySelectorAll('[data-image-direction]').forEach(button => {
            button.addEventListener('click', () => moveImage(Number(button.dataset.imageDirection)));
        });
        select.addEventListener('click', () => {
            if (!active || select.disabled) return;
            if (active.card.classList.contains('selected')) { close(); return; }
            // The existing edit handler may await a price warning before committing selection.
            pendingSelection = active;
            select.disabled = true;
            active.card.click();
        });
        AccountPages.listen(document, 'keydown', event => {
            if (gallery.hidden || !modal.classList.contains('show') || document.querySelector('.client-feedback-dialog[open]')) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault();
                moveImage(event.key === 'ArrowLeft' ? -1 : 1);
            }
        }, true);
        const entries = [...root.querySelectorAll('.package-card')].map(card => {
            const label = card.dataset.package || card.dataset.name;
            const control = card.querySelector('.package-info');
            control.tabIndex = 0;
            control.setAttribute('role', 'button');
            control.setAttribute('aria-label', 'Select ' + label);
            control.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    card.click();
                }
            });
            const actions = document.createElement('div');
            actions.className = 'package-card-actions';
            const view = document.createElement('button');
            view.type = 'button';
            view.className = 'package-preview-toggle';
            view.innerHTML = icon('image') + '<span>View sample setups</span>' + icon('chevron');
            view.setAttribute('aria-label', 'Sample setups for ' + label);
            view.setAttribute('aria-controls', gallery.id);
            const entry = {card, control, view, label};
            view.addEventListener('click', event => { event.stopPropagation(); open(entry); });
            actions.append(view);
            if (card.dataset.package) {
                entry.remove = document.createElement('button');
                entry.remove.type = 'button';
                entry.remove.className = 'package-remove-control';
                entry.remove.textContent = 'Remove package';
                entry.remove.hidden = true;
                entry.remove.addEventListener('click', event => { event.stopPropagation(); clearPackage(); });
                actions.append(entry.remove);
            }
            card.append(actions);
            return entry;
        });
        return {
            close,
            sync() {
                for (const entry of entries) {
                    const selected = entry.card.classList.contains('selected');
                    entry.control.setAttribute('aria-pressed', String(selected));
                    entry.control.setAttribute('aria-disabled', String(entry.card.classList.contains('disabled')));
                    if (entry.remove) entry.remove.hidden = !selected;
                }
                if (pendingSelection) {
                    if (pendingSelection.card.classList.contains('selected')) close();
                    else {
                        select.disabled = false;
                        select.focus({preventScroll: true});
                    }
                    pendingSelection = null;
                }
            }
        };
    }
    function setupUpload(zone) {
        if(zone.dataset.ready)return;zone.dataset.ready='1';
        const input=document.getElementById(zone.dataset.fileInput),status=zone.querySelector('.reference-upload-status');
        if(!input)return;
        // Capture before the wizard's accumulation handler, for browsing and drops.
        input.addEventListener('change',()=>{
            const files=[...input.files],transfer=new DataTransfer();
            const isImage=file=>file.type.startsWith('image/') || /\.(png|jpe?g|webp|gif|avif|bmp)$/i.test(file.name);
            const tooLarge=files.some(file=>file.size>5*1024*1024);
            zone.dataset.uploadError=tooLarge?'Each photo must be 5MB or smaller.':files.some(file=>!isImage(file))?'Please choose image files.':'';
            for(const file of files)if(isImage(file) && file.size<=5*1024*1024)transfer.items.add(file);
            input.files=transfer.files;
        },true);
        zone.addEventListener('click',()=>input.click());
        for(const type of ['dragenter','dragover'])zone.addEventListener(type,event=>{event.preventDefault();zone.classList.add('is-dragging');});
        zone.addEventListener('dragleave',event=>{if(!zone.contains(event.relatedTarget))zone.classList.remove('is-dragging');});
        zone.addEventListener('drop',event=>{
            event.preventDefault();zone.classList.remove('is-dragging');
            input.files=event.dataTransfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
        });
        const update=()=>{
            if(zone.dataset.uploadError){status.classList.add('is-error');status.textContent=zone.dataset.uploadError;return;}
            const total=input.closest('form')?.querySelector('input[name="reference_images"]')?.files.length || 0;
            status.classList.remove('is-error');status.textContent=total?`${total} new image${total===1?'':'s'} selected`:'';
        };
        input.addEventListener('change',()=>queueMicrotask(update));
        input.closest('form')?.addEventListener('click',()=>queueMicrotask(update));
        input.closest('form')?.addEventListener('reset',()=>{zone.dataset.uploadError='';status.textContent='';status.classList.remove('is-error');});
    }
    function enhance(root) {
        if(!(root instanceof Element))return;
        const icons=root.matches('i[class]')?[root]:root.querySelectorAll('i[class]');
        for(const el of icons) {const holder=document.createElement('span');holder.innerHTML=icon(nameFor(el));el.replaceWith(holder.firstElementChild);}
        for(const button of root.querySelectorAll('.design-chip,.palette-swatch')) {
            button.setAttribute('aria-pressed',String(button.classList.contains('selected')));
            if(button.dataset.color)button.setAttribute('aria-label',button.dataset.color);
        }
        root.querySelectorAll('.reference-dropzone').forEach(setupUpload);
        for(const trigger of root.querySelectorAll('.custom-select-trigger')) {
            if(trigger.dataset.focusReady)continue;
            trigger.dataset.focusReady='1';trigger.tabIndex=0;trigger.setAttribute('role','button');
            trigger.addEventListener('keydown',event=>{
                if(event.key==='Enter' || event.key===' '){event.preventDefault();trigger.click();}
                if(event.key==='Escape')trigger.closest('.custom-select-container')?.classList.remove('open');
            });
        }
    }
    scope.ready(()=>{
        for(const root of document.querySelectorAll('#bookingModalOverlay,#editBookingModal')) {
            enhance(root);
            const observer = new MutationObserver(records=>{
                for(const record of records) {
                    if(record.type==='attributes' && record.target.matches('.design-chip,.palette-swatch'))record.target.setAttribute('aria-pressed',String(record.target.classList.contains('selected')));
                    for(const node of record.addedNodes)enhance(node);
                }
            });
            observer.observe(root,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
            scope.cleanup(() => observer.disconnect());
        }
    });
    window.BookingFormUI={icon,setupPackageGallery};

}, -10);
