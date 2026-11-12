/* A read-only introduction to interface regions; no form or transaction actions. */
window.SiteGuideContent = (() => {
    const item = (target,title,text) => ({target,title,text});
    const calendars = [
        item('#booking-calendar','Events calendar','This calendar displays the event schedule and date availability.'),
        item('.cal-toolbar','Calendar controls','The arrows, month selector and view buttons change the calendar display.'),
        item('.calendar-legend','Schedule legend','The legend explains the marks used for scheduled events.')
    ];
    const canvas = [
        item('.canvas-tool-rail','Design tools','Assets, Text, Uploads and Layers organize the tools used in the editor.'),
        item('#canvasDropZone','Design workspace','This is the layout area where the event design is displayed and arranged.'),
        item('.canvas-main-toolbar','Editor controls','The toolbar contains the available canvas, zoom and editing controls.'),
        item('#saveDesignBtn','Saved layouts','Save stores the layout in My Designs. A saved design can be a draft or ready to book.'),
        item('#summaryFloatBtn, #mobileChecklistBtn','Design checklist','The checklist summarizes the selected offer, included items and design requirements.')
    ];
    const payments = [
        item('.mp-stats','Payment overview','These figures summarize the payment records and their review status.'),
        item('#paymentsTabs','Payment categories','The categories organize action-required records, remaining balances and payment history.'),
        item('.cp-tab-panel.is-active .account-table-wrap','Payment records','This table displays the records for the selected category, including amounts, status and available actions.'),
        item('.cp-tab-panel.is-active .cp-btn-view','Payment details','The details control opens the payment record and its related booking information.'),
        item('.cp-tab-panel.is-active .cp-btn-download','Payment receipts','Verified payment records can have a receipt available for download.')
    ];
    function feature(page) {
        if (['booking_page','customer_profile'].includes(page)) return 'booking';
        if (page==='design_canvas') return 'canvas';
        if (['my_payments','payment_page','booking_change_payment'].includes(page)) return 'payments';
        return '';
    }
    function entries(page,scope) {
        const kind=feature(page);
        if (!kind) return [];
        if (scope!==document) {
            if (kind==='booking' && scope.matches('#bookingModalOverlay,#editBookingModal')) return [
                item('.stepper-wrapper','Booking sections','The section indicator organizes the booking information into event details, offer, design preferences and review.'),
                item('.stepper-step h3','Current section','This heading identifies the section currently displayed in the form.'),
                item('#eventTypeCustomSelect, #editEventTypeCustomSelect','Event information','This area describes the occasion associated with the booking.'),
                item('.time-row','Event schedule','Start and End together show the event schedule and duration.'),
                item('.location-card-group','Venue information','This section combines the venue address, map pin, location controls and arrival information.'),
                item('.stepper-step[style*="block"] .package-cards-grid','Available offers','The offer cards display current package information, inclusions and prices.'),
                item('.form-group:has(#designThemeChips), .form-group:has(#editDesignThemeChips)','Theme / Decor Style','The theme describes the preferred style of the event setup, including any custom theme.'),
                item('.form-group:has(#designPaletteSwatches), .form-group:has(#editDesignPaletteSwatches)','Color palette','This area contains the preset colors, custom color picker and selected colors for the design.'),
                item('.form-group:has(#motto_text), .form-group:has(#edit_motto_text)','Motto / Backdrop text','This optional text is the wording requested for the backdrop or signage.'),
                item('.form-group:has(#booking_special_requests), .form-group:has(#edit_special_requests)','Special requests','These optional design notes describe additional preferences for the event setup.'),
                item('.form-group:has(#booking_reference_images_ui), #edit_images_section','Reference pictures','Reference pictures and their previews communicate the preferred appearance of the design.'),
                item('.booking-summary-container, #edit-booking-details-list','Booking summary','The review area brings together the booking information and displayed totals.')
            ];
            if (kind==='booking' && scope.matches('#bookingModal,#eventDesignModal')) return [
                item('.customer-booking-header','Booking details','This window brings together the information recorded for a reservation.'),
                item('#modalStatusBadge','Booking status','The status badge identifies the current stage of the reservation.'),
                item('.booking-detail-actions','Available booking actions','The controls shown here depend on the reservation’s current status and permissions.'),
                item('.customer-booking-content','Reservation information','The details area contains the recorded event, offer and design information.')
            ];
            if (kind==='payments' && scope.matches('#bookingModal')) return [
                item('.cp-modal-header','Payment details','This window shows a payment record and its related booking.'),
                item('#modal-payment-summary-section','Payment summary','The summary displays the booking total, paid amount and remaining balance.'),
                item('#modal-activity-section','Payment activity','The activity area displays recorded payment progress and review updates.'),
                item('#modal-payment-detail-section','Recorded transaction','This section contains the available reference, amount and review information for the selected payment.')
            ];
            if (kind==='canvas' && scope.matches('#mobileInventoryDialog')) return [
                item('header','Editor panel','This panel contains the tools for the selected editor category.'),
                item('.panel-search','Find editor items','Search and category controls organize the available items.'),
                item('.draggable-item','Available items','Each item represents an element available in this editor panel.')
            ];
            if (kind==='canvas' && scope.matches('#mobileChecklistDialog')) return [
                item('header','Design checklist','This panel summarizes the offer and its requirements.'),
                item('#designOverallState','Design readiness','The readiness summary reports the current design evaluation.'),
                item('#designRequiredGroup','Included requirements','The requirement rows compare included items with the current layout.')
            ];
            if (kind==='canvas' && scope.closest('#saveDesignModal')) return [
                item('#saveDesignModalTitle','Save Design window','This window identifies the layout that will appear in My Designs.'),
                item('#saveDesignNameInput','Design name','The design name is the label used to recognize this saved layout.')
            ];
            return [];
        }
        if (page==='booking_page') return calendars;
        if (page==='customer_profile') return [
            item('.stats-row','Booking overview','The overview summarizes reservations by their current status.'),
            item('#filterForm','Find bookings','Search, status and sorting controls organize the booking list.'),
            item('.account-table-wrap','Your reservations','The list displays reservation details, status and the available controls.'),
            item('.booking-row-action, .btn-view','Booking actions','Each reservation exposes the actions available at its current stage.')
        ];
        if (kind==='canvas') return canvas;
        if (page==='my_payments') return payments;
        return [
            item('.pu-head-text','Payment information','This page brings together the payment information for the selected booking.'),
            item('.booking-deadline-note, .pu-change-deadline','Payment status and deadline','This notice displays the applicable deadline or the payment’s current review state.'),
            item('.cp-option-grid, .pu-fixed-option','Payment options','This area displays the payment options and amounts currently available for this booking.'),
            item('.pu-qr-section','Pay with GCash QR','Scan or download the merchant QR. Check the recipient and send the exact selected amount in GCash.'),
            item('.pu-side','Booking and amount summary','The summary contains the related booking details and displayed amounts.'),
            item('.pu-proof-grid','Submit payment proof','Enter the GCash transaction reference, sender name, and transaction date and time from your successful payment.'),
            item('.pu-proof-fields [data-payment-upload]','Upload payment screenshot','Choose or drag in your successful payment screenshot. Use a PNG or JPEG image up to 5 MB. You can preview or remove the selected image before submitting.'),
            item('.pu-terms-box','Payment acknowledgement','The acknowledgement presents the conditions associated with the payment.'),
            item('#js-checkout-btn','Submit for verification','After paying the merchant QR, submit the transaction details and screenshot here. Wait for admin verification before paying again.'),
            item('.ps-hero, .pu-paid','Payment progress','This area displays the recorded payment state, including verification or completion.')
        ];
    }
    function getSteps(page,scope,visible) {
        const seen=new Set();
        return entries(page,scope).flatMap(entry => {
            const element=[...scope.querySelectorAll(entry.target)].find(visible);
            if (!element || seen.has(element)) return [];
            seen.add(element);return [{...entry,element}];
        });
    }
    return {feature,getSteps};
})();
