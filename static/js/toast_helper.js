/* ==========================================================
   Shared Toast helper (client pages)
   ------------------------------------------------------------
   Iisa na ang pinagmumulan ng toasts sa buong client site, para
   hindi na mapagsabay-sabay ang magkakaibang `Swal.mixin()` sa
   bawat template.

   Naka-define ang `window.AppToast` na may parehong interface sa
   dating `Toast` (`AppToast.fire({...})`), kaya halos hindi
   nagbabago ang mga call site.

   Bakit kailangan nitong centralized:
   1) DEDUPE GUARD — kapag na-double-fire ang isang action (dalawang
      listener, o yung error branch at yung catch branch na sabay-sabay
      tumawag), pinipigilan nitong mag-stack ng dalawang toast sa
      iisang screen. Ang duplicate na `icon + title` sa loob ng
      DEDUPE_WINDOW_MS ay binabayan.
   2) Iisang default config para consistent sa lahat ng page.

   Usage:
     AppToast.fire({ icon: 'success', title: 'Saved!' });
     // o may sariling timer/config:
     const Toast = AppToast.mixin({ timer: 2000 });
     // Confirm dialog na kapareho ng admin design (puting button):
     AppToast.confirm({ title: 'Submit booking now?', text: '...' })
       .then(function (r) { if (r.isConfirmed) submit(); });
     // Destructive (RED ang confirm, gaya ng admin delete):
     AppToast.confirm({ title: 'Delete this?', danger: true });
   ========================================================== */
(function (global) {
    'use strict';

    if (global.AppToast) { return; }

    /* Panahagang pagbabantay: kapag pareho ang icon+title sa loob
       ng window na ito, itatago ang pangalawa. */
    var DEDUPE_WINDOW_MS = 1500;

    var BASE_OPTIONS = {
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true,
        background: '#1a1a1a',
        color: '#fff',
        didOpen: function (toast) {
            toast.addEventListener('mouseenter', global.Swal.stopTimer);
            toast.addEventListener('mouseleave', global.Swal.resumeTimer);
        }
    };

    var lastKey = '';
    var lastShownAt = 0;

    function getKey(options) {
        var icon = options.icon || 'info';
        var text = options.title || options.text || '';
        return icon + '|' + text;
    }

    /* Ibalot ang isang Swal mixin sa dedupe guard. */
    function withDedupe(mixin) {
        var originalFire = mixin.fire.bind(mixin);
        mixin.fire = function (options) {
            options = options || {};
            var now = Date.now();
            var key = getKey(options);

            if (key === lastKey && (now - lastShownAt) < DEDUPE_WINDOW_MS) {
                return Promise.resolve({ isDismissed: true });
            }

            lastKey = key;
            lastShownAt = now;
            return originalFire(options);
        };
        return mixin;
    }

    function merge(base, overrides) {
        var merged = {};
        var key;
        for (key in base) {
            if (Object.prototype.hasOwnProperty.call(base, key)) {
                merged[key] = base[key];
            }
        }
        for (key in overrides) {
            if (Object.prototype.hasOwnProperty.call(overrides, key)) {
                merged[key] = overrides[key];
            }
        }
        return merged;
    }

    /* ── CONFIRM DIALOG (parang admin side) ────────────────────────
       Ang admin ay gumagamit ng `customClass` + `buttonsStyling:false`
       (tingnan ang admin_payment_list.html / admin_base.css
       `.booking-request-*`) — kaya PUTI ang confirm button
       (#f0f0f0 + dark text), hindi blue.

       Isinasalita dito ang parehong design token para pantay ang
       hitsura sa client at admin. Ang `danger: true` naman ang
       ginagamit ng destructive actions (hal. delete) para RED pa rin
       ang confirm (#dc2626) gaya ng admin delete flow. */
    var DIALOG_CLASSES = {
        popup: 'app-dialog-popup',
        title: 'app-dialog-title',
        actions: 'app-dialog-actions',
        confirmButton: 'app-dialog-confirm',
        cancelButton: 'app-dialog-cancel'
    };

    function confirmDialog(options) {
        options = options || {};

        var classes = merge(DIALOG_CLASSES, {});
        if (options.danger) {
            classes.confirmButton =
                'app-dialog-confirm app-dialog-confirm--danger';
        }

        var config = {
            title: options.title,
            text: options.text,
            icon: options.icon || 'warning',
            showCancelButton: true,
            confirmButtonText: options.confirmText || 'Yes, Continue',
            cancelButtonText: options.cancelText || 'Cancel',
            reverseButtons: true,
            focusCancel: true,
            buttonsStyling: false,
            customClass: classes
        };

        if (options.input) { config.input = options.input; }
        if (options.inputPlaceholder) {
            config.inputPlaceholder = options.inputPlaceholder;
        }
        if (options.inputValidator) {
            config.inputValidator = options.inputValidator;
        }
        if (typeof options.didOpen === 'function') {
            config.didOpen = options.didOpen;
        }

        return global.Swal.fire(config);
    }

    /* Ang default instance — ginagamit ng AppToast.fire(). */
    var defaultToast = withDedupe(global.Swal.mixin(BASE_OPTIONS));

    global.AppToast = {
        fire: function (options) {
            return defaultToast.fire(options || {});
        },
        mixin: function (overrides) {
            return withDedupe(global.Swal.mixin(merge(BASE_OPTIONS, overrides || {})));
        },
        confirm: confirmDialog,
        DIALOG_CLASSES: DIALOG_CLASSES,
        /* Para sa pagsusuri/testing lamang. */
        DEDUPE_WINDOW_MS: DEDUPE_WINDOW_MS
    };

})(window);