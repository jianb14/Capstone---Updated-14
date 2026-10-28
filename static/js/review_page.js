AccountPages.enhance('my_reviews', 'review_page.js', function(scope) {
    'use strict';
    scope.capture(['ReviewPage']);
    const page = document.querySelector('[data-review-page]');
    if (!page) return;
    const isPublic = page.dataset.reviewPage === 'reviews';
    const region = () => page.querySelector('[data-review-page-content]');
    const cards = () => [...region().querySelectorAll('.review-card')];
    let shownCount = 6;
    let refreshId = 0;
    let refreshing;
    const notify = (icon, title) => AppToast.fire({icon, title});
    const csrf = () => document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
    const select = id => document.getElementById(id);

    function closeFilters() {
        page.querySelectorAll('[data-review-filter]').forEach(dropdown => {
            dropdown.classList.remove('open');
            dropdown.querySelector('.dropdown-trigger').setAttribute('aria-expanded', 'false');
        });
    }
    function syncDropdown(dropdown) {
        const control = dropdown.querySelector('select');
        dropdown.querySelector('.dropdown-trigger span').textContent = control.selectedOptions[0].textContent;
        const list = dropdown.querySelector('.dropdown-options');
        list.replaceChildren(...[...control.options].map(option => {
            const item = document.createElement('li');
            item.textContent = option.textContent;
            item.dataset.value = option.value;
            item.tabIndex = -1;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', String(option.selected));
            item.classList.toggle('selected', option.selected);
            return item;
        }));
    }
    function initFilters() {
        if (!isPublic) return;
        const packages = select('package-filter');
        const previous = packages.value;
        const values = [...new Set(cards().map(card => card.dataset.package))].sort((a,b) => a.localeCompare(b, undefined, {numeric:true}));
        // Keep an active package filter when its last matching review is deleted.
        if (previous !== 'all' && !values.includes(previous)) values.push(previous);
        packages.replaceChildren(new Option('Package (All)', 'all'), ...values.map(value => new Option(value, value)));
        packages.value = previous;
        page.querySelectorAll('[data-review-filter]').forEach(syncDropdown);
        applyFilters();
    }
    function applyFilters() {
        if (!isPublic) return;
        const rating = select('star-filter').value;
        const pkg = select('package-filter').value;
        const sort = select('sort-filter').value;
        const all = cards();
        all.sort((a,b) => {
            const key = sort === 'highest' ? 'rating' : sort === 'most-liked' ? 'likes' : 'date';
            return Number(b.dataset[key]) - Number(a.dataset[key]) || Number(b.dataset.date) - Number(a.dataset.date);
        });
        const list = region().querySelector('.reviews-list');
        const matching = all.filter(card => (rating === 'all' || card.dataset.rating === rating) && (pkg === 'all' || card.dataset.package === pkg));
        all.forEach(card => {
            const index = matching.indexOf(card);
            card.classList.remove('load-hidden');
            card.hidden = index < 0 || index >= shownCount;
            card.style.display = card.hidden ? 'none' : 'flex';
            list.insertBefore(card, list.querySelector('#review-filter-empty'));
        });
        region().querySelector('#review-filter-empty').hidden = !all.length || matching.length > 0;
        const more = region().querySelector('#loadMoreBtn');
        more.hidden = matching.length <= shownCount;
        more.style.display = more.hidden ? 'none' : 'inline-flex';
    }
    function refreshError(url) {
        let notice = page.querySelector('.review-refresh-error');
        if (!notice) {
            notice = document.createElement('div');
            notice.className = 'review-refresh-error';
            notice.setAttribute('role', 'alert');
            const text = document.createElement('span');
            text.textContent = 'We couldn’t update the review list. Try again to see the latest reviews.';
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.textContent = 'Try again';
            retry.addEventListener('click', () => refresh(url));
            notice.append(text, retry);
            page.prepend(notice);
        }
    }
    async function refresh(url = window.location.href, push = false) {
        const id = ++refreshId;
        refreshing?.abort();
        refreshing = new AbortController();
        region().setAttribute('aria-busy', 'true');
        try {
            const response = await fetch(url, {headers:{'X-Requested-With':'XMLHttpRequest'}, signal:refreshing.signal, cache:'no-store'});
            if (!response.ok) throw new Error('Could not refresh reviews.');
            const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
            const content = doc.querySelector('[data-review-page-content]');
            if (!page.isConnected || !content || id !== refreshId) throw new Error('Review list unavailable.');
            region().replaceWith(content);
            page.querySelector('.review-refresh-error')?.remove();
            initFilters();
            if (push) history.pushState({reviewPage:true}, '', url);
            page.dispatchEvent(new CustomEvent('reviews:updated'));
            return true;
        } catch (error) {
            if (error.name !== 'AbortError' && id === refreshId) refreshError(url);
            return false;
        } finally {
            if (id === refreshId) region().removeAttribute('aria-busy');
        }
    }
    function formError(form, message) {
        let error = form.querySelector('.review-form-server-error');
        if (!error) {
            error = document.createElement('p');
            error.className = 'review-form-server-error';
            error.setAttribute('role','alert');
            error.tabIndex = -1;
            form.querySelector('.review-dialog__fields').prepend(error);
        }
        error.textContent = message;
        error.hidden = !message;
        if (message) error.focus();
    }
    async function save(form, reviewId) {
        if (form.dataset.saving) return;
        const button = form.querySelector('[type="submit"]');
        const original = button.textContent;
        form.dataset.saving = 'true';
        button.disabled = true;
        button.textContent = 'Saving…';
        formError(form, '');
        let saved = false;
        try {
            const response = await fetch(reviewId ? `/reviews/${reviewId}/edit/` : form.action, {
                method:'POST', headers:{'X-CSRFToken':csrf(), 'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}, body:new FormData(form)
            });
            const data = await response.json().catch(() => ({}));
            if (!scope.active) return;
            if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Could not save your review. Please try again.');
            saved = true;
            if (reviewId) window.closeEditModal(); else window.closeReviewModal();
            // New reviews should appear on the first published page.
            const url = new URL(window.location.href);
            if (!reviewId) url.searchParams.delete('page_published');
            await refresh(url.href, url.href !== window.location.href);
            notify('success', data.message || 'Review saved.');
        } catch (error) {
            if (!saved) formError(form, error.message || 'Could not save your review. Please try again.');
        } finally {
            delete form.dataset.saving;
            button.disabled = false;
            button.textContent = original;
        }
    }
    const deleting = new Set();
    async function deleteReview(id) {
        if (deleting.has(id)) return;
        deleting.add(id);
        try {
            const result = await AppToast.confirm({title:'Delete this review?', text:'This will also remove its photos.',
                confirmText:'Delete review', confirmButtonColor:'#dc2626', danger:true});
            if (!result.isConfirmed) return;
            if (!scope.active) return;
            const response = await fetch(`/reviews/${id}/delete/`, {method:'POST',headers:{'X-CSRFToken':csrf(), 'X-Requested-With':'XMLHttpRequest'}});
            const data = await response.json().catch(() => ({}));
            if (!scope.active) return;
            if (!response.ok) throw new Error(data.message || 'Could not delete your review. Please try again.');
            await refresh();
            notify('success', data.message || 'Review deleted.');
        } catch (error) { notify('error', error.message || 'Could not delete your review. Please try again.'); }
        finally { deleting.delete(id); }
    }
    window.ReviewPage = {save, deleteReview, refresh};
    document.querySelectorAll('.review-dialog form').forEach(form => form.addEventListener('reset', () => formError(form, '')));
    page.addEventListener('click', async event => {
        const pagination = event.target.closest('.pagination a');
        if (pagination && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault();
            const url = new URL(pagination.href);
            if (url.origin === window.location.origin) await refresh(url.href, true);
            return;
        }
        const dropdown = event.target.closest('[data-review-filter]');
        if (dropdown) {
            const trigger = event.target.closest('.dropdown-trigger');
            if (trigger) {
                const wasOpen = dropdown.classList.contains('open');
                closeFilters();
                if (!wasOpen) {
                    dropdown.classList.add('open');
                    trigger.setAttribute('aria-expanded','true');
                    dropdown.querySelector('[aria-selected="true"]')?.focus();
                }
            }
            const option = event.target.closest('[role="option"]');
            if (option) {
                const control = dropdown.querySelector('select');
                control.value = option.dataset.value;
                syncDropdown(dropdown);
                closeFilters();
                dropdown.querySelector('.dropdown-trigger').focus();
                shownCount = 6;
                applyFilters();
            }
            return;
        }
        if (event.target.closest('[data-clear-review-filters]')) {
            select('star-filter').value = 'all';
            select('package-filter').value = 'all';
            page.querySelectorAll('[data-review-filter]').forEach(syncDropdown);
            shownCount = 6;
            applyFilters();
            select('star-filter').closest('[data-review-filter]').querySelector('button').focus();
        }
        if (event.target.closest('#loadMoreBtn')) { shownCount += 6; applyFilters(); }
        const like = event.target.closest('.like-btn');
        if (like && !like.disabled) {
            like.disabled = true;
            try {
                const response = await fetch(`/reviews/${like.dataset.id}/like/`, {method:'POST',headers:{'X-CSRFToken':csrf(), 'X-Requested-With':'XMLHttpRequest'}});
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Could not update your like.');
                like.classList.toggle('liked', data.liked);
                like.querySelector('svg').setAttribute('fill', data.liked ? 'currentColor' : 'none');
                like.querySelector('.like-count').textContent = data.total_likes;
                like.closest('.review-card').dataset.likes = data.total_likes;
                applyFilters();
            } catch (error) { notify('error', error.message || 'Could not update your like.'); }
            finally { like.disabled = false; }
        }
    });
    AccountPages.listen(document, 'click', event => { if (!event.target.closest('[data-review-filter]')) closeFilters(); });
    page.addEventListener('keydown', event => {
        const dropdown = event.target.closest('[data-review-filter]');
        if (!dropdown) return;
        const trigger = dropdown.querySelector('.dropdown-trigger');
        const items = [...dropdown.querySelectorAll('[role="option"]')];
        const open = dropdown.classList.contains('open');
        if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
            event.preventDefault();
            if (!open) { closeFilters(); dropdown.classList.add('open'); trigger.setAttribute('aria-expanded','true'); }
            const index = items.indexOf(document.activeElement);
            items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
        } else if (['Enter',' '].includes(event.key) && event.target.matches('[role="option"]')) { event.preventDefault(); event.target.click(); }
        else if (event.key === 'Escape' || event.key === 'Tab') { closeFilters(); if (event.key === 'Escape') {event.preventDefault(); trigger.focus();} }
    });
    if (!document.querySelector('[data-account-page]')) AccountPages.listen(window, 'popstate', () => refresh());
    initFilters();

    scope.cleanup(() => { refreshId++; refreshing?.abort(); });

}, -20);
