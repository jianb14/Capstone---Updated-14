AccountPages.enhance('customer_profile', 'booking_changes.js', function(scope) {
    'use strict';
    scope.capture(['configureBookingChangeForm', 'promptBookingChangeReason',
        'checkBookingChangeEligibility', 'confirmBookingChangePrice']);
    let askingReason = false;
    let checkingEligibility = false, askingPrice = false, acknowledgedEstimate = '';
    window.checkBookingChangeEligibility = async url => {
        if (checkingEligibility || askingReason) return null;
        checkingEligibility = true;
        try {
            const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store',
                signal: scope.controller.signal,
                headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}});
            if (!scope.active) return null;
            if (response.redirected || !response.ok) throw new Error('Eligibility check failed');
            const state = await response.json();
            if (!scope.active) return null;
            if (state.can_request_changes !== true) {
                window.AppToast.fire({icon: 'info', title: state.message || 'Booking changes are not available right now.', timer: 6500});
                return null;
            }
            return state;
        } catch (error) {
            if (scope.active && error.name !== 'AbortError') window.AppToast.fire({icon: 'error',
                title: "We couldn't check whether changes are available. Please refresh the page and try again.", timer: 6500});
            return null;
        } finally {
            checkingEligibility = false;
        }
    };
    window.confirmBookingChangePrice = async estimatedTotal => {
        const form = document.getElementById('editBookingForm');
        if (!form || form.dataset.changeMode !== '1') return true;
        const paid = Number(form.dataset.verifiedPaidCents);
        const original = Number(form.dataset.originalTotalCents);
        const total = Math.round(Number(estimatedTotal) * 100);
        if (!Number.isFinite(total) || total < 0) return false;
        if (paid <= total || total >= original) return true;
        const key = `${paid}:${total}`;
        if (acknowledgedEstimate === key) return true;
        if (askingPrice) return false;
        askingPrice = true;
        const money = cents => new Intl.NumberFormat('en-PH', {style: 'currency', currency: 'PHP'}).format(cents / 100);
        try {
            const result = await window.AppToast.confirm({
                title: 'Review your package change',
                text: `Your verified payments total ${money(paid)}. The estimated revised booking total is ${money(total)}, leaving an estimated excess of ${money(paid - total)}. If the final quote confirms an excess, it will not be refunded under the existing payment policy, subject to its stated exceptions. Our team will confirm the final amount in your quote.`,
                confirmText: 'Continue with Changes', cancelText: 'Keep Current Selection'
            });
            if (!scope.active || !result.isConfirmed) return false;
            acknowledgedEstimate = key;
            return true;
        } finally {
            askingPrice = false;
        }
    };
    window.promptBookingChangeReason = async bookingId => {
        if (askingReason) return null;
        askingReason = true;
        const trigger = document.activeElement;
        const wasViewingDetails = document.getElementById('bookingModal')?.classList.contains('show');
        window.CustomerBookingModals?.close(false);
        let reason = null;
        try {
            const result = await window.AppToast.confirm({
                title: 'Request booking changes',
                text: `Tell us why you want to change Booking #${bookingId}. You can select your changes on the next screen.`,
                input: 'textarea', inputLabel: 'Why are you requesting changes?',
                inputPlaceholder: 'For example: We need a larger package because more guests will attend.',
                inputAttributes: { maxlength: '2000', rows: '4' },
                inputValidator: value => {
                    const length = value.trim().length;
                    if (length < 10 || length > 2000) return 'Please provide a reason between 10 and 2,000 characters.';
                },
                confirmText: 'Continue to Changes',
                cancelText: 'Cancel', returnFocus: false
            });
            if (result.isConfirmed) reason = result.value.trim();
            return reason;
        } finally {
            askingReason = false;
            if (!reason) {
                if (wasViewingDetails) window.openBookingModal?.(bookingId);
                else if (trigger?.isConnected) trigger.focus();
            }
        }
    };
    window.configureBookingChangeForm = (enabled, bookingId, requestReason = '', paymentState = null) => {
        const form = document.getElementById('editBookingForm');
        if (!form) return;
        form.dataset.changeMode = enabled ? '1' : '0';
        form.dataset.verifiedPaidCents = String(Math.round(Number(paymentState?.verified_paid || 0) * 100));
        form.dataset.originalTotalCents = String(Math.round(Number(paymentState?.original_total || 0) * 100));
        acknowledgedEstimate = '';
        document.getElementById('changeRequestBanner').hidden = !enabled;
        document.getElementById('changeRequestBookingId').textContent = `#${bookingId}`;
        const reason = document.getElementById('change_reason');
        reason.value = enabled ? requestReason.trim() : '';
        document.getElementById('changeRequestReasonText').textContent = reason.value;
        reason.disabled = !enabled;
        document.getElementById('changeRequestError').textContent = '';
        form.querySelector('button[type="submit"]').textContent = enabled ? 'Submit Change Request' : 'Update Booking';
    };

}, -30);
