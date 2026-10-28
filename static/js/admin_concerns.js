/* The queue, filters and ticket updates stay on the same document. */
(() => {
    'use strict';
    const root=document.querySelector('.ac-workspace');
    if (!root) return;
    const form=document.getElementById('acFilters'), results=document.getElementById('adminConcernResults');
    const notice=document.getElementById('acListFeedback'), search=form.elements.q, clear=form.querySelector('.ac-search-clear');
    const modal=document.getElementById('concernDetailModal'), detail=document.getElementById('acDetailContent');
    const update=document.getElementById('concernUpdateForm'), save=document.getElementById('acUpdateSubmit');
    const detailNotice=document.getElementById('acDetailFeedback'), updateNotice=document.getElementById('acUpdateFeedback');
    const lightbox=document.getElementById('concernImageLightbox'), dates=document.getElementById('acDateFilters');
    let pageSize=results.querySelector('[data-list-size]')?.value || (new URL(location.href).searchParams.get('per_page')==='4'?'4':'8');
    let listRequest, detailRequest, listVersion=0, detailVersion=0, timer, ticket, origin, saving=false, removeTicketURL=true, queueNeedsRefresh=false;
    const selects=window.AdminSelects.create(root);
    async function request(url, options={}) {
        const timeout=new AbortController(), abort=()=>timeout.abort();
        options.signal?.addEventListener('abort',abort,{once:true});
        const clock=setTimeout(abort,12000);
        try {
            if (options.signal?.aborted) timeout.abort();
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:timeout.signal,
                headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest',...options.headers}});
            if (response.redirected) throw new Error('Your session ended. Please sign in again.');
            const data=await response.json().catch(()=>({}));
            if (!response.ok) { const error=new Error(data.message || data.error || 'We could not complete this request. Please try again.');error.status=response.status;throw error; }
            return data;
        } finally { clearTimeout(clock); options.signal?.removeEventListener('abort',abort); }
    }
    function showError(element,message,retry) {
        element.dataset.kind='error';
        element.replaceChildren(document.createTextNode(message));
        if (retry) {
            const button=document.createElement('button'); button.type='button'; button.className='ac-button'; button.textContent='Try again';
            button.addEventListener('click',retry,{once:true}); element.append(' ',button);
        }
    }
    function counts(data) {
        root.querySelectorAll('[data-stat]').forEach(node=>{node.textContent=String(data[node.dataset.stat] ?? 0);});
        const link=document.querySelector('.sidebar [data-concerns-link]');
        if (link) {
            let badge=link.querySelector('.nav-count-badge');
            if (!badge) { badge=document.createElement('span'); badge.className='nav-count-badge'; link.append(badge); }
            badge.textContent=String(data.new || 0); badge.hidden=!data.new;
        }
    }
    function enhance() { selects.enhance(); }
    function filtersURL() {
        const url=new URL(root.dataset.queueUrl,location.origin);
        for(const [key,value] of new FormData(form))if(value)url.searchParams.set(key,value);
        const size=results.querySelector('[data-list-size]')?.value || pageSize;
        url.searchParams.set('per_page',size);
        url.searchParams.set('page','1'); return url;
    }
    function validDates() {
        const start=form.elements.start_date, end=form.elements.end_date;
        const message=Boolean(start.value)!==Boolean(end.value)?'Choose both a start date and end date.':start.value>end.value?'The end date must be on or after the start date.':'';
        showError(notice,message); return !message;
    }
    async function load(url,history=true) {
        if(!validDates())return;
        clearTimeout(timer); listRequest?.abort(); selects.close();
        const controller=listRequest=new AbortController(), version=++listVersion;
        results.setAttribute('aria-busy','true'); showError(notice,'');
        try {
            const data=await request(url,{signal:controller.signal}); if(version!==listVersion)return;
            // Move focus out of a footer that is about to be replaced.
            if(results.contains(document.activeElement))search.focus({preventScroll:true});
            selects.release(results);
            const position=window.scrollY;
            results.innerHTML=data.html; counts(data.counts); enhance();
            if (window.scrollY !== position) window.scrollTo({top:position,behavior:'instant'});
            const actual=new URL(url,location.href); actual.searchParams.set('page',String(data.page)); actual.searchParams.delete('concern_id');
            pageSize=actual.searchParams.get('per_page')==='4'?'4':'8';
            if(history)window.history.pushState({},'',actual);
        } catch(error) {
            if(version===listVersion && !controller.signal.aborted)showError(notice,error.name==='AbortError'?'The request took too long. Your current list is still here.':error.message,()=>load(url,history));
        } finally { if(version===listVersion)results.removeAttribute('aria-busy'); }
    }
    function reset(all=true) {
        if(all){form.reset();search.value='';form.elements.category.value='';form.elements.concern_status.value='';clear.hidden=true;}
        form.elements.start_date.value='';form.elements.end_date.value='';
        selects.sync();load(filtersURL());
    }
    search.addEventListener('input',()=>{clear.hidden=!search.value;listRequest?.abort();++listVersion;results.removeAttribute('aria-busy');clearTimeout(timer);timer=setTimeout(()=>load(filtersURL()),280);});
    clear.addEventListener('click',()=>{search.value='';clear.hidden=true;search.focus();load(filtersURL());});
    form.addEventListener('submit',event=>{event.preventDefault();load(filtersURL());});
    form.addEventListener('change',event=>{if(event.target.matches('select'))load(filtersURL());});
    root.addEventListener('change',event=>{if(event.target.matches('[data-list-size]'))load(filtersURL());});
    root.addEventListener('click',event=>{
        const link=event.target.closest('[data-list-page]');
        if(link && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey){event.preventDefault();load(new URL(link.href));}
        if(event.target.closest('[data-reset-filters],[data-list-reset]'))reset();
        if(event.target.closest('[data-reset-dates]'))reset(false);
        const view=event.target.closest('.btn-view-concern');if(view)openDetails(view.dataset.detailsUrl,view);
    });
    document.getElementById('acDatesToggle').addEventListener('click',event=>{
        dates.hidden=!dates.hidden;event.currentTarget.setAttribute('aria-expanded',String(!dates.hidden));
    });
    const setText=(id,text)=>{document.getElementById(id).textContent=text || '';};
    function displayTicket(data) {
        ticket=data.ticket; const canUpdate=data.can_update!==false && ticket.status!=='cancelled';
        setText('acTicketNumber',ticket.number);setText('concernModalTitle',ticket.subject);
        setText('acDetailCategory',ticket.category);setText('acDetailStatus',ticket.status_label);
        document.getElementById('acDetailStatus').className=`ac-status ac-status--${ticket.status}`;
        for(const [key,value]of Object.entries({Customer:ticket.name,Email:ticket.email,Created:ticket.created,Updated:ticket.updated,Message:ticket.message}))setText(`acDetail${key}`,value);
        const images=document.getElementById('acDetailImages');images.replaceChildren();
        ticket.images.forEach((image,index)=>{
            const button=document.createElement('button');button.type='button';button.setAttribute('aria-label',`View attachment ${index+1}`);
            const img=document.createElement('img');img.src=image.url;img.alt=`Concern attachment ${index+1}`;button.append(img);
            button.addEventListener('click',()=>{selects.close();lightbox.querySelector('img').src=image.url;lightbox.showModal();});images.append(button);
        });
        document.getElementById('acDetailAttachments').hidden=!ticket.images.length;
        update.hidden=!canUpdate;save.hidden=!canUpdate;save.disabled=false;
        document.getElementById('acReadOnlyUpdate').hidden=canUpdate;
        document.getElementById('cancelledConcernNote').hidden=ticket.status!=='cancelled';
        document.getElementById('acReadOnlyNotes').hidden=ticket.status==='cancelled';
        setText('acReadOnlyNotes',ticket.admin_notes||'No customer update yet.');
        update.action=ticket.update_url;update.elements.status.value=canUpdate?ticket.status:'new';
        update.elements.admin_notes.value=ticket.admin_notes || '';selects.sync(update.elements.status);
        detail.hidden=false;showError(detailNotice,'');showError(updateNotice,'');
    }
    async function openDetails(url,button) {
        origin=button || document.activeElement;detailRequest?.abort(); const version=++detailVersion;
        detailRequest=new AbortController();detail.hidden=true;save.hidden=true;ticket=null;
        setText('acTicketNumber','Concern details');setText('concernModalTitle','Loading concern');showError(detailNotice,'Loading the latest details…');
        if(!modal.open){modal.showModal();document.body.classList.add('ac-modal-open');}
        try { const data=await request(url,{signal:detailRequest.signal});if(version===detailVersion && modal.open)displayTicket(data); }
        catch(error){if(version===detailVersion && modal.open && !detailRequest.signal.aborted){setText('concernModalTitle','Concern details');showError(detailNotice,error.message,()=>openDetails(url,origin));}}
    }
    function closeDetails(cleanURL=true) { if(saving)return;removeTicketURL=cleanURL;selects.close();detailRequest?.abort();modal.close(); }
    modal.addEventListener('close',()=>{
        selects.close();detailRequest?.abort();document.body.classList.remove('ac-modal-open');
        const url=new URL(location.href);if(removeTicketURL && url.searchParams.has('concern_id')){url.searchParams.delete('concern_id');history.replaceState({},'',url);}removeTicketURL=true;
        if(origin?.isConnected)origin.focus({preventScroll:true});
        refreshQueueIfIdle();
    });
    modal.addEventListener('cancel',event=>{if(saving)event.preventDefault();else selects.close();});
    modal.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>closeDetails()));
    modal.addEventListener('click',event=>{if(event.target===modal)closeDetails();});
    lightbox.querySelector('button').addEventListener('click',()=>lightbox.close());
    lightbox.addEventListener('click',event=>{if(event.target===lightbox)lightbox.close();});
    update.addEventListener('submit',async event=>{
        event.preventDefault();if(saving || !ticket || !update.reportValidity())return;
        const payload=new FormData(update);
        saving=true;save.disabled=true;save.textContent='Saving…';showError(updateNotice,'');
        update.querySelectorAll('input,select,textarea,button').forEach(control=>control.disabled=true);
        modal.querySelectorAll('[data-close-dialog]').forEach(button=>button.disabled=true);
        const submitted=ticket.id;
        try {
            const data=await request(update.action,{method:'POST',body:payload});
            if(!data.success)throw new Error(data.message || 'The update could not be saved.');
            window.AdminConfigurationFeedback?.show(data.message);
            if(ticket?.id===submitted){displayTicket({...data,can_update:true});showError(updateNotice,data.message);updateNotice.dataset.kind='success';}
            counts(data.counts);const url=new URL(location.href);url.searchParams.delete('concern_id');await load(url,false);window.AdminNotifications?.syncCount();
        } catch(error){
            if(error.status===409){
                try { displayTicket(await request(root.dataset.detailsPattern.replace('/0/',`/${submitted}/`))); } catch(_) { /* Retain the draft and original conflict message. */ }
            }
            const message=error.name==='AbortError'?'The response took too long. Check the latest concern before trying again.':error.message;
            showError(updateNotice,message);if(update.hidden)showError(detailNotice,message);else updateNotice.focus();
            window.AdminConfigurationFeedback?.show(message,'error');
        }
        finally {saving=false;save.disabled=false;save.textContent='Save update';update.querySelectorAll('input,select,textarea,button').forEach(control=>control.disabled=false);modal.querySelectorAll('[data-close-dialog]').forEach(button=>button.disabled=false);}
    });
    window.addEventListener('popstate',()=>{
        const url=new URL(location.href);
        if(modal.open && !saving)closeDetails(false);
        for(const key of ['q','category','concern_status','start_date','end_date'])form.elements[key].value=url.searchParams.get(key)||'';
        selects.sync();clear.hidden=!search.value;dates.hidden=!form.elements.start_date.value&&!form.elements.end_date.value;
        document.getElementById('acDatesToggle').setAttribute('aria-expanded',String(!dates.hidden));load(url,false);
        const key=url.searchParams.get('concern_id');
        if(key && /^[1-9]\d{0,18}$/.test(key))openDetails(root.dataset.detailsPattern.replace('/0/',`/${key}/`));
    });
    enhance();
    function refreshQueueIfIdle(){
        if(queueNeedsRefresh && !modal.open && !saving && !results.hasAttribute('aria-busy') && search.value===(new URL(location.href).searchParams.get('q')||'')){
            queueNeedsRefresh=false;load(new URL(location.href),false);
        }
    }
    window.addEventListener('admin:concerns-counts',event=>{
        const changed=[...root.querySelectorAll('[data-stat]')].some(node=>Number(node.textContent)!==event.detail[node.dataset.stat]);
        counts(event.detail);if(changed)queueNeedsRefresh=true;refreshQueueIfIdle();
    });
    window.AdminConcerns={openTicket(target){
        const url=new URL(target,location.href), key=url.searchParams.get('concern_id');
        if(key && /^[1-9]\d{0,18}$/.test(key)){
            const current=new URL(location.href);current.searchParams.set('concern_id',key);history.pushState({},'',current);
            openDetails(root.dataset.detailsPattern.replace('/0/',`/${key}/`));
        }
    }};
    const key=new URL(location.href).searchParams.get('concern_id');
    if(key && /^[1-9]\d{0,18}$/.test(key))openDetails(root.dataset.detailsPattern.replace('/0/',`/${key}/`));
})();
