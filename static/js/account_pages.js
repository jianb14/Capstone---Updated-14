/* Account page lifecycle. Public pages continue to use normal navigation. */
(() => {
    'use strict';
    const factories = new Map();
    let current;
    function register(page, key, factory, priority = 0) {
        if (!factories.has(page)) factories.set(page, new Map());
        factories.get(page).set(key, {factory, priority});
    }
    function listen(target, type, handler, options) {
        target.addEventListener(type, handler, options);
        const scope = current;
        scope?.cleanup(() => target.removeEventListener(type, handler, options));
    }
    function cleanup(callback) { current?.cleanup(callback); }
    function unmount() {
        if (!current) return;
        current.active = false;
        current.controller.abort();
        current.disposers.reverse().forEach(dispose => { try { dispose(); } catch (error) { console.error(error); } });
        current = null;
    }
    function mount() {
        const root = document.querySelector('[data-account-page]');
        if (!root) return;
        const scope = {
            root, active:true, disposers:[], queue:[], controller:new AbortController(),
            cleanup(callback) { this.disposers.push(callback); },
            ready(callback) { this.queue.push(callback); },
            expose(values) {
                const previous = new Map(Object.keys(values).map(key => [key, Object.getOwnPropertyDescriptor(window,key)]));
                Object.assign(window, values);
                this.cleanup(() => previous.forEach((descriptor,key) => {
                    if (descriptor) Object.defineProperty(window,key,descriptor); else delete window[key];
                }));
            },
            capture(names) {
                const previous = new Map(names.map(key => [key,Object.getOwnPropertyDescriptor(window,key)]));
                this.cleanup(() => previous.forEach((descriptor,key) => {
                    if (descriptor) Object.defineProperty(window,key,descriptor); else delete window[key];
                }));
            }
        };
        current = scope;
        [...(factories.get(root.dataset.accountPage)?.values() || [])]
            .sort((a,b) => a.priority-b.priority).forEach(({factory}) => factory(scope));
        scope.queue.forEach(callback => callback());
        document.dispatchEvent(new CustomEvent('account:mounted', {detail:{page:root.dataset.accountPage}}));
    }
    function enhance(page, key, factory, priority = 0) {
        if (document.querySelector('[data-account-page]')) register(page,key,factory,priority);
        else factory({active:true, cleanup() {}, capture() {}, expose(values) { Object.assign(window,values); },
            ready(callback) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',callback,{once:true}); else callback(); }});
    }
    window.AccountPages = {register, enhance, listen, cleanup, mount, unmount, get current() { return current; }};
    document.addEventListener('DOMContentLoaded', mount, {once:true});
})();
