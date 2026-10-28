/* Notifications stay mounted with the navbar across account navigation. */
(() => {
    'use strict';
    const root=document.querySelector('.notification-wrapper'), panel=document.getElementById('notif-dropdown');
    if (!root || !panel) return;
    const isAdmin=root.dataset.audience==='admin';
    function syncConcerns(data) {
        if (isAdmin && Number.isFinite(data.new_concerns_count)) {
            if (data.concern_counts) window.dispatchEvent(new CustomEvent('admin:concerns-counts',{detail:data.concern_counts}));
            const link=document.querySelector('.sidebar a[data-concerns-link]');
            if (!link) return;
            let badge=link.querySelector('.nav-count-badge');
            if (!badge) { badge=document.createElement('span'); badge.className='nav-count-badge'; link.append(badge); }
            badge.textContent=String(data.new_concerns_count); badge.hidden=!data.new_concerns_count;
        }
    }
    const bell=document.getElementById('notif-bell'), list=panel.querySelector('.notif-list');
    const markAll=document.getElementById('clear-all-notifs'), more=panel.querySelector('.notif-load-more');
    const feedback=panel.querySelector('.notif-feedback'), summary=document.getElementById('notif-summary');
    const canPopover=typeof panel.showPopover==='function';
    let nextCursor=null, loading=false, count=0, mutation=Promise.resolve(), revision=0, checkingCount=false;
    const reading=new Set();
    if (canPopover) { panel.setAttribute('popover','manual'); panel.classList.add('notification-popover'); }
    function place() {
        const box=bell.getBoundingClientRect(), right=Math.max(12,innerWidth-box.right);
        panel.style.setProperty('--nt-top',`${Math.max(12,box.bottom+12)}px`);
        panel.style.setProperty('--nt-right',`${innerWidth<=600?12:Math.min(right,innerWidth-372)}px`);
    }
    function status(message,retry) {
        if (feedback.contains(document.activeElement)) bell.focus({preventScroll:true});
        feedback.replaceChildren(document.createTextNode(message)); feedback.hidden=!message;
        if (retry) {
            const button=document.createElement('button'); button.type='button'; button.textContent='Try again';
            button.addEventListener('click',retry,{once:true}); feedback.append(button);
        }
    }
    function updateCount(value) {
        count=Math.max(0,Number(value)||0);
        let badge=bell.querySelector('.notif-badge');
        if (count && !badge) { badge=document.createElement('span'); badge.className='notif-badge'; badge.setAttribute('aria-hidden','true'); bell.append(badge); }
        if (badge) { if (count) badge.textContent=count>99?'99+':String(count); else badge.remove(); }
        summary.textContent=count?`${count} unread`:"You're all caught up";
        bell.setAttribute('aria-label',count?`Notifications, ${count} unread`:'Notifications');
        markAll.disabled=!count || markAll.dataset.busy==='true';
    }
    function readUI(item) { item?.classList.remove('unread'); item?.querySelector('.unread-dot')?.remove(); }
    async function jsonRequest(url,options={}) {
        const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),10000);
        try {
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal,
                headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest',...options.headers}});
            if (response.redirected) throw new Error('Please sign in again to load notifications.');
            const data=await response.json().catch(()=>({}));
            if (!response.ok) throw new Error(data.message || 'We could not update notifications.');
            return data;
        } finally { clearTimeout(timer); }
    }
    function post(url) {
        const token=panel.querySelector('[name="csrfmiddlewaretoken"]')?.value;
        return jsonRequest(url,{method:'POST',keepalive:true,headers:{'X-CSRFToken':token || ''}}).then(data=>{
            if (data.status!=='success') throw new Error('We could not update notifications.'); return data;
        });
    }
    function day(date) {
        return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Manila',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
    }
    function groupDates() {
        list.querySelectorAll('.notif-date-header').forEach(header=>header.remove());
        let previous;
        list.querySelectorAll('.notif-item').forEach(item=>{
            const date=new Date(item.dataset.createdAt); if (Number.isNaN(date.getTime())) return;
            const key=day(date); if (key===previous) return; previous=key;
            const header=document.createElement('div'); header.className='notif-date-header';
            header.textContent=key===day(new Date())?'Today':key===day(new Date(Date.now()-86400000))?'Yesterday':
                date.toLocaleDateString('en-US',{timeZone:'Asia/Manila',month:'short',day:'numeric',year:'numeric'});
            item.before(header);
        });
    }
    function safeTarget(value) {
        try { const url=new URL(value,location.origin); return url.origin===location.origin?url.href:null; }
        catch { return null; }
    }
    function makeItem(data) {
        const item=document.createElement('a'); item.className=`notif-item${data.is_read?'':' unread'}`;
        item.href=safeTarget(data.target_url) || (isAdmin?'/staff/concerns/':'/customer/');
        item.dataset.id=String(data.id); item.dataset.readUrl=data.read_url; item.dataset.createdAt=data.created_at;
        const content=document.createElement('div'); content.className='notif-content';
        const message=document.createElement('p'); message.textContent=data.message;
        const meta=document.createElement('div'); meta.className='notif-meta';
        const time=document.createElement('small'), date=new Date(data.created_at);
        time.textContent=Number.isNaN(date.getTime())?'':date.toLocaleString('en-US',
            {timeZone:'Asia/Manila',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
        const hint=document.createElement('span'); hint.className='notif-open-hint'; hint.setAttribute('aria-hidden','true');
        hint.innerHTML='View details <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>';
        meta.append(time,hint); content.append(message,meta); item.append(content);
        if (!data.is_read) { const dot=document.createElement('span'); dot.className='unread-dot'; item.append(dot); }
        return item;
    }
    async function refresh(append=false) {
        if (loading) return;
        if (document.activeElement===more) bell.focus({preventScroll:true});
        loading=true; list.setAttribute('aria-busy','true'); more.disabled=true; status('');
        let superseded=false;
        try {
            await mutation;
            const requestedRevision=revision;
            const url=new URL(root.dataset.feedUrl,location.href);
            if (append && nextCursor) url.searchParams.set('cursor',nextCursor);
            const data=await jsonRequest(url);
            if (requestedRevision!==revision) { superseded=true; return; }
            if (!Array.isArray(data.items)) throw new Error('Notifications are unavailable.');
            if (!append) {
                if (list.contains(document.activeElement)) bell.focus({preventScroll:true});
                list.replaceChildren();
            }
            list.querySelector('.notif-empty')?.remove();
            const existing=new Set([...list.querySelectorAll('.notif-item')].map(item=>item.dataset.id));
            data.items.forEach(item=>{ if (!existing.has(String(item.id))) list.append(makeItem(item)); });
            if (!list.querySelector('.notif-item')) {
                const empty=document.createElement('div'); empty.className='notif-empty';
                empty.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8M10 21h4"/></svg><h3>No notifications yet</h3><p>Booking and payment updates will appear here.</p>';
                if (isAdmin) empty.querySelector('p').textContent='Customer bookings, payments and concerns will appear here.';
                list.append(empty);
            }
            nextCursor=data.next_cursor; more.hidden=!nextCursor; updateCount(data.unread_count); syncConcerns(data); groupDates();
        } catch(error) {
            status(error.name==='AbortError'?'Notifications took too long to load. Your current list is still here.':error.message,()=>refresh(append));
        } finally {
            loading=false; list.removeAttribute('aria-busy'); more.disabled=false;
            if (superseded && !panel.hidden) refresh(append);
        }
    }
    function close(restore=false) {
        if (canPopover && panel.matches(':popover-open')) panel.hidePopover();
        panel.classList.remove('show'); panel.hidden=true; bell.setAttribute('aria-expanded','false');
        if (restore) bell.focus();
    }
    async function syncCount() {
        if (checkingCount || loading || !panel.hidden || document.hidden || reading.size || markAll.dataset.busy==='true') return;
        checkingCount=true;
        const requestedRevision=revision;
        try {
            const url=new URL(root.dataset.feedUrl,location.href);
            url.searchParams.set('summary','1');
            const data=await jsonRequest(url);
            if (requestedRevision===revision) { updateCount(data.unread_count); syncConcerns(data); }
        } catch (_) { /* Retain the last confirmed count until the next check. */ }
        finally { checkingCount=false; }
    }
    function open(focus=false) {
        window.closeClientAccountMenu?.(); panel.hidden=false; place(); panel.classList.add('show');
        if (canPopover && !panel.matches(':popover-open')) panel.showPopover();
        bell.setAttribute('aria-expanded','true');
        refresh().then(()=>{if (focus && !panel.hidden) (list.querySelector('.notif-item') || markAll)?.focus();});
    }
    function queueRead(item) {
        if (!item.classList.contains('unread') || reading.has(item.dataset.id)) return;
        revision++;
        const id=item.dataset.id; reading.add(id);
        mutation=mutation.then(()=>post(item.dataset.readUrl)).then(data=>{
            readUI(list.querySelector(`[data-id="${id}"]`)); updateCount(data.unread_count);
        }).catch(()=>status('We could not mark this update as read. You can still open its details.',()=>queueRead(item)))
            .finally(()=>reading.delete(id));
    }
    bell.addEventListener('click',()=>panel.hidden?open():close());
    bell.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();open(true);}});
    more.addEventListener('click',()=>refresh(true));
    markAll.addEventListener('click',()=>{
        if (markAll.disabled) return;
        revision++;
        if (document.activeElement===markAll) bell.focus({preventScroll:true});
        markAll.dataset.busy='true'; markAll.disabled=true; status('');
        mutation=mutation.then(()=>post(root.dataset.readAllUrl)).then(data=>{
            list.querySelectorAll('.notif-item.unread').forEach(readUI); updateCount(data.unread_count);
        }).catch(()=>status('Your notifications are still unread. Please try again.',()=>markAll.click()))
            .finally(()=>{delete markAll.dataset.busy; updateCount(count);});
    });
    list.addEventListener('click',event=>{
        const item=event.target.closest('.notif-item'); if (!item || event.defaultPrevented) return;
        const target=safeTarget(item.href); if (!target) {event.preventDefault();return;}
        queueRead(item);
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button!==0) return;
        event.preventDefault(); close();
        if (isAdmin && window.AdminConcerns && new URL(target).pathname===location.pathname && new URL(target).searchParams.has('concern_id')) window.AdminConcerns.openTicket(target);
        else if (document.getElementById('accountContent') && window.AccountNavigation) AccountNavigation.navigate(target,{force:true});
        else location.assign(target);
    });
    list.addEventListener('auxclick',event=>{const item=event.target.closest('.notif-item');if(item && event.button===1)queueRead(item);});
    document.addEventListener('click',event=>{if(!panel.hidden && !event.composedPath().includes(root))close();});
    document.addEventListener('keydown',event=>{if(!panel.hidden && event.key==='Escape'){event.preventDefault();close(true);}});
    root.addEventListener('focusout',event=>{if(event.relatedTarget && !root.contains(event.relatedTarget))close();});
    window.addEventListener('resize',()=>{if(!panel.hidden)place();});
    window.addEventListener('scroll',()=>{if(!panel.hidden)place();},{passive:true});
    window.addEventListener('focus',syncCount);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncCount();});
    setInterval(syncCount,30000);
    updateCount(bell.dataset.unreadCount); groupDates();
    window.CustomerNotifications={close,refresh:()=>refresh()};
    if (isAdmin) window.AdminNotifications={close,syncCount};
})();
