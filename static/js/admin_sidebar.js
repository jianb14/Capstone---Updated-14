/* Sidebar state is local UI state; collapsing never navigates or fetches a page. */
(() => {
    'use strict';
    const root=document.documentElement, key='balloorina-admin-sidebar';
    const readPreference=()=>{try{return localStorage.getItem(key)==='collapsed';}catch{return false;}};
    let collapsed=readPreference();
    root.dataset.sidebarState=collapsed?'collapsed':'expanded';

    function mount(){
        const sidebar=document.querySelector('[data-admin-sidebar]');
        if(!sidebar || sidebar.dataset.ready)return;
        sidebar.dataset.ready='true';
        const menu=sidebar.querySelector('.sidebar-nav-menu'), collapse=sidebar.querySelector('[data-sidebar-collapse]');
        const trigger=document.querySelector('[data-sidebar-mobile-toggle]'), overlay=document.querySelector('.sidebar-overlay');
        const mobile=matchMedia('(max-width:1024px)'), reduced=matchMedia('(prefers-reduced-motion:reduce)');
        const tooltip=document.createElement('div');
        tooltip.id='adminSidebarTooltip';tooltip.className='admin-sidebar-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;
        const popover=typeof tooltip.showPopover==='function';
        if(popover)tooltip.setAttribute('popover','manual');
        document.body.append(tooltip);
        let tooltipTarget, hideTimer, mobileOpen=false;

        function hideTooltip(){
            clearTimeout(hideTimer);
            tooltipTarget?.removeAttribute('aria-describedby');tooltipTarget=null;
            if(popover && tooltip.matches(':popover-open'))tooltip.hidePopover();
            tooltip.hidden=true;
        }
        function tooltipText(target){
            return target===collapse?collapse.getAttribute('aria-label'):target.querySelector('span:not(.nav-count-badge)')?.textContent.trim();
        }
        function showTooltip(target){
            clearTimeout(hideTimer);
            if(mobile.matches || (target!==collapse && !collapsed))return;
            const text=tooltipText(target);
            if(!text)return;
            if(tooltipTarget!==target)hideTooltip();
            tooltipTarget=target;tooltip.replaceChildren(document.createTextNode(text));
            const count=target.querySelector('.nav-count-badge')?.textContent.trim();
            if(count){const badge=document.createElement('span');badge.className='admin-sidebar-tooltip-count';badge.textContent=count;tooltip.append(badge);}
            target.setAttribute('aria-describedby',tooltip.id);
            tooltip.hidden=false;tooltip.style.visibility='hidden';
            if(popover && !tooltip.matches(':popover-open'))tooltip.showPopover();
            const bounds=target.getBoundingClientRect(), box=tooltip.getBoundingClientRect();
            const top=Math.max(8,Math.min(bounds.top+(bounds.height-box.height)/2,innerHeight-box.height-8));
            tooltip.style.left=`${Math.min(sidebar.getBoundingClientRect().right+10,innerWidth-box.width-12)}px`;
            tooltip.style.top=`${top}px`;
            tooltip.style.setProperty('--as-tooltip-arrow-y',`${Math.max(10,Math.min(bounds.top+bounds.height/2-top,box.height-10))}px`);
            tooltip.style.visibility='';
        }
        const delayHide=()=>{clearTimeout(hideTimer);hideTimer=setTimeout(hideTooltip,100);};
        function sidebarTarget(node){return node instanceof Element?node.closest('.sidebar-nav-menu a,.admin-sidebar-footer a,[data-sidebar-collapse]'):null;}
        sidebar.addEventListener('pointerover',event=>{if(event.pointerType!=='touch'){const target=sidebarTarget(event.target);if(target)showTooltip(target);}});
        sidebar.addEventListener('pointerout',event=>{if(tooltipTarget && !tooltipTarget.contains(event.relatedTarget) && !tooltip.contains(event.relatedTarget))delayHide();});
        sidebar.addEventListener('focusin',event=>{const target=sidebarTarget(event.target);if(target)showTooltip(target);});
        sidebar.addEventListener('focusout',event=>{if(!sidebar.contains(event.relatedTarget))hideTooltip();});
        tooltip.addEventListener('pointerenter',()=>clearTimeout(hideTimer));tooltip.addEventListener('pointerleave',delayHide);
        function repositionTooltip(){
            const target=tooltipTarget;
            if(!target)return;
            requestAnimationFrame(()=>{
                if(tooltipTarget!==target)return;
                const bounds=target.getBoundingClientRect(), clip=menu?.getBoundingClientRect();
                const outside=menu?.contains(target) && (bounds.bottom<=clip.top || bounds.top>=clip.bottom);
                if(outside || (!target.matches(':hover') && document.activeElement!==target && !tooltip.matches(':hover')))hideTooltip();
                else showTooltip(target);
            });
        }
        document.addEventListener('scroll',repositionTooltip,{capture:true,passive:true});
        window.addEventListener('resize',repositionTooltip);
        const counts=new MutationObserver(()=>{if(tooltipTarget)showTooltip(tooltipTarget);});
        counts.observe(sidebar,{childList:true,subtree:true,characterData:true});

        function ensureActiveVisible(){
            const current=menu?.querySelector('a.active');
            if(!current)return;
            const item=current.getBoundingClientRect(), bounds=menu.getBoundingClientRect();
            if(item.top<bounds.top)menu.scrollTop-=bounds.top-item.top+8;
            else if(item.bottom>bounds.bottom)menu.scrollTop+=item.bottom-bounds.bottom+8;
        }
        function applyPreference(){
            hideTooltip();root.dataset.sidebarState=collapsed?'collapsed':'expanded';
            if(collapse){collapse.setAttribute('aria-expanded',String(!collapsed));collapse.setAttribute('aria-label',collapsed?'Expand sidebar':'Collapse sidebar');}
            if(reduced.matches)requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
        }
        collapse?.addEventListener('click',()=>{
            collapsed=!collapsed;applyPreference();
            try{localStorage.setItem(key,collapsed?'collapsed':'expanded');}catch{/* Storage may be disabled. */}
        });
        sidebar.addEventListener('transitionend',event=>{
            if(event.target===sidebar && event.propertyName==='width'){
                if(!menu?.matches(':hover') && !menu?.contains(document.activeElement))ensureActiveVisible();
                window.dispatchEvent(new Event('resize'));
            }
        });
        window.addEventListener('storage',event=>{if(event.key===key){collapsed=event.newValue==='collapsed';applyPreference();}});

        function setMobile(open,restoreFocus=true){
            mobileOpen=Boolean(open && mobile.matches);hideTooltip();
            sidebar.classList.toggle('mobile-open',mobileOpen);overlay?.classList.toggle('active',mobileOpen);
            document.body.classList.toggle('admin-sidebar-open',mobileOpen);
            trigger?.setAttribute('aria-expanded',String(mobileOpen));
            sidebar.inert=mobile.matches && !mobileOpen;
            if(mobile.matches)sidebar.setAttribute('aria-hidden',String(!mobileOpen));else sidebar.removeAttribute('aria-hidden');
            if(mobileOpen){sidebar.querySelector('.admin-sidebar-mobile-close')?.focus({preventScroll:true});ensureActiveVisible();}
            else if(restoreFocus && mobile.matches)trigger?.focus({preventScroll:true});
        }
        trigger?.addEventListener('click',()=>setMobile(!mobileOpen));
        sidebar.querySelectorAll('[data-sidebar-dismiss]').forEach(button=>button.addEventListener('click',()=>setMobile(false)));
        overlay?.addEventListener('click',()=>setMobile(false));
        sidebar.querySelectorAll('a').forEach(link=>{
            link.addEventListener('click',()=>{
                hideTooltip();if(mobile.matches)setMobile(false,false);
                try{sessionStorage.setItem('balloorina-admin-menu-scroll',String(menu?.scrollTop || 0));}catch{/* Optional preference. */}
            });
            link.querySelector('svg')?.setAttribute('aria-hidden','true');
        });
        document.addEventListener('keydown',event=>{
            if(event.key==='Escape'){
                if(mobileOpen){event.preventDefault();setMobile(false);}else if(!tooltip.hidden){event.preventDefault();hideTooltip();}
            }
            if(event.key==='Tab' && mobileOpen){
                const items=[...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(item=>item.getClientRects().length);
                const first=items[0], last=items.at(-1);
                if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
                else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
            }
        });
        document.addEventListener('focusin',event=>{
            if(mobileOpen && !sidebar.contains(event.target))sidebar.querySelector('.admin-sidebar-mobile-close')?.focus({preventScroll:true});
        });
        mobile.addEventListener('change',()=>{
            const focused=sidebar.contains(document.activeElement);setMobile(false,focused);applyPreference();
            if(focused && !mobile.matches)collapse?.focus({preventScroll:true});
            requestAnimationFrame(ensureActiveVisible);
        });
        window.addEventListener('pagehide',()=>setMobile(false,false));
        window.addEventListener('pageshow',()=>{collapsed=readPreference();applyPreference();});
        document.addEventListener('visibilitychange',()=>{if(document.hidden)hideTooltip();});

        // Keep the current navigation group selected for detail/editor URLs too.
        const links=[...sidebar.querySelectorAll('.sidebar-nav-menu a,.admin-sidebar-footer a:not(.admin-sidebar-logout)')];
        const matches=links.filter(link=>{const path=new URL(link.href,location.href).pathname;return location.pathname===path || (path.endsWith('/') && location.pathname.startsWith(path));});
        const selected=links.find(link=>link.classList.contains('active')) || matches.sort((a,b)=>new URL(b.href).pathname.length-new URL(a.href).pathname.length)[0];
        if(selected){links.forEach(link=>link.classList.toggle('active',link===selected));}
        links.forEach(link=>{if(link.classList.contains('active'))link.setAttribute('aria-current','page');});
        try{const saved=Number(sessionStorage.getItem('balloorina-admin-menu-scroll'));if(menu && Number.isFinite(saved))menu.scrollTop=saved;}catch{/* Optional preference. */}
        applyPreference();setMobile(false,false);requestAnimationFrame(ensureActiveVisible);
        // Compatibility with existing templates that call these mobile helpers.
        window.toggleMobileSidebar=()=>setMobile(!mobileOpen);
        window.closeMobileSidebar=()=>setMobile(false);
    }
    window.AdminSidebar={mount};
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
