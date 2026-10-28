AccountPages.register('my_profile','account-deletion',function(scope) {
    'use strict';
    const dialog = document.getElementById('deleteAccountDialog');
    const form = document.getElementById('deleteAccountForm');
    const trigger = document.getElementById('deleteAccountButton');
    if (!dialog || !form || !trigger) return;
    const select = id => document.getElementById(id);
    const submit = select('deletionSubmit'), feedback = select('deletionFeedback');
    const password = select('deletionPassword'), code = select('deletionCode');
    const resend = select('deletionResend'), acknowledgement = select('deletionAcknowledge');
    let phase = 'loading', busy = false, finalizing = false, request;
    let previousOverflow = null, resendUntil = 0, verifyUntil = 0, cycle = 0;
    const active = opened => scope.active && dialog.open && opened === cycle;
    const remaining = until => Math.max(0,Math.ceil((until-Date.now())/1000));
    function message(text,error=false) {
        feedback.textContent = text; feedback.hidden = !text;
        feedback.classList.toggle('is-error',error);
        feedback.setAttribute('role',error ? 'alert' : 'status');
    }
    function buttons() {
        const wait = remaining(verifyUntil);
        submit.disabled = busy || ['loading','blocked','unavailable'].includes(phase) || (phase === 'code' && wait>0);
        submit.textContent = busy ? finalizing ? 'Deleting account…' : 'Please wait…'
            : ({loading:'Checking…',blocked:'Resolve these items first',unavailable:'Verification required',password:'Send verification code',
                code:wait ? `Try again in ${wait}s` : 'Verify code',confirm:'Delete my account',error:'Try again'})[phase];
        submit.classList.toggle('is-destructive',phase === 'confirm');
        const resendWait = remaining(resendUntil);
        resend.disabled = busy || resendWait>0;
        resend.textContent = resendWait ? `Resend code in ${resendWait}s` : 'Resend code';
        dialog.querySelectorAll('[data-delete-close]').forEach(button => button.disabled = finalizing);
    }
    function step(next,focus=true) {
        phase = next;
        select('deletionLoading').hidden = phase !== 'loading';
        select('deletionBlockers').hidden = phase !== 'blocked';
        select('deletionEffects').hidden = !['password','code','confirm','unavailable'].includes(phase);
        select('deletionPasswordStep').hidden = phase !== 'password';
        select('deletionCodeStep').hidden = phase !== 'code';
        select('deletionConfirmStep').hidden = phase !== 'confirm';
        acknowledgement.checked = false;
        buttons();
        if (focus) ({password,code,confirm:acknowledgement,error:submit,blocked:feedback,unavailable:feedback})[phase]?.focus();
    }
    function blockers(items) {
        const list = select('deletionBlockerList'); list.replaceChildren();
        items.forEach(item => {
            const card = document.createElement('div'); card.className = 'deletion-blocker';
            const title = document.createElement('h3'); title.textContent = `${item.title} · ${item.event_type}`;
            const reasons = document.createElement('ul');
            item.reasons.forEach(text => { const row=document.createElement('li'); row.textContent=text; reasons.append(row); });
            const links = document.createElement('div'); links.className = 'deletion-blocker-links';
            [['View booking',item.booking_url],['My payments',item.payments_url]].forEach(([label,url]) => {
                const link = document.createElement('a'); link.textContent = label; link.href = url;
                link.dataset.accountLink = '';
                link.addEventListener('click',event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) dialog.close(); });
                links.append(link);
            });
            card.append(title,reasons,links); list.append(card);
        });
        message('Your account cannot be deleted while these items are unresolved.',true);
        step('blocked');
    }
    async function api(action,opened) {
        request?.abort(); request = new AbortController();
        const payload = new FormData();
        if (action) {
            payload.set('csrfmiddlewaretoken',form.querySelector('[name="csrfmiddlewaretoken"]').value);
            payload.set('action',action);
            if (action === 'request_code') payload.set('password',password.value);
            if (action === 'verify') payload.set('code',code.value.trim());
            if (action === 'confirm') payload.set('acknowledge',acknowledgement.checked ? 'yes' : 'no');
        }
        const controller = request;
        const timeout = setTimeout(() => controller.abort(),30000);
        try {
            const response = await fetch(action ? dialog.dataset.actionUrl : dialog.dataset.statusUrl,{
                method:action ? 'POST' : 'GET',body:action ? payload : undefined,
                credentials:'same-origin',cache:'no-store',signal:controller.signal,
                headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
            });
            if (!active(opened) || request !== controller) return null;
            if (response.redirected || response.status === 401 || response.status === 403) {
                window.location.assign(dialog.dataset.loginUrl);
                throw new Error('Please sign in again.');
            }
            const data = await response.json().catch(() => ({}));
            if (!active(opened) || request !== controller) return null;
            if (!response.ok || !data.success) {
                if (data.blockers) { blockers(data.blockers); return null; }
                if (data.restart) { code.value = ''; password.value = ''; step('password'); }
                if (data.retry_after) {
                    if (action === 'verify') verifyUntil = Date.now()+data.retry_after*1000;
                    else resendUntil = Date.now()+data.retry_after*1000;
                }
                throw new Error(data.message || 'We could not confirm this request. Please try again.');
            }
            return data;
        } finally { clearTimeout(timeout); }
    }
    async function load() {
        const opened = cycle;
        message(''); step('loading',false);
        busy = true; buttons();
        try {
            const data = await api(undefined,opened);
            if (!data) return;
            dialog.querySelectorAll('[data-deletion-email]').forEach(element => element.textContent=data.masked_email);
            resendUntil = Date.now()+(data.resend_wait || 0)*1000;
            if (data.blockers.length) { blockers(data.blockers); return; }
            if (!data.has_password || !data.email_verified) {
                message('A verified account email and a current password are required. Please verify your email before continuing.',true);
                step('unavailable'); return;
            }
            step(data.step);
        } catch (error) {
            if (active(opened)) { message('We could not check your account. Please try again.',true); step('error'); }
        } finally { if (active(opened)) { busy=false; buttons(); } }
    }
    trigger.addEventListener('click',() => {
        if (dialog.open || finalizing) return;
        cycle += 1;
        form.reset(); window.PasswordVisibility?.reset(form);
        if (previousOverflow === null) previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden'; dialog.showModal(); load();
    });
    form.addEventListener('submit',async event => {
        event.preventDefault();
        if (busy) return;
        if (phase === 'error') { load(); return; }
        if (phase === 'password' && !password.value) { message('Enter your current password.',true); password.focus(); return; }
        if (phase === 'code' && !/^\d{6}$/.test(code.value.trim())) { message('Enter the 6-digit code from your email.',true); code.focus(); return; }
        if (phase === 'confirm' && !acknowledgement.checked) { message('Confirm that you understand this action is permanent.',true); acknowledgement.focus(); return; }
        const action = {password:'request_code',code:'verify',confirm:'confirm'}[phase];
        if (!action) return;
        const opened = cycle;
        busy=true; finalizing=action==='confirm'; message(''); buttons();
        try {
            const data = await api(action,opened);
            if (!data) return;
            if (data.deleted) { window.location.replace(data.redirect_url); return; }
            if (data.step === 'code') {
                password.value=''; code.value=''; window.PasswordVisibility?.reset(form);
                resendUntil = Date.now()+(data.resend_wait || 0)*1000;
            }
            if (data.step) step(data.step);
            message(data.message || '');
        } catch (error) {
            if (active(opened)) {
                message(error.name === 'AbortError' || error instanceof TypeError
                    ? finalizing ? 'We could not confirm the result. Try again, or sign in again to check your account.' : 'Connection interrupted. Please try again.' : error.message,true);
                feedback.focus();
            }
        } finally { if (active(opened)) { busy=false; finalizing=false; buttons(); } }
    });
    resend.addEventListener('click',async () => {
        if (busy || remaining(resendUntil)) return;
        const opened = cycle;
        busy=true; message(''); buttons();
        try {
            const data = await api('resend',opened);
            if (data) { code.value=''; resendUntil=Date.now()+data.resend_wait*1000; message(data.message); code.focus(); }
        } catch (error) { if (active(opened)) message(error.message,true); }
        finally { if (active(opened)) { busy=false; buttons(); } }
    });
    dialog.querySelectorAll('[data-delete-close]').forEach(button => button.addEventListener('click',() => { if (!finalizing) dialog.close(); }));
    dialog.addEventListener('cancel',event => { if (finalizing) event.preventDefault(); });
    dialog.addEventListener('click',event => {
        if (event.target !== dialog || finalizing) return;
        const box = dialog.getBoundingClientRect();
        if (event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom) dialog.close();
    });
    dialog.addEventListener('keydown',event => {
        if (event.key !== 'Tab') return;
        const items=[...dialog.querySelectorAll('button:not(:disabled),input:not([type="hidden"]),a[href]')].filter(element => element.getClientRects().length);
        const first=items[0],last=items[items.length-1];
        if (event.shiftKey && (document.activeElement===first || !items.includes(document.activeElement))) {event.preventDefault(); last?.focus();}
        else if (!event.shiftKey && (document.activeElement===last || !items.includes(document.activeElement))) {event.preventDefault(); first?.focus();}
    });
    dialog.addEventListener('close',() => {
        // A native close event can arrive after the same dialog was reopened.
        if (dialog.open) return;
        cycle += 1;
        request?.abort(); busy=false; finalizing=false;
        if (previousOverflow !== null) document.body.style.overflow=previousOverflow;
        previousOverflow = null;
        form.reset(); window.PasswordVisibility?.reset(form);
        message(''); trigger.focus({preventScroll:true});
    });
    const timer = setInterval(() => { if (dialog.open) buttons(); },1000);
    scope.cleanup(() => {
        clearInterval(timer); cycle += 1; request?.abort();
        if (dialog.open) dialog.close();
        if (previousOverflow !== null) document.body.style.overflow=previousOverflow;
        previousOverflow = null;
    });
},10);
