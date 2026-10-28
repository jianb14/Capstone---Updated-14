/* Forms inside the account workspace keep their validation and submit over fetch. */
['my_profile','customer_profile'].forEach(page=>AccountPages.register(page,'account-forms',scope=>{
    const pending=new Set(), busy=new WeakSet();
    scope.ready(()=>{
        scope.root.addEventListener('submit',async event=>{
            const form=event.target;
            if (event.defaultPrevented || !form.matches('#editProfileForm,#editBookingForm,#deleteBookingForm,#reviewForm,.change-action-form')) return;
            event.preventDefault();
            if (busy.has(form)) return;
            if (!form.checkValidity()) { form.reportValidity(); return; }
            let feedback=form.querySelector('[data-account-form-message]');
            if (!feedback) {
                feedback=document.createElement('p'); feedback.className='account-form-message';
                feedback.dataset.accountFormMessage=''; feedback.setAttribute('role','alert'); feedback.tabIndex=-1;
                form.prepend(feedback);
            }
            feedback.hidden=true;
            if (form.dataset.changeMode==='1' && form.elements.namedItem('change_reason').value.trim().length<10) {
                feedback.textContent='Please reopen Request Changes and provide a reason before submitting.';
                feedback.hidden=false; feedback.focus(); return;
            }
            const data=new FormData(form), controller=new AbortController();
            const submit=event.submitter || form.querySelector('[type="submit"]');
            const label=submit?.textContent;
            const controls=[...form.querySelectorAll('input,select,textarea,button[type="submit"]')].map(control=>[control,control.disabled]);
            controls.forEach(([control])=>control.disabled=true);
            if (submit) submit.textContent='Saving…';
            form.setAttribute('aria-busy','true'); busy.add(form); pending.add(controller);
            const timeout=setTimeout(()=>controller.abort(),45000);
            try {
                const response=await fetch(form.action,{method:'POST',body:data,credentials:'same-origin',signal:controller.signal,
                    headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
                if (!scope.active) return;
                if (response.redirected) throw new Error('Your session may have expired. Sign in again in another tab, then retry. Your details are still here.');
                const result=await response.json().catch(()=>({}));
                if (!scope.active) return;
                if (!response.ok || !(result.success || result.status==='success')) {
                    Object.entries(result.errors || {}).forEach(([name,errors])=>{
                        const input=form.elements.namedItem(name);
                        if (input && page==='my_profile') window.profileFieldError?.(input,Array.isArray(errors)?errors.join(' '):String(errors));
                    });
                    throw new Error(result.message || result.error || 'We could not save this request. Your details are still here.');
                }
                const target=result.redirect_url || result.redirect || location.href;
                const scroll=[scrollX,scrollY];
                await window.AccountNavigation.navigate(target,{force:true,replace:true,scroll});
                window.AppToast?.fire({icon:'success',title:result.message || 'Saved successfully.'});
            } catch(error) {
                if (!scope.active) return;
                feedback.textContent=error.name==='AbortError' || error instanceof TypeError
                    ? 'We could not confirm the result. Check your connection and your list before trying again. Your details are still here.' : error.message;
                feedback.hidden=false; feedback.focus();
            } finally {
                clearTimeout(timeout); pending.delete(controller); busy.delete(form);
                controls.forEach(([control,disabled])=>control.disabled=disabled);
                if (submit) submit.textContent=label;
                form.removeAttribute('aria-busy');
            }
        });
    });
    scope.cleanup(()=>pending.forEach(controller=>controller.abort()));
},30));
