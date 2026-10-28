/* The same restrained entrance used by reviews, including async table replacements. */
['my_profile','customer_profile','my_payments','report_concern'].forEach(page=>AccountPages.register(page,'account-motion',scope=>{
    if (!window.IntersectionObserver || !Element.prototype.animate) return;
    const reduced=matchMedia('(prefers-reduced-motion:reduce)'), seen=new WeakSet(), running=new Map();
    const finish=element=>{ running.get(element)?.cancel(); running.delete(element); };
    const observer=new IntersectionObserver(entries=>{
        entries.filter(entry=>entry.isIntersecting && entry.target.getClientRects().length)
            .sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top || a.boundingClientRect.left-b.boundingClientRect.left)
            .forEach((entry,index)=>{
                const element=entry.target; observer.unobserve(element);
                if (reduced.matches || !element.isConnected) return;
                const animation=element.animate([{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],
                    {id:'account-entry',duration:480,delay:Math.min(index*45,225),easing:'cubic-bezier(.22,1,.36,1)',fill:'backwards'});
                running.set(element,animation); animation.onfinish=()=>finish(element);
            });
    },{threshold:.01,rootMargin:'0px 0px 32px 0px'});
    function register() {
        running.forEach((_,element)=>{ if (!element.isConnected) finish(element); });
        scope.root.querySelectorAll('.account-page-header,.account-kpi,.my-profile-header,.profile-section,.account-toolbar,.account-table-wrap,.account-table-footer,.concern-panel-heading,.concern-form,.account-empty-state,.cp-tabs,.cp-panel-head').forEach(element=>{
            if (seen.has(element)) return; seen.add(element); if (!reduced.matches) observer.observe(element);
        });
    }
    register(); const mutation=new MutationObserver(register); mutation.observe(scope.root,{childList:true,subtree:true});
    const settle=event=>{ let element=event.target; while(element && element!==scope.root) { finish(element); element=element.parentElement; } };
    AccountPages.listen(scope.root,'pointerdown',settle,true); AccountPages.listen(scope.root,'focusin',settle,true);
    AccountPages.listen(reduced,'change',()=>{ if (reduced.matches) { observer.disconnect(); running.forEach((_,element)=>finish(element)); } });
    scope.cleanup(()=>{ mutation.disconnect(); observer.disconnect(); running.forEach(animation=>animation.cancel()); });
},20));
