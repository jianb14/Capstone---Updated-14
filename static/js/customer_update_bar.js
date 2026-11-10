/* One temporary customer update bar; notification history stays in the bell. */
(() => {
    'use strict';
    window.CustomerUpdateBar = {create({bell, onGroup, onItem, storageKey}) {
        const bar = document.createElement('aside');
        bar.id = 'customer-update-bar'; bar.className = 'customer-update-bar';
        bar.hidden = true; bar.setAttribute('role', 'status');
        bar.setAttribute('aria-live', 'polite'); bar.setAttribute('aria-atomic', 'true');
        bar.setAttribute('popover', 'manual');
        // Only application-owned, fixed markup enters this template.
        bar.innerHTML = `<div class="customer-update-inner">
            <svg class="customer-update-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"></svg>
            <div class="customer-update-text"><strong class="customer-update-title"></strong><span class="customer-update-description"></span></div>
            <button type="button" class="customer-update-action"></button>
            <button type="button" class="customer-update-close" aria-label="Dismiss update"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
        </div>`;
        document.body.append(bar);
        const title=bar.querySelector('.customer-update-title'), description=bar.querySelector('.customer-update-description');
        const action=bar.querySelector('.customer-update-action'), icon=bar.querySelector('.customer-update-icon');
        const navbar=document.querySelector('.navbar');
        let total=0, single=null, timer=null, remaining=8000, started=0;
        function place() {
            bar.style.setProperty('--customer-update-top', `${Math.max(0,navbar?.getBoundingClientRect().bottom || 0)}px`);
        }
        function pause() {
            if (timer !== null) {
                clearTimeout(timer); timer=null;
                remaining=Math.max(0,remaining-(Date.now()-started));
            }
        }
        function hide() {
            pause();
            if (typeof bar.hidePopover==='function' && bar.matches(':popover-open')) bar.hidePopover();
            bar.hidden=true; total=0; single=null;
        }
        function dismiss(restoreFocus=false) {
            if (restoreFocus && bar.contains(document.activeElement)) bell.focus({preventScroll:true});
            hide();
            try {if (storageKey) sessionStorage.removeItem(storageKey);} catch (_) { /* Current page still dismisses. */ }
        }
        function resume() {
            if (bar.hidden || document.hidden || bar.matches(':hover') || bar.contains(document.activeElement)) return;
            pause(); started=Date.now(); timer=setTimeout(()=>dismiss(),remaining);
        }
        function render() {
            // TWO is the grouping threshold, independent of unread badge count.
            const grouped=total>=2;
            bar.dataset.kind=grouped?'grouped':single.kind;
            title.textContent=grouped?`${total} new updates`:single.title;
            description.textContent=grouped?'Booking, payment and design activity':single.description;
            action.textContent=grouped?'View updates':single.action;
            icon.innerHTML=grouped?'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>':
                single.kind==='success'?'<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>':
                '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/>';
            place(); bar.hidden=false;
            if (typeof bar.showPopover==='function' && !bar.matches(':popover-open')) {
                try {bar.showPopover();} catch (_) { /* Fixed-position fallback remains usable. */ }
            }
            resume();
        }
        function show(data) {
            if (!data.update_count) return;
            if (bar.hidden) {total=0;remaining=8000;}
            total+=data.update_count;
            single=total===1?data.updates[0]:null;
            render();
        }
        function restore() {
            if (!storageKey || document.querySelector('dialog[open],.modal-overlay.show')) return;
            let state;
            try {
                const raw=sessionStorage.getItem(storageKey);
                if (!raw) return;
                sessionStorage.removeItem(storageKey);
                state=JSON.parse(raw);
                const age=Date.now()-state.savedAt;
                if (!Number.isSafeInteger(state.total) || state.total<1 || !Number.isFinite(state.remaining)
                        || state.remaining<=0 || state.remaining>8000 || !Number.isFinite(age) || age<0 || age>60000) return;
                if (state.total===1) {
                    const item=state.single;
                    if (!item || !Number.isSafeInteger(item.id) || item.id<1
                            || !['success','warning','error'].includes(item.kind)
                            || !['title','description','action','message','created_at','target_url','read_url'].every(key=>typeof item[key]==='string')
                            || [item.target_url,item.read_url].some(url=>new URL(url,location.origin).origin!==location.origin)) return;
                }
            } catch (_) {return; /* Unavailable or malformed storage must not stop live updates. */ }
            pause(); total=state.total; single=total===1?state.single:null; remaining=state.remaining;
            render();
        }
        window.addEventListener('pagehide',()=>{
            pause();
            if (bar.hidden || !storageKey || remaining<=0) return;
            try {sessionStorage.setItem(storageKey,JSON.stringify({total,single,remaining,savedAt:Date.now()}));}
            catch (_) { /* Navigation still works without storage. */ }
        });
        window.addEventListener('pageshow',event=>{
            if (event.persisted) {hide();restore();}
        });
        action.addEventListener('click',event=>{
            event.stopPropagation();
            const item=single;
            dismiss();
            if (item) onItem(item,event); else onGroup();
        });
        bar.querySelector('.customer-update-close').addEventListener('click',()=>dismiss(true));
        bar.addEventListener('pointerenter',pause); bar.addEventListener('pointerleave',resume);
        bar.addEventListener('focusin',pause);
        bar.addEventListener('focusout',()=>setTimeout(resume,0));
        bar.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismiss(true);}});
        document.addEventListener('visibilitychange',()=>document.hidden?pause():resume());
        window.addEventListener('resize',place);
        if (navbar && typeof ResizeObserver==='function') new ResizeObserver(place).observe(navbar);
        return {show,dismiss,restore};
    }};
})();
