AccountPages.register('my_profile','password-otp',scope=>{
    const dialog=document.getElementById('profilePasswordOtpDialog');
    const form=document.getElementById('profilePasswordOtpForm');
    if (!dialog || !form) return;
    const code=document.getElementById('profileOtpCode'), feedback=document.getElementById('profileOtpFeedback');
    const submit=document.getElementById('profileOtpSubmit'), resend=document.getElementById('profileOtpResend');
    let request, generation=0, busy=false, finalizing=false, ready=false, resendUntil=0, verifyUntil=0, previousOverflow=null;
    const active=id=>scope.active && dialog.open && generation===id;
    const remaining=until=>Math.max(0,Math.ceil((until-Date.now())/1000));
    function message(text) { feedback.textContent=text; feedback.hidden=!text; }
    function buttons() {
        const wait=remaining(verifyUntil), send=remaining(resendUntil);
        submit.disabled=busy || !ready || wait>0;
        submit.textContent=busy?'Please wait…':wait?`Try again in ${wait}s`:'Verify & change password';
        resend.disabled=busy || !ready || send>0;
        resend.textContent=send?`Resend code in ${send}s`:'Resend code';
        dialog.querySelectorAll('[data-profile-otp-close]').forEach(button=>button.disabled=finalizing);
    }
    async function run(action) {
        const id=generation;
        request?.abort(); request=new AbortController();
        const data=new FormData(form); if (action) data.set('action',action);
        busy=true; finalizing=action==='verify'; message(''); buttons();
        const controller=request, timeout=setTimeout(()=>controller.abort(),30000);
        try {
            const response=await fetch(dialog.dataset.endpoint,{method:action?'POST':'GET',body:action?data:undefined,
                credentials:'same-origin',cache:'no-store',signal:controller.signal,
                headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
            const result=await response.json().catch(()=>({}));
            if (!active(id)) return;
            if (result.resend_wait!==undefined) resendUntil=Date.now()+result.resend_wait*1000;
            if (result.verify_wait!==undefined) verifyUntil=Date.now()+result.verify_wait*1000;
            if (!response.ok || !result.success) {
                if (result.restart) { ready=false; scope.root.querySelector('.profile-dialog__resume').hidden=true; }
                throw new Error(result.message || 'We could not confirm this request. Please try again.');
            }
            if (result.verified) {
                close();
                await AccountNavigation.navigate(result.redirect_url,{force:true,replace:true,scroll:[scrollX,scrollY]});
                window.AppToast?.fire({icon:'success',title:result.message}); return;
            }
            ready=true;
            dialog.querySelector('[data-profile-otp-email]').textContent=result.masked_email;
            if (action==='resend') code.value='';
            message(result.message || ''); code.focus();
        } catch(error) {
            if (active(id)) { message(error.name==='AbortError'?'Connection interrupted. Please try again.':error.message); feedback.focus(); }
        } finally { clearTimeout(timeout); if (active(id)) { busy=false; finalizing=false; buttons(); } }
    }
    function open() {
        if (dialog.open) return;
        window.closePasswordModal?.();
        generation++; form.reset(); ready=false; busy=false; message('');
        scope.root.querySelector('.profile-dialog__resume').hidden=false;
        if (previousOverflow===null) previousOverflow=document.body.style.overflow;
        document.body.style.overflow='hidden'; dialog.showModal(); run();
    }
    function restore() {
        if (dialog.open) return;
        generation++; request?.abort(); busy=false; finalizing=false; ready=false; form.reset();
        if (previousOverflow!==null && !document.querySelector('.profile-dialog[open]')) document.body.style.overflow=previousOverflow;
        previousOverflow=null;
    }
    function close() { dialog.close(); restore(); }
    form.addEventListener('submit',event=>{
        event.preventDefault(); if (busy || !ready || remaining(verifyUntil)) return;
        if (!/^\d{6}$/.test(code.value.trim())) { message('Enter the 6-digit code from your email.'); code.focus(); return; }
        run('verify');
    });
    resend.addEventListener('click',()=>{ if (!busy && ready && !remaining(resendUntil)) run('resend'); });
    dialog.querySelectorAll('[data-profile-otp-close]').forEach(button=>button.addEventListener('click',close));
    dialog.addEventListener('cancel',event=>{ if (finalizing) event.preventDefault(); });
    dialog.addEventListener('close',restore);
    scope.root.querySelectorAll('[data-password-resume]').forEach(link=>link.addEventListener('click',event=>{
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();open();
    }));
    const timer=setInterval(()=>{if(dialog.open)buttons();},1000);
    scope.expose({AccountPasswordOTP:{open}});
    scope.cleanup(()=>{clearInterval(timer);request?.abort();if(dialog.open)close();});
},10);
