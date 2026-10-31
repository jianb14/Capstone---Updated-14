AccountPages.enhance('customer_profile', 'booking_changes.js', function(scope) {
    'use strict';
    scope.capture(['configureBookingChangeForm', 'promptBookingChangeReason']);
    let askingReason = false;
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
    window.configureBookingChangeForm = (enabled, bookingId, requestReason = '') => {
        const form = document.getElementById('editBookingForm');
        if (!form) return;
        form.dataset.changeMode = enabled ? '1' : '0';
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
