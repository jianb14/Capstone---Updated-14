/* Read-only audit history: partial table updates and accessible inline details. */
(() => {
    'use strict';
    const root=document.querySelector('[data-audit-workspace]');
    if(!root)return;
    const form=document.getElementById('auditFilters'), results=document.getElementById('auditLogResults');
    const search=form.elements.search, clear=form.querySelector('.ac-search-clear');
    const dates=document.getElementById('auditDateFilters'), dateToggle=document.getElementById('auditDatesToggle');
    const feedback=document.getElementById('auditListFeedback'), selects=window.AdminSelects.create(root);
    let pending, version=0, timer, expanded=null;
    let pageSize=results.querySelector('[data-list-size]')?.value || (new URL(location.href).searchParams.get('per_page')==='4'?'4':'8');

    function announce(message,retry){
        feedback.replaceChildren(document.createTextNode(message));
        if(retry){
            const button=document.createElement('button');button.type='button';button.className='ac-button';button.textContent='Try again';
            button.addEventListener('click',retry,{once:true});feedback.append(' ',button);
        }
    }
    function sizeDetails(){
        const table=results.querySelector('.audit-table-scroll');
        if(!table)return;
        const value=`${Math.max(120,table.clientWidth-32)}px`;
        if(results.style.getPropertyValue('--audit-detail-width')!==value)results.style.setProperty('--audit-detail-width',value);
        if(expanded){
            const action=document.getElementById(`audit-detail-${expanded}`)?.querySelector('.audit-full-action');
            if(action && action.scrollHeight>action.clientHeight){action.tabIndex=0;action.setAttribute('role','region');action.setAttribute('aria-label','Full recorded activity');}
            else if(action){action.removeAttribute('tabindex');action.removeAttribute('role');action.removeAttribute('aria-label');}
        }
    }
    function closeRow(id){
        const row=results.querySelector(`[data-audit-row="${id}"]`), panel=document.getElementById(`audit-detail-${id}`);
        if(!row || !panel)return;
        panel.hidden=true;row.classList.remove('is-expanded');
        const button=row.querySelector('[data-audit-toggle]');
        button.setAttribute('aria-expanded','false');button.setAttribute('aria-label',`Show details for activity #LOG-${id}`);
    }
    function toggleRow(id){
        if(!/^\d+$/.test(id))return;
        const row=results.querySelector(`[data-audit-row="${id}"]`), panel=document.getElementById(`audit-detail-${id}`);
        if(!row || !panel || !results.contains(panel))return;
        const opening=panel.hidden;
        if(expanded && expanded!==id)closeRow(expanded);
        const button=row.querySelector('[data-audit-toggle]');
        panel.hidden=!opening;row.classList.toggle('is-expanded',opening);
        button.setAttribute('aria-expanded',String(opening));
        button.setAttribute('aria-label',`${opening?'Hide':'Show'} details for activity #LOG-${id}`);
        expanded=opening?id:null;sizeDetails();
    }
    function filterURL(){
        const url=new URL(root.dataset.listUrl,location.origin);
        for(const [key,value] of new FormData(form))if(value)url.searchParams.set(key,value);
        url.searchParams.set('per_page',results.querySelector('[data-list-size]')?.value || pageSize);
        url.searchParams.set('page','1');return url;
    }
    function validDates(){
        const first=form.elements.date_from.value, last=form.elements.date_to.value;
        const error=Boolean(first)!==Boolean(last)?'Choose both a start date and end date.':first>last?'The end date must be on or after the start date.':'';
        announce(error);return !error;
    }
    function invalidate(){
        clearTimeout(timer);pending?.abort();version++;results.removeAttribute('aria-busy');
    }
    async function load(url,push=true){
        invalidate();selects.close();
        if(!validDates())return;
        const requested=version, controller=pending=new AbortController();
        let timedOut=false;
        const clock=setTimeout(()=>{timedOut=true;controller.abort();},12000);
        results.setAttribute('aria-busy','true');announce('');
        try{
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
                headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest'}});
            if(response.redirected)throw new Error('Your session ended. Please sign in again.');
            const data=await response.json().catch(()=>({}));
            if(!response.ok){const error=new Error(data.error || data.message || 'Activity history could not be loaded.');error.status=response.status;throw error;}
            if(typeof data.html!=='string' || !Number.isInteger(data.page) || ![4,8].includes(data.per_page))throw new Error('Activity history is unavailable. Please try again.');
            if(requested!==version)return;
            const position=window.scrollY;
            if(results.contains(document.activeElement))search.focus({preventScroll:true});
            selects.release(results);results.innerHTML=data.html;pageSize=String(data.per_page);expanded=null;
            selects.enhance();sizeDetails();
            if(window.scrollY!==position)window.scrollTo({top:position,behavior:'instant'});
            const actual=new URL(url,location.href);actual.searchParams.set('page',String(data.page));actual.searchParams.set('per_page',pageSize);
            if(push && actual.href!==location.href)history.pushState({},'',actual);
            else history.replaceState({},'',actual);
        }catch(error){
            if(requested===version && (!controller.signal.aborted || timedOut)){
                const message=timedOut?'The request took too long. Your current list is still here.':error.message;
                announce(message,error.status===400?null:()=>load(url,push));
            }
        }finally{clearTimeout(clock);if(requested===version)results.removeAttribute('aria-busy');}
    }
    function reset(all=true){
        if(all){search.value='';form.elements.role.value='';clear.hidden=true;}
        form.elements.date_from.value='';form.elements.date_to.value='';selects.sync();load(filterURL());
    }
    search.addEventListener('input',()=>{
        clear.hidden=!search.value;invalidate();timer=setTimeout(()=>load(filterURL()),280);
    });
    clear.addEventListener('click',()=>{search.value='';clear.hidden=true;search.focus();load(filterURL());});
    form.addEventListener('submit',event=>{event.preventDefault();load(filterURL());});
    form.addEventListener('change',event=>{if(event.target.matches('select'))load(filterURL());});
    dateToggle.addEventListener('click',()=>{dates.hidden=!dates.hidden;dateToggle.setAttribute('aria-expanded',String(!dates.hidden));});
    root.addEventListener('change',event=>{if(event.target.matches('[data-list-size]'))load(filterURL());});
    root.addEventListener('click',event=>{
        const page=event.target.closest('[data-list-page]');
        if(page && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey){event.preventDefault();load(new URL(page.href));return;}
        if(event.target.closest('[data-list-reset]')){reset();return;}
        if(event.target.closest('[data-audit-reset-dates]')){reset(false);return;}
        const button=event.target.closest('[data-audit-toggle]');
        if(button){toggleRow(button.dataset.auditToggle);return;}
        const row=event.target.closest('[data-audit-row]');
        if(row && !event.target.closest('a,button,input,select,textarea') && window.getSelection()?.isCollapsed!==false)toggleRow(row.dataset.auditRow);
    });
    root.addEventListener('keydown',event=>{
        if(event.key==='Escape' && !event.defaultPrevented && expanded){
            event.preventDefault();const id=expanded;closeRow(id);expanded=null;
            results.querySelector(`[data-audit-toggle="${id}"]`)?.focus({preventScroll:true});
        }
    });
    window.addEventListener('popstate',()=>{
        const url=new URL(location.href);
        for(const key of ['search','role','date_from','date_to'])form.elements[key].value=url.searchParams.get(key)||'';
        clear.hidden=!search.value;dates.hidden=!form.elements.date_from.value&&!form.elements.date_to.value;
        dateToggle.setAttribute('aria-expanded',String(!dates.hidden));selects.sync();load(url,false);
    });
    selects.enhance();sizeDetails();
    if(typeof ResizeObserver==='function')new ResizeObserver(sizeDetails).observe(results);
    else window.addEventListener('resize',sizeDetails);
})();
