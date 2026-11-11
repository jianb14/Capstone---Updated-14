/* A modal feature tour: only Back/Next advances; application controls stay untouched. */
(() => {
    'use strict';
    const root=document.getElementById('siteGuide'), content=window.SiteGuideContent;
    if (!root || !content || root.dataset.initialized) return;
    root.dataset.initialized='true';
    const home=root.parentNode, panel=root.querySelector('[data-guide-panel]');
    const title=root.querySelector('[data-guide-title]'), text=root.querySelector('[data-guide-text]');
    const progress=root.querySelector('[data-guide-progress]'), label=root.querySelector('[data-guide-label]');
    const next=root.querySelector('[data-guide-next]'), back=root.querySelector('[data-guide-back]');
    const close=root.querySelector('[data-guide-close]'), hole=root.querySelector('[data-guide-hole]');
    const outline=root.querySelector('[data-guide-outline]'), shade=root.querySelector('[data-guide-shade]'), copy=root.querySelector('.site-guide-copy');
    const motion=matchMedia('(prefers-reduced-motion: reduce)');
    let steps=[], index=0, target, scope, launcher, frame=0, savedOverflow, savedInert;
    let closing=false, closeGeneration=0, closingRestore=true;
    const page=()=>document.querySelector('[data-account-page]')?.dataset.accountPage || root.dataset.guidePage;

    function visible(element) {
        if (!element?.isConnected || !element.getClientRects().length || element.closest('[hidden],[aria-hidden="true"],[inert]')) return false;
        const rect=element.getBoundingClientRect();
        if (!rect.width || !rect.height) return false;
        return element.checkVisibility ? element.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})
            : getComputedStyle(element).visibility!=='hidden';
    }
    function context() {
        return [...document.querySelectorAll('dialog[open],[role="dialog"][aria-modal="true"],#bookingModalOverlay,#editBookingModal')]
            .filter(element=>!root.contains(element) && visible(element)).at(-1) || document;
    }
    function clearTarget() {
        if (!target) return;
        target.removeAttribute('data-site-guide-target');
        const ids=(target.getAttribute('aria-describedby') || '').split(/\s+/).filter(id=>id && id!=='siteGuideText');
        if (ids.length) target.setAttribute('aria-describedby',ids.join(' ')); else target.removeAttribute('aria-describedby');
        target=null;
    }
    function finishHide(restore) {
        if (!root.open) return;
        closeGeneration++;closing=false;
        root.getAnimations({subtree:true}).forEach(animation=>animation.cancel());
        observer.disconnect();resize.disconnect();cancelAnimationFrame(frame);frame=0;
        clearTarget();root.close();panel.hidden=true;
        root.removeAttribute('data-closing');root.removeAttribute('data-tracking');
        if (root.parentNode!==home) home.append(root);
        root.inert=Boolean(savedInert && scope instanceof Element && visible(scope));
        if (savedOverflow?.value) document.body.style.setProperty('overflow',savedOverflow.value,savedOverflow.priority);
        else document.body.style.removeProperty('overflow');
        document.documentElement.removeAttribute('data-site-guide-active');
        launcher?.setAttribute('aria-expanded','false');
        if (restore && visible(launcher)) launcher.focus({preventScroll:true});
        launcher=null;scope=null;steps=[];savedOverflow=null;
    }
    function hide(restore=true,animated=true) {
        if (!root.open) return;
        if (!animated || motion.matches) {finishHide(restore);return;}
        if (closing) return;
        closing=true;closingRestore=restore;
        const generation=++closeGeneration;
        const opacity=[getComputedStyle(shade).opacity,getComputedStyle(panel).opacity];
        root.getAnimations({subtree:true}).forEach(animation=>animation.cancel());
        root.setAttribute('data-closing','');
        const exits=[shade,panel].map((element,i)=>element.animate([{opacity:opacity[i]},{opacity:0}],{duration:140,easing:'ease-out',fill:'forwards'}));
        Promise.allSettled(exits.map(animation=>animation.finished)).then(()=>{
            if (generation===closeGeneration && closing) finishHide(restore);
        });
    }
    function visibleRect(element) {
        const view=window.visualViewport;
        const left=view?.offsetLeft || 0, top=view?.offsetTop || 0;
        let rect=element.getBoundingClientRect();
        let area={left:Math.max(left+6,rect.left-5),top:Math.max(top+6,rect.top-5),right:Math.min(left+(view?.width || innerWidth)-6,rect.right+5),bottom:Math.min(top+(view?.height || innerHeight)-6,rect.bottom+5)};
        for (let parent=element.parentElement;parent && parent!==document.body;parent=parent.parentElement) {
            const style=getComputedStyle(parent), bounds=parent.getBoundingClientRect();
            if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) { area.top=Math.max(area.top,bounds.top);area.bottom=Math.min(area.bottom,bounds.bottom); }
            if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) { area.left=Math.max(area.left,bounds.left);area.right=Math.min(area.right,bounds.right); }
        }
        return {...area,width:Math.max(0,area.right-area.left),height:Math.max(0,area.bottom-area.top)};
    }
    function position() {
        frame=0;
        if (!root.open) return;
        if (!visible(target) || context()!==scope) { hide(false,false);return; }
        if (closing) return;
        const view=window.visualViewport, left=(view?.offsetLeft || 0)+12, top=(view?.offsetTop || 0)+12;
        const right=left+(view?.width || innerWidth)-24, bottom=top+(view?.height || innerHeight)-24;
        const rect=visibleRect(target);
        for (const [name,value] of Object.entries({x:rect.left,y:rect.top,width:rect.width,height:rect.height})) hole.setAttribute(name,String(value));
        Object.assign(outline.style,{transform:`translate3d(${rect.left}px,${rect.top}px,0)`,width:rect.width+'px',height:rect.height+'px'});
        panel.style.maxWidth=Math.max(100,right-left)+'px';panel.style.maxHeight=Math.max(100,bottom-top)+'px';
        const card=panel.getBoundingClientRect(), gap=14;
        const anchoredX=Math.max(left,Math.min(rect.left,right-card.width));
        const candidates=[[rect.right+gap,rect.top],[rect.left-card.width-gap,rect.top],
            [anchoredX,rect.bottom+gap],[anchoredX,rect.top-card.height-gap],
            [right-card.width,bottom-card.height],[left,top]];
        const overlaps=(x,y)=>x<rect.right && x+card.width>rect.left && y<rect.bottom && y+card.height>rect.top;
        const point=candidates.find(([x,y])=>x>=left && y>=top && x+card.width<=right && y+card.height<=bottom && !overlaps(x,y));
        const [x,y]=point || [Math.max(left,Math.min(rect.left,right-card.width)),Math.max(top,bottom-card.height)];
        panel.style.transform=`translate3d(${Math.round(x)}px,${Math.round(y)}px,0)`;
    }
    function schedule(tracking=false) {
        if (!root.open) return;
        if (tracking) root.setAttribute('data-tracking','');
        if (!frame) frame=requestAnimationFrame(position);
    }
    function showStep(animated=true) {
        root.toggleAttribute('data-tracking',!animated || motion.matches);
        clearTarget();target=steps[index].element;
        target.setAttribute('data-site-guide-target','');
        const ids=new Set((target.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
        ids.add('siteGuideText');target.setAttribute('aria-describedby',[...ids].join(' '));
        title.textContent=steps[index].title;text.textContent=steps[index].text;
        progress.textContent=`${index+1} of ${steps.length}`;
        back.disabled=index===0;next.textContent=index===steps.length-1 ? 'Done' : 'Next';
        const rect=visibleRect(target), whole=target.getBoundingClientRect();
        if (!rect.width || !rect.height || whole.top<80 || whole.bottom>innerHeight-30 || rect.height<Math.min(whole.height,180)) {
            target.scrollIntoView({block:'center',inline:'nearest',behavior:motion.matches ? 'instant' : 'smooth'});
        }
        resize.disconnect();resize.observe(target);resize.observe(panel);
        position();
        copy.getAnimations().forEach(animation=>animation.cancel());
        if (animated && !motion.matches) copy.animate([{opacity:.35,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],{duration:180,easing:'cubic-bezier(.22,1,.36,1)'});
        if (back.disabled && document.activeElement===back) next.focus({preventScroll:true});
    }
    function advance(direction) {
        if (closing) return;
        const current=steps[index];steps=steps.filter(step=>visible(step.element));
        const currentIndex=steps.indexOf(current);
        if (currentIndex<0) { hide();return; }
        if (direction>0 && currentIndex===steps.length-1) { hide();return; }
        index=Math.max(0,Math.min(currentIndex+direction,steps.length-1));showStep();
    }
    function enhanceDialogs() {
        const source=document.querySelector('[data-site-guide-start]');
        if (!source || !content.feature(page())) return;
        document.querySelectorAll('dialog,[role="dialog"][aria-modal="true"],#editBookingModal').forEach(dialog=>{
            if (root.contains(dialog) || dialog.querySelector('[data-site-guide-start]') || !content.getSteps(page(),dialog,element=>Boolean(element.getClientRects().length || dialog.contains(element))).length) return;
            const header=dialog.querySelector('header,.modal-header,.cp-modal-header,.modal-head');
            const button=source.cloneNode(true);button.className='site-guide-launch site-guide-dialog-launch';button.hidden=false;
            button.setAttribute('aria-expanded','false');
            if (header) {
                header.classList.add('site-guide-dialog-head');
                header.insertBefore(button,header.lastElementChild?.tagName==='BUTTON' ? header.lastElementChild : null);
            } else {
                const tools=document.createElement('div');tools.className='site-guide-dialog-tools';tools.append(button);dialog.insertBefore(tools,dialog.firstChild);
            }
        });
    }
    function start(button) {
        if (root.open) return;
        const tools=button.closest('#mobileCanvasToolsDialog');
        if (tools) tools.querySelector('[data-mobile-close]')?.click();
        scope=context();steps=content.getSteps(page(),scope,visible);
        if (!steps.length) { scope=null;return; }
        index=0;launcher=button;savedInert=root.inert;closing=false;closeGeneration++;
        savedOverflow={value:document.body.style.getPropertyValue('overflow'),priority:document.body.style.getPropertyPriority('overflow')};
        if (scope!==document) scope.append(root);
        root.inert=false;panel.hidden=false;
        document.body.style.setProperty('overflow','hidden');
        launcher.setAttribute('aria-expanded','true');
        document.documentElement.setAttribute('data-site-guide-active','');
        label.textContent={booking:'Booking guide',canvas:'Canvas guide',payments:'Payments guide'}[content.feature(page())] || 'Feature guide';
        root.showModal();showStep(false);next.focus({preventScroll:true});
        if (!motion.matches) {
            shade.animate([{opacity:0},{opacity:1}],{duration:180,easing:'ease-out'});
            panel.animate([{opacity:0},{opacity:1}],{duration:200,easing:'ease-out'});
        }
        observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','style','hidden','open','aria-hidden']});
    }
    const observer=new MutationObserver(changes=>{if (changes.some(change=>!root.contains(change.target))) schedule();});
    const resize=new ResizeObserver(()=>schedule());
    document.addEventListener('click',event=>{
        const button=event.target.closest('[data-site-guide-start]');
        if (button && !root.contains(button)) { event.preventDefault();start(button); }
    });
    next.addEventListener('click',()=>advance(1));back.addEventListener('click',()=>advance(-1));
    close.addEventListener('click',()=>hide());
    root.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();hide();});
    document.addEventListener('keydown',event=>{
        if (!root.open) return;
        // Native modal focus does not suppress application document shortcuts.
        event.stopImmediatePropagation();
        if (event.key==='Escape') {event.preventDefault();event.stopImmediatePropagation();hide();}
        if (event.key==='Tab') {
            const buttons=[close,back,next].filter(button=>!button.disabled);
            const offset=buttons.indexOf(document.activeElement), direction=event.shiftKey ? -1 : 1;
            event.preventDefault();event.stopImmediatePropagation();
            buttons[(offset+direction+buttons.length)%buttons.length].focus({preventScroll:true});
        }
    },true);
    // Existing keyup handlers may still release a pan key held before the tour.
    document.addEventListener('scroll',()=>schedule(true),{capture:true,passive:true});
    window.addEventListener('resize',()=>schedule(true),{passive:true});
    window.visualViewport?.addEventListener('resize',()=>schedule(true),{passive:true});
    window.visualViewport?.addEventListener('scroll',()=>schedule(true),{passive:true});
    document.addEventListener('account:unmounting',()=>hide(false,false));
    document.addEventListener('account:mounted',enhanceDialogs);
    document.addEventListener('toggle',event=>{if (event.target.tagName==='DIALOG' && event.target!==root) {enhanceDialogs();schedule();}},true);
    window.addEventListener('pagehide',()=>hide(false,false));window.addEventListener('popstate',()=>hide(false,false));
    motion.addEventListener('change',()=>{
        if (!motion.matches || !root.open) return;
        if (closing) {hide(closingRestore,false);return;}
        root.getAnimations({subtree:true}).forEach(animation=>animation.cancel());schedule(true);
    });
    document.documentElement.setAttribute('data-site-guide-ready','');enhanceDialogs();
})();
