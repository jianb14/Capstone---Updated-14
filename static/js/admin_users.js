/* Read-only profiles; filters and explicit account access changes share one document. */
(() => {
    'use strict';
    const root=document.querySelector('.um-workspace');
    if(!root)return;
    const form=document.getElementById('userFilters'), results=document.getElementById('userResults');
    const search=form.elements.search, clear=form.querySelector('.ac-search-clear'), notice=document.getElementById('userListFeedback');
    const modal=document.getElementById('userDetailModal'), content=document.getElementById('userDetailContent'), detailNotice=document.getElementById('userDetailFeedback');
    const confirmation=document.getElementById('userAccessModal'), accessForm=document.getElementById('userAccessForm'), submit=document.getElementById('userAccessSubmit'), accessNotice=document.getElementById('userAccessFeedback');
    const selects=window.AdminSelects.create(root);
    const listURL=new URL(root.dataset.usersUrl,location.origin);
    let listRequest,detailRequest,listVersion=0,detailVersion=0,timer,detailId,detailOrigin,accessOrigin,pending,saving=false;
    let size=results.querySelector('[data-list-size]')?.value || '8', originalOverflow;
    async function request(url,options={}) {
        const controller=new AbortController(), abort=()=>controller.abort();
        options.signal?.addEventListener('abort',abort,{once:true});
        const timeout=setTimeout(abort,18000);
        try {
            if(options.signal?.aborted)abort();
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal,
                headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest',...options.headers}});
            if(response.redirected)throw new Error('Your session ended. Please sign in again.');
            const data=await response.json().catch(()=>({}));
            if(!response.ok)throw new Error(data.message || (response.status===404?'This account is no longer available.':'We could not complete this request. Please try again.'));
            return data;
        } finally {clearTimeout(timeout);options.signal?.removeEventListener('abort',abort);}
    }
    function feedback(node,text,retry) {
        node.replaceChildren(document.createTextNode(text));
        if(retry){const button=document.createElement('button');button.type='button';button.className='ac-button';button.textContent='Try again';button.addEventListener('click',retry,{once:true});node.append(' ',button);}
    }
    function filtersURL() {
        const url=new URL(listURL);
        for(const [key,value] of new FormData(form))if(value)url.searchParams.set(key,value);
        url.searchParams.set('per_page',results.querySelector('[data-list-size]')?.value || size);url.searchParams.set('page','1');return url;
    }
    function updateCounts(counts){root.querySelectorAll('[data-user-stat]').forEach(node=>node.textContent=String(counts[node.dataset.userStat] ?? 0));}
    function animateList(){results.classList.remove('um-results-enter');void results.offsetWidth;results.classList.add('um-results-enter');}
    async function load(url,{history=true}={}) {
        clearTimeout(timer);listRequest?.abort();selects.close();
        const controller=listRequest=new AbortController(),version=++listVersion;
        results.setAttribute('aria-busy','true');feedback(notice,'');
        try {
            const data=await request(url,{signal:controller.signal});if(version!==listVersion)return false;
            if(results.contains(document.activeElement))search.focus({preventScroll:true});
            selects.release(results);const scroll=window.scrollY;
            results.innerHTML=data.html;updateCounts(data.counts);selects.enhance();animateList();
            const actual=new URL(url,location.href);actual.pathname=listURL.pathname;actual.searchParams.delete('user_id');actual.searchParams.set('page',String(data.page));
            size=actual.searchParams.get('per_page')==='4'?'4':'8';
            if(history)window.history.pushState({},'',actual);
            else if(location.pathname===listURL.pathname)window.history.replaceState({},'',actual);
            if(window.scrollY!==scroll)window.scrollTo({top:scroll,behavior:'instant'});
            return true;
        } catch(error) {
            if(version===listVersion && !controller.signal.aborted)feedback(notice,error.name==='AbortError'?'The request took too long. Your current list is still here.':error.message,()=>load(url,{history}));
            return false;
        } finally {if(version===listVersion)results.removeAttribute('aria-busy');}
    }
    function lockScroll(){if(originalOverflow===undefined){originalOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}}
    function unlockScroll(){if(!modal.open&&!confirmation.open&&originalOverflow!==undefined){document.body.style.overflow=originalOverflow;originalOverflow=undefined;}}
    function detailURL(id){return root.dataset.detailsPattern.replace('/0/',`/${id}/`);}
    async function fillDetails(id) {
        detailRequest?.abort();const controller=detailRequest=new AbortController(),version=++detailVersion;
        content.hidden=true;feedback(detailNotice,'Loading account details...');
        try {
            const data=await request(detailURL(id),{signal:controller.signal});
            if(version!==detailVersion||!modal.open||String(detailId)!==String(id))return;
            content.innerHTML=data.html;content.hidden=false;feedback(detailNotice,'');
        } catch(error) {
            if(version===detailVersion&&!controller.signal.aborted)feedback(detailNotice,error.name==='AbortError'?'Loading took too long. Please try again.':error.message,()=>fillDetails(id));
        }
    }
    function openDetails(id,origin) {
        detailId=String(id);detailOrigin=origin;selects.close();lockScroll();
        if(!modal.open)modal.showModal();fillDetails(id);
    }
    function closeDetails(){if(confirmation.open||saving)return;detailRequest?.abort();++detailVersion;modal.close();}
    modal.addEventListener('close',()=>{detailRequest?.abort();++detailVersion;unlockScroll();if(detailOrigin?.isConnected)detailOrigin.focus({preventScroll:true});});
    modal.addEventListener('cancel',event=>{if(confirmation.open||saving)event.preventDefault();});
    function showConfirmation(button) {
        if(saving)return;
        accessOrigin=button;
        pending={id:button.dataset.userId,url:button.dataset.actionUrl,active:button.dataset.userActive==='1',name:button.dataset.userName,email:button.dataset.userEmail};
        const verb=pending.active?'Deactivate':'Activate';
        confirmation.dataset.action=pending.active?'deactivate':'activate';
        document.getElementById('userAccessTitle').textContent=`${verb} account?`;
        document.getElementById('userAccessDescription').textContent=pending.active?`${pending.name} will no longer be able to sign in. You can restore access later.`:`Restore sign-in access for ${pending.name}? Email verification will still be required if it has not been completed.`;
        document.getElementById('userAccessEmail').textContent=pending.email || 'No email address on file';
        submit.textContent=`${verb} account`;submit.disabled=!pending.email;feedback(accessNotice,pending.email?'':'This account has no email address. Its access cannot be changed.');
        selects.close();lockScroll();confirmation.showModal();
    }
    function closeConfirmation(){if(!saving)confirmation.close();}
    confirmation.addEventListener('cancel',event=>{if(saving)event.preventDefault();});
    confirmation.addEventListener('close',()=>{unlockScroll();if(accessOrigin?.isConnected)accessOrigin.focus({preventScroll:true});});
    accessForm.addEventListener('submit',async event=>{
        event.preventDefault();if(saving||!pending||!pending.email)return;
        saving=true;const action={...pending},body=new FormData();
        body.set('action',action.active?'deactivate':'activate');body.set('expected_active',action.active?'1':'0');
        submit.disabled=true;submit.textContent='Sending notification...';feedback(accessNotice,'');confirmation.setAttribute('aria-busy','true');
        confirmation.querySelectorAll('[data-close-access]').forEach(button=>button.disabled=true);
        let completed;
        try {
            completed=await request(action.url,{method:'POST',body,headers:{'X-CSRFToken':accessForm.querySelector('[name="csrfmiddlewaretoken"]').value}});
        } catch(error) {
            feedback(accessNotice,error.name==='AbortError'?'The request took too long to confirm. Refresh this account before trying again.':error.message);
            window.AdminConfigurationFeedback?.show(accessNotice.textContent,'error');
            accessNotice.focus({preventScroll:true});
        } finally {
            saving=false;confirmation.removeAttribute('aria-busy');submit.disabled=false;submit.textContent=action.active?'Deactivate account':'Activate account';
            confirmation.querySelectorAll('[data-close-access]').forEach(button=>button.disabled=false);
        }
        if(completed){
            confirmation.close();window.AdminConfigurationFeedback?.show(completed.message);
            // Finish this form before refreshing, so a later action keeps its own controls.
            if(modal.open&&String(detailId)===action.id)fillDetails(detailId);
            const url=new URL(location.href);url.pathname=listURL.pathname;url.searchParams.delete('user_id');
            await load(url,{history:false});
        }
    });
    root.addEventListener('click',event=>{
        if(event.target.closest('[data-close-user]'))closeDetails();
        if(event.target.closest('[data-close-access]'))closeConfirmation();
        const action=event.target.closest('.um-access-toggle');if(action)showConfirmation(action);
        const view=event.target.closest('.um-view');
        if(view&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){event.preventDefault();openDetails(view.dataset.userId,view);}
        const page=event.target.closest('[data-list-page]');
        if(page&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){event.preventDefault();const url=new URL(page.href);url.pathname=listURL.pathname;url.searchParams.delete('user_id');load(url);}
        if(event.target.closest('[data-list-reset],[data-reset-filters]')){
            form.reset();search.value='';form.elements.role.value='';form.elements.status.value='';clear.hidden=true;selects.sync();load(filtersURL());
        }
    });
    [modal,confirmation].forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom){if(dialog===modal)closeDetails();else closeConfirmation();}}));
    search.addEventListener('input',()=>{clear.hidden=!search.value;listRequest?.abort();++listVersion;results.removeAttribute('aria-busy');clearTimeout(timer);timer=setTimeout(()=>load(filtersURL()),280);});
    clear.addEventListener('click',()=>{search.value='';clear.hidden=true;search.focus();load(filtersURL());});
    form.addEventListener('submit',event=>{event.preventDefault();load(filtersURL());});
    form.addEventListener('change',event=>{if(event.target.matches('select'))load(filtersURL());});
    results.addEventListener('change',event=>{if(event.target.matches('[data-list-size]'))load(filtersURL());});
    window.addEventListener('popstate',()=>{
        const url=new URL(location.href);search.value=url.searchParams.get('search') || '';form.elements.role.value=url.searchParams.get('role') || '';form.elements.status.value=url.searchParams.get('status') || '';
        size=url.searchParams.get('per_page')==='4'?'4':'8';const current=results.querySelector('[data-list-size]');if(current)current.value=size;
        clear.hidden=!search.value;selects.sync();load(url,{history:false});
    });
    selects.enhance();
    if(root.dataset.initialUser){
        detailId=root.dataset.initialUser;lockScroll();modal.showModal();
        if(!content.querySelector('[data-detail-user]'))fillDetails(detailId);
    }
})();
