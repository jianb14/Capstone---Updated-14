/* Private, bounded search suggestions; search never changes the current page. */
(() => {
    'use strict';
    const root=document.getElementById('adminGlobalSearch');if(!root)return;
    const input=root.querySelector('input'),form=root.querySelector('form'),panel=root.querySelector('.admin-search-popup');
    const list=root.querySelector('#adminSearchResults'),status=root.querySelector('.admin-search-status'),footer=root.querySelector('.admin-search-footer');
    const clear=root.querySelector('.admin-search-clear'),closeButton=root.querySelector('.admin-search-close');
    const topbar=root.closest('.admin-topbar'),toggle=topbar.querySelector('.admin-search-toggle');
    const compact=matchMedia('(max-width:1279px)'),popover=typeof panel.showPopover==='function';
    let controller,timer,version=0,active=-1,composition=false,loadedQuery='',restoringFocus=false;
    if(popover)panel.setAttribute('popover','manual');
    const items=()=>[...list.querySelectorAll('.admin-search-result')];
    function position(){
        if(!popover||panel.hidden)return;
        const box=form.getBoundingClientRect(),width=Math.min(compact.matches?box.width:Math.max(box.width,420),500,innerWidth-24);
        panel.style.width=`${width}px`;
        panel.style.left=`${Math.max(12,Math.min(box.left,innerWidth-width-12))}px`;
        panel.style.top=`${box.bottom+9}px`;
        panel.style.maxHeight=`${Math.max(100,Math.min(560,innerHeight-box.bottom-23))}px`;
    }
    function open(){
        window.CustomerNotifications?.close();window.closeClientAccountMenu?.();
        if(compact.matches){root.classList.add('is-open');toggle.setAttribute('aria-expanded','true');}
        panel.hidden=false;position();
        if(popover&&!panel.matches(':popover-open'))panel.showPopover();
        input.setAttribute('aria-expanded','true');
    }
    function select(index){
        const nodes=items();active=index;
        nodes.forEach((node,i)=>node.setAttribute('aria-selected',String(i===index)));
        if(nodes[index]){input.setAttribute('aria-activedescendant',nodes[index].id);nodes[index].scrollIntoView({block:'nearest'});}
        else input.removeAttribute('aria-activedescendant');
    }
    function close(restore=false){
        clearTimeout(timer);controller?.abort();++version;
        if(popover&&panel.matches(':popover-open'))panel.hidePopover();
        panel.hidden=true;input.setAttribute('aria-expanded','false');select(-1);
        root.classList.remove('is-open');toggle.setAttribute('aria-expanded','false');
        if(restore){restoringFocus=true;(compact.matches?toggle:input).focus({preventScroll:true});restoringFocus=false;}
    }
    function feedback(message,error=false,retry=false){
        list.replaceChildren();footer.hidden=true;select(-1);status.classList.toggle('is-error',error);
        status.replaceChildren(document.createTextNode(message));
        if(retry){const button=document.createElement('button');button.type='button';button.textContent='Try again';button.addEventListener('click',()=>search(),{once:true});status.append(button);}
    }
    function valid(query){return query.length>=2||/^[0-9]$/.test(query);}
    function idle(){loadedQuery='';feedback('Search by booking ID, customer name, email or payment reference.');}
    function resultIcon(key){
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
        const path=document.createElementNS(svg.namespaceURI,'path');
        path.setAttribute('d',key==='customers'?'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4 21v-2a8 8 0 0 1 16 0v2':key==='payments'?'M3 7h18v14H3ZM3 11h18M7 16h4':'M4 5h16v16H4ZM8 3v4m8-4v4M4 11h16');svg.append(path);return svg;
    }
    function render(data){
        const groups=Array.isArray(data.groups)?data.groups:[];list.replaceChildren();status.classList.remove('is-error');select(-1);
        let count=0;
        for(const group of groups){
            const section=document.createElement('div');section.className='admin-search-group';section.setAttribute('role','group');section.setAttribute('aria-label',group.label);
            const heading=document.createElement('span');heading.className='admin-search-group-label';heading.textContent=group.label;section.append(heading);
            for(const item of group.items||[]){
                const url=new URL(item.url,location.origin);if(url.origin!==location.origin||!url.pathname.startsWith('/staff/'))continue;
                const link=document.createElement('a');link.className='admin-search-result';link.href=url.href;link.id=`adminSearchOption${count++}`;link.setAttribute('role','option');link.setAttribute('aria-selected','false');link.tabIndex=-1;
                const copy=document.createElement('div');copy.className='admin-search-result-copy';
                const title=document.createElement('strong');title.textContent=item.title;
                const description=document.createElement('small');description.textContent=item.description;copy.append(title,description);
                link.append(resultIcon(group.key),copy);section.append(link);
            }
            list.append(section);
        }
        status.textContent=count?`${count} matching record${count===1?'':'s'}`:'No matching records. Try another name, ID or reference.';
        footer.hidden=!data.has_more;
    }
    async function search(){
        clearTimeout(timer);controller?.abort();const query=input.value.trim(),requestID=++version;
        clear.hidden=!input.value;
        if(!valid(query)){idle();return;}
        const current=controller=new AbortController(),timeout=setTimeout(()=>current.abort(),12000);
        feedback('Searching records…');open();
        try{
            const url=new URL(root.dataset.searchUrl,location.origin);url.searchParams.set('q',query);
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:current.signal,headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest'}});
            if(response.redirected)throw new Error('Your session ended. Sign in again to search.');
            const data=await response.json().catch(()=>({}));
            if(!response.ok)throw new Error(data.error||'Search is unavailable. Please try again.');
            if(!Array.isArray(data.groups))throw new Error('Search is unavailable. Please try again.');
            if(requestID!==version)return;
            loadedQuery=query;render(data);position();
        }catch(error){if(requestID===version&&!panel.hidden)feedback(error.name==='AbortError'?'Search took too long. Please try again.':error.message,true,true);}
        finally{clearTimeout(timeout);}
    }
    function schedule(){
        clear.hidden=!input.value;loadedQuery='';clearTimeout(timer);controller?.abort();++version;open();
        if(!valid(input.value.trim())){idle();return;}
        feedback('Searching records…');timer=setTimeout(search,250);
    }
    input.addEventListener('input',()=>{if(!composition)schedule();});
    input.addEventListener('compositionstart',()=>{composition=true;clearTimeout(timer);controller?.abort();++version;});
    input.addEventListener('compositionend',()=>{composition=false;schedule();});
    input.addEventListener('focus',()=>{if(restoringFocus)return;open();if(loadedQuery===input.value.trim()&&items().length)return;schedule();});
    input.addEventListener('keydown',event=>{
        if(event.isComposing||composition)return;
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&!panel.hidden&&items().length){
            event.preventDefault();const length=items().length;
            select(event.key==='Home'?0:event.key==='End'?length-1:active<0?(event.key==='ArrowUp'?length-1:0):(active+(event.key==='ArrowDown'?1:-1)+length)%length);
        }else if(event.key==='Escape'&&(root.classList.contains('is-open')||!panel.hidden)){event.preventDefault();event.stopPropagation();close(true);}
    });
    form.addEventListener('submit',event=>{
        event.preventDefault();if(composition)return;
        const nodes=items();if(active>=0&&!panel.hidden&&loadedQuery===input.value.trim())nodes[active]?.click();else search();
    });
    toggle.addEventListener('click',()=>{if(root.classList.contains('is-open'))close(true);else{root.classList.add('is-open');toggle.setAttribute('aria-expanded','true');input.focus();}});
    clear.addEventListener('click',()=>{input.value='';clear.hidden=true;loadedQuery='';controller?.abort();++version;clearTimeout(timer);idle();input.focus();open();});
    closeButton.addEventListener('click',()=>close(true));
    panel.addEventListener('pointermove',event=>{const link=event.target.closest('.admin-search-result');if(link)select(items().indexOf(link));});
    panel.addEventListener('click',event=>{if(event.target.closest('.admin-search-result'))close();});
    document.addEventListener('pointerdown',event=>{if(!root.contains(event.target)&&event.target!==toggle&&!toggle.contains(event.target))close();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&root.contains(document.activeElement)){close(true);}});
    root.addEventListener('focusout',event=>{if(event.relatedTarget&&!root.contains(event.relatedTarget)&&event.relatedTarget!==toggle)close();});
    window.addEventListener('resize',()=>{if(!panel.hidden)position();});
    compact.addEventListener('change',()=>close());
    document.addEventListener('scroll',event=>{if(!panel.hidden&&!panel.contains(event.target))position();},{capture:true,passive:true});
    window.addEventListener('pageshow',()=>{if(!panel.hidden)close();});
})();
