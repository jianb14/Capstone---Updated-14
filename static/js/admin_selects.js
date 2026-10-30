/* Shared keyboard and popover behavior for admin table dropdowns. */
(() => {
    'use strict';
    let instance=0;
    window.AdminSelects={create(root){
        const controls=new Map(), namespace=++instance;
        let sequence=0, active;
        function enhanceSelect(select){
            if(controls.has(select))return;
            const wrap=document.createElement('div');wrap.className='ac-select';select.before(wrap);wrap.append(select);
            const trigger=document.createElement('button');trigger.type='button';trigger.className='ac-select-trigger';
            trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
            const name=select.getAttribute('aria-label') || 'Rows per page', text=document.createElement('span');
            const menu=document.createElement('div');menu.className='ac-select-menu';menu.hidden=true;
            menu.setAttribute('role','listbox');menu.setAttribute('aria-label',name);menu.id=`admin-select-${namespace}-${++sequence}`;
            trigger.setAttribute('aria-controls',menu.id);trigger.append(text);
            trigger.insertAdjacentHTML('beforeend','<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>');
            const usesPopover=typeof menu.showPopover==='function';
            if(usesPopover)menu.setAttribute('popover','manual');
            const choices=[...select.options].map(option=>{
                const button=document.createElement('button');button.type='button';button.setAttribute('role','option');
                button.textContent=option.text;button.dataset.value=option.value;button.disabled=option.disabled;
                button.addEventListener('click',()=>{select.value=option.value;sync();close();trigger.focus();select.dispatchEvent(new Event('change',{bubbles:true}));});
                menu.append(button);return button;
            });
            function sync(){
                text.textContent=select.selectedOptions[0]?.text || '';
                trigger.disabled=select.disabled;
                for(const attr of ['aria-invalid','aria-describedby']){
                    if(select.hasAttribute(attr))trigger.setAttribute(attr,select.getAttribute(attr));else trigger.removeAttribute(attr);
                }
                trigger.setAttribute('aria-label',`${name}: ${text.textContent}`);
                choices.forEach(button=>button.setAttribute('aria-selected',String(button.dataset.value===select.value)));
            }
            function close(){
                if(usesPopover && menu.matches(':popover-open'))menu.hidePopover();
                menu.hidden=true;trigger.setAttribute('aria-expanded','false');
                if(active?.wrap===wrap)active=null;
            }
            function open(last=false){
                active?.close();active={wrap,menu,close,trigger,anchor:trigger.getBoundingClientRect()};menu.hidden=false;
                if(usesPopover){
                    const box=trigger.getBoundingClientRect(), edge=12, gap=6, availableWidth=Math.max(1,innerWidth-edge*2);
                    // Measure actual labels before sizing, including wrapped options on small screens.
                    menu.style.visibility='hidden';menu.style.width='max-content';menu.style.maxWidth=`${availableWidth}px`;
                    menu.style.maxHeight='none';menu.style.left='0';menu.style.top='0';
                    menu.showPopover();
                    const width=Math.min(availableWidth,Math.max(box.width,130,Math.ceil(menu.getBoundingClientRect().width)));
                    menu.style.width=`${width}px`;
                    const desired=Math.min(256,Math.ceil(menu.getBoundingClientRect().height));
                    const below=innerHeight-box.bottom-edge-gap, above=box.top-edge-gap, up=below<desired && above>below;
                    menu.style.maxHeight=`${Math.min(desired,Math.max(1,up?above:below))}px`;
                    const height=menu.getBoundingClientRect().height;
                    menu.style.left=`${Math.max(edge,Math.min(box.left,innerWidth-width-edge))}px`;
                    menu.style.top=`${up?Math.max(edge,box.top-height-gap):box.bottom+gap}px`;
                    menu.style.visibility='';
                }
                trigger.setAttribute('aria-expanded','true');
                const enabled=choices.filter(button=>!button.disabled);
                // Opening a filter after scrolling must not scroll the document
                // again and immediately dismiss the newly opened popover.
                (last?enabled.at(-1):enabled.find(button=>button.dataset.value===select.value)||enabled[0])?.focus({preventScroll:true});
            }
            trigger.addEventListener('click',()=>menu.hidden?open():close());
            trigger.addEventListener('keydown',event=>{if(['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();open(event.key==='ArrowUp');}});
            menu.addEventListener('keydown',event=>{
                const enabled=choices.filter(button=>!button.disabled), index=enabled.indexOf(document.activeElement);
                if(['ArrowUp','ArrowDown','Home','End'].includes(event.key)){
                    event.preventDefault();enabled[event.key==='Home'?0:event.key==='End'?enabled.length-1:(index+(event.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length]?.focus();
                }else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();trigger.focus();}
                else if(event.key==='Tab')close();
            });
            wrap.addEventListener('focusout',event=>{if(event.relatedTarget && !wrap.contains(event.relatedTarget))close();});
            wrap.append(trigger,menu);select.hidden=true;controls.set(select,{sync,close});sync();
        }
        const close=()=>active?.close();
        const outside=event=>{if(active && !event.composedPath().includes(active.wrap))close();};
        const scroll=event=>{
            if(!active || event.target===active.menu || active.menu.contains(event.target))return;
            // A scroll queued before the opening click may arrive afterward.
            // Dismiss only if the trigger actually moved from its anchor.
            const box=active.trigger.getBoundingClientRect();
            if(Math.abs(box.top-active.anchor.top)>.5 || Math.abs(box.left-active.anchor.left)>.5)close();
        };
        document.addEventListener('click',outside);
        document.addEventListener('scroll',scroll,{capture:true,passive:true});
        window.addEventListener('resize',close);
        return {
            enhance(){root.querySelectorAll('select[data-admin-select],select[data-account-select]').forEach(enhanceSelect);},
            sync(select){if(select)controls.get(select)?.sync();else controls.forEach(control=>control.sync());},
            close,
            release(scope){for(const [select,control] of controls)if(scope.contains(select)){control.close();controls.delete(select);}},
            destroy(){close();controls.clear();document.removeEventListener('click',outside);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',close);}
        };
    }};
})();
