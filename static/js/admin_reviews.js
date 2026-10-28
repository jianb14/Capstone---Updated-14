/* Filters, pagination, replies and testimonials stay in the current document. */
(() => {
    'use strict';
    const root = document.querySelector('.rv-workspace');
    if (!root) return;
    const form = root.querySelector('#reviewFilters'), search = form.elements.search;
    const results = root.querySelector('#reviewResults'), summary = root.querySelector('#reviewSummary');
    const notice = root.querySelector('#reviewListFeedback'), clear = form.querySelector('.ac-search-clear');
    const modal = root.querySelector('#reviewDetailModal'), content = root.querySelector('#reviewDetailContent');
    const detailNotice = root.querySelector('#reviewDetailFeedback'), imageModal = root.querySelector('#reviewImageModal');
    const selects = window.AdminSelects.create(root);
    let pageSize = results.querySelector('[data-list-size]')?.value || (new URL(location.href).searchParams.get('per_page') === '4' ? '4' : '8');
    let listController, detailController, listVersion = 0, detailVersion = 0, timer, saving = false, origin;
    let currentID = null, appliedURL = new URL(location.href), removeReviewURL = true;
    const keys = ['search', 'rating', 'featured', 'sort'];

    function feedback(node, message = '', success = false, retry) {
        node.dataset.kind = success ? 'success' : 'error';
        node.replaceChildren(document.createTextNode(message));
        if (retry) {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'ac-button'; button.textContent = 'Try again';
            button.addEventListener('click', retry, {once:true}); node.append(' ', button);
        }
    }
    async function request(url, options = {}) {
        const timeout = new AbortController(), abort = () => timeout.abort();
        options.signal?.addEventListener('abort', abort, {once:true});
        const clock = setTimeout(abort, 15000);
        try {
            if (options.signal?.aborted) abort();
            const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options, signal:timeout.signal,
                headers:{Accept:'application/json', 'X-Requested-With':'XMLHttpRequest', ...options.headers}});
            if (response.redirected) throw new Error('Your session ended. Please sign in again.');
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.message || 'This request could not be completed. Please try again.');
            if (!data.html) throw new Error('The server returned an incomplete response. Please try again.');
            return data;
        } finally {
            clearTimeout(clock); options.signal?.removeEventListener('abort', abort);
        }
    }
    function updateSummary(html) {
        if (html && summary.innerHTML !== html) summary.innerHTML = html;
    }
    function filtersURL(keepPage = false) {
        const url = new URL(root.dataset.reviewsUrl, location.origin);
        for (const key of keys) if (form.elements[key].value) url.searchParams.set(key, form.elements[key].value.trim());
        url.searchParams.set('per_page', pageSize);
        const unchanged = keys.every(key => {
            const fallback = key === 'sort' ? '-created_at' : '';
            return (url.searchParams.get(key) || fallback) === (appliedURL.searchParams.get(key) || fallback);
        });
        url.searchParams.set('page', keepPage && unchanged ? appliedURL.searchParams.get('page') || '1' : '1');
        return url;
    }
    function setHistory(url, push) {
        const clean = new URL(url, location.href);
        clean.pathname = root.dataset.reviewsUrl;
        if (modal.open && currentID) clean.searchParams.set('review_id', currentID);
        else clean.searchParams.delete('review_id');
        if (push && clean.href !== location.href) history.pushState({}, '', clean);
        else history.replaceState({}, '', clean);
        appliedURL = clean;
    }
    async function load(url, push = true) {
        clearTimeout(timer); listController?.abort(); selects.close();
        const controller = listController = new AbortController(), version = ++listVersion;
        results.setAttribute('aria-busy', 'true'); feedback(notice);
        try {
            const data = await request(url, {signal:controller.signal});
            if (version !== listVersion) return;
            if (results.contains(document.activeElement)) search.focus({preventScroll:true});
            selects.release(results);
            results.innerHTML = data.html; updateSummary(data.summary_html); selects.enhance();
            if (saving) busy(true);
            results.classList.remove('rv-results-enter'); void results.offsetWidth; results.classList.add('rv-results-enter');
            const actual = new URL(url); actual.searchParams.set('page', data.page);
            setHistory(actual, push);
            return true;
        } catch (error) {
            if (version === listVersion && !controller.signal.aborted) {
                feedback(notice, error.name === 'AbortError' ? 'The request took too long. Your current reviews are still here.' : error.message,
                    false, () => load(url, push));
            }
            return false;
        } finally { if (version === listVersion) results.removeAttribute('aria-busy'); }
    }
    function restoreFilters(url) {
        for (const key of keys) {
            const control = form.elements[key], requested = url.searchParams.get(key) || (key === 'sort' ? '-created_at' : '');
            control.value = key === 'search' ? requested.slice(0, 150) : [...control.options].some(option => option.value === requested) ? requested : key === 'sort' ? '-created_at' : '';
        }
        pageSize = url.searchParams.get('per_page') === '4' ? '4' : '8';
        clear.hidden = !search.value; selects.sync();
    }
    search.addEventListener('input', () => {
        clear.hidden = !search.value; clearTimeout(timer);
        // Invalidate immediately; a slower old search must not replace the newer draft.
        listController?.abort(); ++listVersion; results.removeAttribute('aria-busy');
        timer = setTimeout(() => load(filtersURL()), 280);
    });
    clear.addEventListener('click', () => {search.value = ''; clear.hidden = true; search.focus(); load(filtersURL());});
    form.addEventListener('submit', event => {event.preventDefault(); load(filtersURL());});
    form.addEventListener('change', event => {if (event.target.matches('select')) load(filtersURL());});
    root.addEventListener('change', event => {
        if (event.target.matches('[data-list-size]')) {pageSize = event.target.value; load(filtersURL());}
    });
    root.addEventListener('input', event => {
        if (event.target.matches('[name="reply_text"]')) {
            event.target.form.querySelector('[data-reply-length]').textContent = `${event.target.value.length}/2000`;
            if (event.target.hasAttribute('aria-invalid')) validateReply(event.target.form);
        }
    });

    function validateReply(replyForm) {
        const textarea = replyForm.elements.reply_text, error = replyForm.querySelector('[data-reply-error]');
        const message = !textarea.value.trim() ? 'Reply text is required.' :
            textarea.value.trim().length > 2000 ? 'Reply is too long (max 2000 characters).' : '';
        error.textContent = message;
        error.hidden = !message;
        if (message) textarea.setAttribute('aria-invalid', 'true');
        else textarea.removeAttribute('aria-invalid');
        return !message;
    }
    function enhanceReply() {
        // Keep the required attribute for accessibility and the no-JavaScript fallback.
        const replyForm = content.querySelector('[data-review-reply]');
        if (replyForm) replyForm.noValidate = true;
    }

    function detailsURL(id) { return root.dataset.detailsPattern.replace('/0/', `/${id}/`); }
    function displayDetail(data, keepDraft = false) {
        const draft = keepDraft ? content.querySelector('[name="reply_text"]')?.value : null;
        const oldScroll = root.querySelector('#reviewModalBody').scrollTop;
        content.innerHTML = data.html;
        enhanceReply();
        if (saving) busy(true);
        if (draft !== null) {
            const textarea = content.querySelector('[name="reply_text"]');
            if (textarea) {textarea.value = draft; textarea.dispatchEvent(new Event('input', {bubbles:true}));}
        }
        content.hidden = false;
        root.querySelector('#reviewModalNumber').textContent = `Review #REV-${data.id}`;
        root.querySelector('#reviewModalTitle').textContent = 'Review details';
        feedback(detailNotice);
        root.querySelector('#reviewModalBody').scrollTop = oldScroll;
    }
    async function openDetails(id, button, push = true, initial = false) {
        if (saving) return;
        origin = button || document.activeElement; currentID = String(id);
        detailController?.abort(); const controller = detailController = new AbortController(), version = ++detailVersion;
        root.querySelector('#reviewModalNumber').textContent = `Review #REV-${id}`;
        root.querySelector('#reviewModalTitle').textContent = 'Review details';
        feedback(detailNotice, initial ? '' : 'Loading the latest review...'); content.hidden = !initial;
        if (!modal.open) {modal.showModal(); document.body.classList.add('ac-modal-open');}
        root.querySelector('#reviewModalBody').scrollTop = 0;
        if (push) {const url = new URL(location.href); url.searchParams.set('review_id', id); history.pushState({}, '', url);}
        if (initial) return;
        try {
            const data = await request(detailsURL(id), {signal:controller.signal});
            if (version === detailVersion && modal.open) displayDetail(data);
        } catch (error) {
            if (version === detailVersion && !controller.signal.aborted && modal.open) {
                feedback(detailNotice, error.name === 'AbortError' ? 'The review took too long to load. Please try again.' : error.message,
                    false, () => openDetails(id, origin, false));
            }
        }
    }
    function closeDetails(clean = true) {
        if (saving) return;
        removeReviewURL = clean; selects.close(); detailController?.abort(); modal.close();
    }
    modal.addEventListener('close', () => {
        if (modal.open) return; // A history change may already have opened the next review.
        detailController?.abort(); ++detailVersion; document.body.classList.remove('ac-modal-open'); currentID = null;
        if (removeReviewURL) {const url = new URL(location.href); url.searchParams.delete('review_id'); history.replaceState({}, '', url);}
        removeReviewURL = true;
        if (origin?.isConnected) origin.focus({preventScroll:true}); else search.focus({preventScroll:true});
    });
    modal.addEventListener('cancel', event => {if (saving) event.preventDefault();});
    modal.addEventListener('click', event => {if (event.target === modal) closeDetails();});
    root.querySelectorAll('[data-close-review]').forEach(button => button.addEventListener('click', () => closeDetails()));
    imageModal.querySelector('button').addEventListener('click', () => imageModal.close());
    imageModal.addEventListener('click', event => {if (event.target === imageModal) imageModal.close();});
    imageModal.addEventListener('close', () => {imageModal.querySelector('img').removeAttribute('src');});

    function busy(value) {
        saving = value;
        root.querySelectorAll('[data-review-feature] button, [data-review-reply] button, [data-close-review], [data-confirm-remove], [data-keep-reply]').forEach(button => button.disabled = value);
        const textarea = content.querySelector('textarea'); if (textarea) textarea.readOnly = value;
        modal.setAttribute('aria-busy', String(value));
    }
    async function mutate(actionForm, action, keepDraft = false) {
        if (saving) return;
        const inModal = modal.contains(actionForm), id = actionForm.dataset.reviewFeature || actionForm.dataset.reviewReply;
        const targetNotice = inModal ? content.querySelector('.rv-action-feedback') : notice;
        const body = new FormData(actionForm);
        listController?.abort(); ++listVersion; results.removeAttribute('aria-busy');
        busy(true); feedback(targetNotice, 'Saving...');
        try {
            const data = await request(action || actionForm.action, {method:'POST', body});
            window.AdminConfigurationFeedback?.show(data.message);
            if (modal.open && currentID === String(id)) {
                displayDetail(data, keepDraft);
                feedback(content.querySelector('.rv-action-feedback'), data.message, true);
            }
            updateSummary(data.summary_html);
            const refreshed = await load(filtersURL(true), false);
            if (!inModal && refreshed) feedback(notice, data.message, true);
        } catch (error) {
            const message = error.name === 'AbortError' ? 'The response took too long. Check the latest review before trying again.' : error.message;
            feedback(targetNotice, message);
            window.AdminConfigurationFeedback?.show(message, 'error');
            if (inModal) targetNotice.focus();
        } finally {busy(false);}
    }
    root.addEventListener('submit', event => {
        const feature = event.target.closest('[data-review-feature]'), reply = event.target.closest('[data-review-reply]');
        if (!feature && !reply) return;
        event.preventDefault(); if (saving) return;
        if (feature) {mutate(feature, null, true); return;}
        if (event.submitter?.matches('[data-remove-reply]')) {
            const confirm = content.querySelector('[data-remove-confirm]'); confirm.hidden = false;
            confirm.querySelector('[data-keep-reply]').focus(); return;
        }
        if (validateReply(reply)) mutate(reply);
        else {
            feedback(content.querySelector('.rv-action-feedback'));
            reply.elements.reply_text.focus();
        }
    });
    root.addEventListener('click', event => {
        const anchor = event.target.closest('[data-list-page]');
        if (anchor && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault(); const url = filtersURL(true);
            url.searchParams.set('page', new URL(anchor.href).searchParams.get('page') || '1'); load(url); return;
        }
        if (event.target.closest('[data-list-reset]')) {
            for (const key of keys) form.elements[key].value = key === 'sort' ? '-created_at' : '';
            clear.hidden = true; selects.sync(); load(filtersURL()); return;
        }
        const detail = event.target.closest('[data-review-detail]');
        if (detail && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault(); openDetails(detail.dataset.reviewDetail, detail); return;
        }
        const photo = event.target.closest('[data-review-image]');
        if (photo) {imageModal.querySelector('img').src = photo.dataset.reviewImage; imageModal.showModal(); return;}
        if (event.target.closest('[data-keep-reply]')) {
            content.querySelector('[data-remove-confirm]').hidden = true;
            content.querySelector('[data-remove-reply]').focus(); return;
        }
        if (event.target.closest('[data-confirm-remove]')) {
            const replyForm = content.querySelector('[data-review-reply]');
            mutate(replyForm, replyForm.querySelector('[data-remove-reply]').formAction);
        }
    });
    window.addEventListener('popstate', () => {
        const url = new URL(location.href);
        if (modal.open && !saving) closeDetails(false);
        restoreFilters(url); load(url, false);
        const id = url.searchParams.get('review_id');
        if (id && /^[1-9]\d{0,18}$/.test(id)) openDetails(id, null, false);
    });
    selects.enhance();
    enhanceReply();
    const initialID = root.dataset.initialReview || new URL(location.href).searchParams.get('review_id');
    if (initialID && /^[1-9]\d{0,18}$/.test(initialID)) {
        const url = new URL(location.href); url.pathname = root.dataset.reviewsUrl; url.searchParams.set('review_id', initialID);
        history.replaceState({}, '', url); appliedURL = url;
        openDetails(initialID, null, false, !!root.dataset.initialReview);
    }
})();
