/* Keep the account shell and navbar in place; replace only the selected page. */
(() => {
    'use strict';
    const routes = new Set([...document.querySelectorAll('[data-account-key],[data-account-menu-key]')].map(link => new URL(link.href).pathname));
    const scripts = new Map([...document.scripts].filter(script => script.src).map(script => [script.src,Promise.resolve()]));
    let pending, serial = 0, navigating = false;
    const root = () => document.getElementById('accountContent');
    const allowed = url => url.origin === location.origin && routes.has(url.pathname);
    function status(message, retry) {
        const notice = document.querySelector('.account-navigation-status');
        if (!notice) return;
        notice.replaceChildren(document.createTextNode(message));
        notice.hidden = !message;
        if (retry) {
            const button = document.createElement('button');
            button.type = 'button'; button.textContent = 'Try again';
            button.addEventListener('click', retry, {once:true}); notice.append(button);
        }
    }
    function syncSidebar() {
        const key = root()?.dataset.accountPage;
        if (!key) return;
        document.querySelectorAll('[data-account-key],[data-account-menu-key]').forEach(link => {
            if ((link.dataset.accountKey || link.dataset.accountMenuKey) === key) link.setAttribute('aria-current','page');
            else link.removeAttribute('aria-current');
        });
        const accountLink = document.querySelector('#clientAccountMenu [data-account-overview]');
        if (key === 'my_profile') accountLink?.setAttribute('aria-current','page');
        else accountLink?.removeAttribute('aria-current');
    }
    function loadScript(source) {
        if (source.src && scripts.has(source.src)) return scripts.get(source.src);
        const task = new Promise((resolve,reject) => {
            const script = document.createElement('script');
            if (source.src) {
                script.src = source.src; script.async = false;
                script.onload = resolve;
                script.onerror = () => { scripts.delete(source.src); script.remove(); reject(new Error('Unable to load page controls.')); };
            } else script.textContent = source.textContent;
            document.body.append(script);
            if (!source.src) { script.remove(); resolve(); }
        });
        if (source.src) scripts.set(source.src,task);
        return task;
    }
    function interruptible(task,signal) {
        if (signal.aborted) return Promise.reject(new DOMException('Navigation cancelled','AbortError'));
        return new Promise((resolve,reject) => {
            const abort = () => reject(new DOMException('Navigation cancelled','AbortError'));
            signal.addEventListener('abort',abort,{once:true});
            task.then(resolve,reject).finally(() => signal.removeEventListener('abort',abort));
        });
    }
    async function prepareStyles(doc, signal) {
        const sources = [...doc.querySelectorAll('#accountContent link[rel="stylesheet"], head link[data-account-style]')];
        const added = [];
        const tasks = sources.map(source => new Promise((resolve,reject) => {
            const link = source.cloneNode(true);
            link.dataset.accountStyle = '';
            link.media = 'not all';
            const done = () => { signal.removeEventListener('abort',abort); resolve(); };
            const abort = () => { link.remove(); reject(new DOMException('Navigation cancelled','AbortError')); };
            link.onload = done;
            link.onerror = () => {
                signal.removeEventListener('abort',abort);
                if (new URL(link.href).origin !== location.origin) { link.remove(); resolve(); }
                else reject(new Error('Unable to load page styles.'));
            };
            signal.addEventListener('abort',abort,{once:true});
            added.push(link); document.head.append(link);
        }));
        try { await Promise.all(tasks); return added; }
        catch (error) { added.forEach(link => link.remove()); throw error; }
    }
    async function navigate(target, {pop = false, replace = false, force = false, scroll} = {}) {
        const url = new URL(target,location.href);
        if (!root() || !allowed(url)) { location.assign(url.href); return; }
        if (!force && url.href === location.href) {
            pending?.abort(); pending = null; serial++; navigating = false;
            root().removeAttribute('aria-busy'); status('');
            window.closeClientAccountMenu?.(); return;
        }
        pending?.abort();
        const controller = new AbortController(); pending = controller;
        const id = ++serial;
        const oldRoot = root();
        const oldStyles = [...document.querySelectorAll('#accountContent link[rel="stylesheet"], head link[data-account-style]')];
        let nextStyles = [], committed = false;
        navigating = true;
        oldRoot.setAttribute('aria-busy','true');
        window.closeClientAccountMenu?.();
        window.CustomerNotifications?.close();
        const delay = setTimeout(() => status('Opening your account page…'),180);
        const timeout = setTimeout(() => controller.abort(),20000);
        try {
            const response = await fetch(url.href,{signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{'Accept':'text/html','X-Account-Navigation':'1'}});
            if (!response.ok) throw new Error('Unable to open this page.');
            const finalUrl = new URL(response.url);
            if (!allowed(finalUrl)) { location.assign(finalUrl.href); return; }
            const doc = new DOMParser().parseFromString(await response.text(),'text/html');
            const next = doc.getElementById('accountContent');
            if (!next) throw new Error('Account content is unavailable.');
            nextStyles = await prepareStyles(doc,controller.signal);
            // Download controls before touching the currently working page.
            const sources = [...next.querySelectorAll('script')].filter(script => !script.type || script.type === 'text/javascript');
            for (const source of sources.filter(script => script.src)) {
                try { await interruptible(loadScript(source),controller.signal); }
                catch (error) { if (new URL(source.src).origin === location.origin) throw error; }
            }
            if (controller.signal.aborted || id !== serial) throw new DOMException('Navigation cancelled','AbortError');
            if (!pop) {
                history.replaceState({...history.state,accountScroll:[scrollX,scrollY]},'',location.href);
                history[replace ? 'replaceState' : 'pushState']({account:true},'',finalUrl.href);
            }
            AccountPages.unmount();
            document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
            document.body.style.removeProperty('overflow');
            next.querySelectorAll('link[rel="stylesheet"]').forEach(link => link.remove());
            oldRoot.replaceWith(next); committed = true;
            nextStyles.forEach(link => link.media = 'all');
            oldStyles.forEach(link => link.remove());
            document.title = doc.title;
            for (const selector of ['[data-account-name]','[data-account-email]']) {
                const value = doc.querySelector(selector)?.textContent;
                if (value) document.querySelectorAll(selector).forEach(element=>element.textContent=value);
            }
            const initial=doc.querySelector('.nav-avatar')?.textContent;
            if (initial) document.querySelectorAll('.nav-avatar,.account-sidebar-avatar').forEach(element=>element.textContent=initial);
            for (const source of sources.filter(script => !script.src)) await loadScript(source);
            AccountPages.mount(); syncSidebar();
            if (!next.contains(document.activeElement)) next.focus({preventScroll:true});
            window.scrollTo({left:scroll?.[0] || 0, top:scroll?.[1] || 0, behavior:'instant'});
            status('');
        } catch (error) {
            if (error.name !== 'AbortError') console.warn('Account navigation failed:',error);
            if (!committed) nextStyles.forEach(link => link.remove());
            if (id === serial) status(committed ? 'We couldn’t finish opening this page. Please try again.' : 'We couldn’t open this page. Your current page is still here.',() => navigate(url.href,{pop,force:true,scroll}));
        } finally {
            clearTimeout(delay); clearTimeout(timeout);
            if (id === serial) { navigating = false; pending = null; root()?.removeAttribute('aria-busy'); }
        }
    }
    document.addEventListener('click',event => {
        const link = event.target.closest('a[href]');
        if (!root() || !link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
        const url = new URL(link.href,location.href);
        if (!allowed(url) || (!link.hasAttribute('data-account-link') && !link.closest('#clientAccountMenu') && !link.closest('#accountContent'))) return;
        event.preventDefault(); navigate(url.href);
    });
    window.addEventListener('popstate',event => {
        if (root() && allowed(new URL(location.href))) navigate(location.href,{pop:true,force:true,scroll:event.state?.accountScroll});
    });
    document.addEventListener('account:mounted',() => { syncSidebar(); });
    window.AccountNavigation = {navigate, get navigating() { return navigating; }};
    syncSidebar();
})();
