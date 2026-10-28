/* Customer tables share filtering, bounded page sizes and cancellable partial updates. */
['customer_profile','my_payments','report_concern'].forEach(page => AccountPages.register(page,'account-tables',scope => {
    const list = scope.root.querySelector('[data-account-list]');
    if (!list) return;
    const mountedPath = location.pathname;
    let pending, sequence = 0, searchTimer;
    const message = document.createElement('div');
    message.className = 'account-list-notice'; message.hidden = true;
    message.setAttribute('role','status'); message.setAttribute('aria-live','polite');
    list.prepend(message);

    function announce(text, retry) {
        message.replaceChildren(document.createTextNode(text)); message.hidden = !text;
        if (retry) {
            const button = document.createElement('button'); button.type = 'button';
            button.textContent = 'Try again'; button.addEventListener('click',retry,{once:true}); message.append(button);
        }
    }
    function selectControl(select) {
        if (select.dataset.enhanced) return;
        select.dataset.enhanced = 'true';
        const wrap = document.createElement('div'); wrap.className = 'account-select';
        select.before(wrap); wrap.append(select);
        const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'account-select-trigger';
        trigger.setAttribute('aria-haspopup','listbox'); trigger.setAttribute('aria-expanded','false');
        const options = document.createElement('div'); options.className = 'account-select-options';
        options.setAttribute('role','listbox'); options.hidden = true;
        options.id = `account-options-${scope.root.dataset.accountPage}-${sequence}-${list.querySelectorAll('.account-select').length}`;
        trigger.setAttribute('aria-controls',options.id);
        const name = select.getAttribute('aria-label') || 'Select an option';
        options.setAttribute('aria-label',name);
        const text = document.createElement('span');
        trigger.append(text);
        trigger.insertAdjacentHTML('beforeend','<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>');
        const choices = [...select.options].map(option => {
            const button = document.createElement('button'); button.type='button'; button.setAttribute('role','option');
            button.textContent=option.text; button.dataset.value=option.value;
            button.addEventListener('click',() => {
                select.value=option.value; sync(); close(); trigger.focus(); select.dispatchEvent(new Event('change',{bubbles:true}));
            });
            options.append(button); return button;
        });
        function sync() {
            text.textContent=select.selectedOptions[0]?.text || '';
            trigger.setAttribute('aria-label',`${name}: ${text.textContent}`);
            choices.forEach(button => button.setAttribute('aria-selected',String(button.dataset.value===select.value)));
        }
        function close() { options.hidden=true; trigger.setAttribute('aria-expanded','false'); }
        function open(last=false) {
            list.querySelectorAll('.account-select-options').forEach(element => { element.hidden=true; element.previousElementSibling?.setAttribute('aria-expanded','false'); });
            options.hidden=false; trigger.setAttribute('aria-expanded','true');
            (last ? choices.at(-1) : choices.find(button=>button.dataset.value===select.value) || choices[0])?.focus();
        }
        trigger.addEventListener('click',() => options.hidden ? open() : close());
        trigger.addEventListener('keydown',event => {
            if (['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); open(event.key==='ArrowUp'); }
        });
        options.addEventListener('keydown',event => {
            const index=choices.indexOf(document.activeElement);
            if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
                event.preventDefault();
                choices[event.key==='Home' ? 0 : event.key==='End' ? choices.length-1 : (index+(event.key==='ArrowDown'?1:-1)+choices.length)%choices.length]?.focus();
            } else if (event.key==='Escape') { event.preventDefault(); close(); trigger.focus(); }
            else if (event.key==='Tab') close();
        });
        wrap.addEventListener('focusout',event => { if (!wrap.contains(event.relatedTarget)) close(); });
        wrap.append(trigger,options); select.hidden=true; sync();
        select.addEventListener('change',sync);
        select.addEventListener('account:sync',sync);
    }
    function enhance() {
        list.querySelectorAll('select[data-account-select]').forEach(selectControl);
        list.querySelectorAll('[data-list-clear]').forEach(button => { button.hidden=!button.previousElementSibling.value; });
    }
    async function refresh(target, {pop=false}={}) {
        clearTimeout(searchTimer); pending?.abort();
        const controller=new AbortController(); pending=controller;
        const id=++sequence, url=new URL(target,location.href);
        const results=document.getElementById(list.dataset.resultsId);
        results?.setAttribute('aria-busy','true'); announce('');
        const delay=setTimeout(()=> { if (scope.active && id===sequence) announce('Updating your results…'); },200);
        const timeout=setTimeout(()=>controller.abort(),20000);
        try {
            const response=await fetch(url.href,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
                headers:{'X-Requested-With':'XMLHttpRequest','Accept':'text/html'}});
            if (response.redirected && new URL(response.url).pathname!==mountedPath) {
                if (scope.active && id===sequence) location.assign(response.url); return;
            }
            if (!response.ok) throw new Error('Results are unavailable.');
            const doc=new DOMParser().parseFromString(await response.text(),'text/html');
            const fresh=doc.getElementById(list.dataset.resultsId);
            if (!fresh) throw new Error('Results are unavailable.');
            if (!scope.active || id!==sequence) return;
            const focused=document.activeElement, restoreFocus=results.contains(focused);
            const field=focused?.matches('[data-list-search]') ? {name:focused.name,value:focused.value,start:focused.selectionStart,end:focused.selectionEnd} : null;
            const sizeControl=focused?.closest('.account-page-size');
            const tabControl=focused?.closest('[data-list-tab]')?.dataset.tabTarget;
            const pageControl=focused?.closest('[data-list-page]');
            results.replaceChildren(...fresh.childNodes);
            if (pop) list.querySelectorAll('[data-list-filter] input,[data-list-filter] select').forEach(input => {
                const original=doc.querySelector(`[data-list-filter] [name="${input.name}"]`);
                if (original) { input.value=original.value; input.dispatchEvent(new Event('account:sync')); }
            });
            if (!pop) history.pushState({account:true,accountList:true},'',url.href);
            enhance();
            // Sync enhanced labels without submitting another request.
            list.querySelectorAll('select[data-account-select]').forEach(select=>select.dispatchEvent(new Event('account:sync')));
            if (restoreFocus) {
                const visible=results.querySelector('.cp-tab-panel.is-active') || results;
                let target;
                if (field) {
                    target=visible.querySelector(`[data-list-search][name="${CSS.escape(field.name)}"]`);
                    if (target && !pop) target.value=field.value;
                } else if (sizeControl) target=visible.querySelector('.account-page-size .account-select-trigger');
                else if (tabControl) target=results.querySelector(`[data-list-tab][data-tab-target="${CSS.escape(tabControl)}"]`);
                else if (pageControl) target=visible.querySelector('[aria-current="page"]');
                if (target) {
                    if (pageControl) target.tabIndex=-1;
                    target.focus({preventScroll:true});
                    if (field && !pop) target.setSelectionRange(field.start,field.end);
                }
            }
            list.dispatchEvent(new CustomEvent('account:list-updated',{bubbles:true}));
            announce('');
        } catch (error) {
            if (!scope.active || id!==sequence) return;
            console.warn('Account list update failed:',error);
            announce('We couldn’t update the list. Your current results are still here.',()=>refresh(url,{pop}));
        } finally {
            clearTimeout(delay); clearTimeout(timeout);
            if (scope.active && id===sequence) { results?.removeAttribute('aria-busy'); pending=null; }
        }
    }
    function filterURL() {
        const url=new URL(location.href);
        ['page','payments_page','ar_page','partial_page','open_edit','booking_id','payment_id','concern_id','modal','from_notif'].forEach(key=>url.searchParams.delete(key));
        list.querySelectorAll('[data-list-filter]').forEach(form=>{
            if (form.closest('.cp-tab-panel') && !form.closest('.cp-tab-panel').classList.contains('is-active')) return;
            for (const [key,value] of new FormData(form)) value ? url.searchParams.set(key,value) : url.searchParams.delete(key);
        });
        return url;
    }
    list.addEventListener('input',event=>{
        if (!event.target.matches('[data-list-search]')) return;
        const clear=event.target.nextElementSibling; if (clear?.matches('[data-list-clear]')) clear.hidden=!event.target.value;
        clearTimeout(searchTimer); searchTimer=setTimeout(()=>refresh(filterURL()),300);
    });
    list.addEventListener('submit',event=>{ if (event.target.matches('[data-list-filter]')) { event.preventDefault(); refresh(filterURL()); } });
    list.addEventListener('change',event=>{
        if (event.target.matches('[data-list-size]')) {
            const url=filterURL(); url.searchParams.set('per_page',event.target.value); refresh(url);
        } else if (event.target.matches('[data-list-filter] select')) refresh(filterURL());
    });
    list.addEventListener('click',event=>{
        const link=event.target.closest('[data-list-page],[data-list-tab]');
        if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button===0) {
            event.preventDefault(); refresh(link.href); return;
        }
        const clear=event.target.closest('[data-list-clear]');
        if (clear) { const input=clear.previousElementSibling; input.value=''; clear.hidden=true; input.focus(); refresh(filterURL()); }
        if (event.target.closest('[data-list-reset]')) {
            list.querySelectorAll('[data-list-filter] input:not([type="hidden"])').forEach(input=>input.value='');
            list.querySelectorAll('[data-list-filter] select').forEach(select=>select.selectedIndex=0);
            refresh(filterURL());
        }
    });
    AccountPages.listen(document,'click',event=>{
        if (event.target.closest('.account-select')) return;
        list.querySelectorAll('.account-select-options').forEach(options=>{ options.hidden=true; options.previousElementSibling?.setAttribute('aria-expanded','false'); });
    });
    AccountPages.listen(window,'popstate',event=>{
        if (location.pathname!==mountedPath) return;
        event.stopImmediatePropagation(); refresh(location.href,{pop:true});
    },true);
    enhance();
    scope.cleanup(()=>{ sequence++; clearTimeout(searchTimer); pending?.abort(); });
},10));
