document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-email-send]').forEach(emailForm => {
        const button = emailForm.querySelector('button[type="submit"]');
        const label = button.textContent;
        emailForm.addEventListener('submit', event => {
            if (button.disabled) { event.preventDefault(); return; }
            button.disabled = true;
            button.textContent = emailForm.dataset.loadingLabel || 'Sending code...';
        });
        window.addEventListener('pageshow', () => { button.disabled = false; button.textContent = label; });
    });
    const form = document.getElementById('otp-form');
    if (!form) return;
    const fields = Array.from(form.querySelectorAll('.otp-digit'));
    const aggregate = document.getElementById('otp-code');
    const submit = document.getElementById('otp-submit');
    const entryError = document.getElementById('otp-entry-error');
    const expiry = document.getElementById('otp-expiry');
    const resend = document.getElementById('otp-resend');
    const resendNotice = document.getElementById('otp-countdown');
    const verifyNotice = document.getElementById('otp-verify-countdown');
    const deadline = Date.now() + Math.max(0, Number(expiry.dataset.seconds) || 0) * 1000;
    const resendDeadline = Date.now() + Math.max(0, Number(resend.dataset.wait) || 0) * 1000;
    const verifyDeadline = Date.now() + Math.max(0, Number(form.dataset.verifyWait) || 0) * 1000;
    let busy = false;
    let resendBusy = false;
    const submitLabel = submit.textContent;
    const remaining = (end) => Math.max(0, Math.ceil((end - Date.now()) / 1000));
    function sync() {
        aggregate.value = fields.map(field => field.value).join('');
        submit.disabled = busy || remaining(verifyDeadline) > 0 || remaining(deadline) === 0 || !/^[0-9]{6}$/.test(aggregate.value);
    }
    function distribute(value, index) {
        const digits = value.replace(/[^0-9]/g, '').slice(0, 6);
        if (!digits) return;
        const start = digits.length === 6 ? 0 : index;
        digits.split('').forEach((digit, offset) => { if (fields[start + offset]) fields[start + offset].value = digit; });
        fields[Math.min(start + digits.length, 5)].focus();
        sync();
    }
    fields.forEach((field, index) => {
        // Allow mobile one-time-code autofill to deliver the whole code in one input event.
        field.maxLength = 6;
        field.addEventListener('focus', () => field.select());
        field.addEventListener('input', () => {
            const value = field.value;
            field.value = '';
            distribute(value, index);
            entryError.hidden = true;
            fields.forEach(item => item.removeAttribute('aria-invalid'));
            sync();
        });
        field.addEventListener('paste', event => {
            event.preventDefault();
            distribute(event.clipboardData.getData('text'), index);
        });
        field.addEventListener('keydown', event => {
            if (event.key === 'Backspace' && !field.value && index > 0) {
                event.preventDefault(); fields[index - 1].value = ''; fields[index - 1].focus(); sync();
            } else if (event.key === 'ArrowLeft' && index > 0) {
                event.preventDefault(); fields[index - 1].focus();
            } else if (event.key === 'ArrowRight' && index < 5) {
                event.preventDefault(); fields[index + 1].focus();
            }
        });
    });
    form.addEventListener('submit', event => {
        sync();
        if (submit.disabled) {
            event.preventDefault();
            entryError.textContent = 'Enter all six digits from your email.';
            entryError.hidden = false;
            fields.forEach(field => field.setAttribute('aria-invalid', 'true'));
            (fields.find(field => !field.value) || fields[0]).focus();
            return;
        }
        busy = true; submit.textContent = 'Verifying...'; sync();
    });
    resend.form.addEventListener('submit', event => {
        if (resend.disabled) { event.preventDefault(); return; }
        resendBusy = true; resend.disabled = true; resend.textContent = 'Sending code...';
    });
    function tick() {
        const seconds = remaining(deadline);
        const wait = remaining(resendDeadline);
        const lock = remaining(verifyDeadline);
        expiry.textContent = seconds ? 'Code expires in ' + Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0') : 'This code has expired. Request a new code below.';
        expiry.classList.toggle('is-expired', !seconds);
        resend.disabled = resendBusy || wait > 0;
        resendNotice.textContent = wait ? 'You can request another code in ' + wait + ' seconds.' : '';
        verifyNotice.textContent = lock ? 'Try again in ' + Math.floor(lock / 60) + ':' + String(lock % 60).padStart(2, '0') + '.' : '';
        sync();
    }
    window.addEventListener('pageshow', () => { busy = false; resendBusy = false; submit.textContent = submitLabel; resend.textContent = 'Resend Code'; tick(); });
    setInterval(tick, 1000);
    tick();
    if (document.activeElement === document.body && window.matchMedia('(pointer: fine)').matches) {
        fields[0].focus({ preventScroll: true });
    }
});
