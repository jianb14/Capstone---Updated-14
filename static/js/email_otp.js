document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('otp-resend');
    const notice = document.getElementById('otp-countdown');
    if (!button || !notice) return;
    const deadline = Date.now() + Math.max(0, Number(button.dataset.wait) || 0) * 1000;
    function update() {
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        button.disabled = remaining > 0;
        notice.textContent = remaining ? 'You can request another code in ' + remaining + ' seconds.' : '';
        if (!remaining) clearInterval(timer);
    }
    const timer = setInterval(update, 1000);
    update();
});
