/* Booking/admin calendar load guard.
 *
 * Sariling static file (hindi kasama sa malaking inline page script) para
 * tumatakbo kahit mag-syntax-error o mag-fail ang page script — o kapag hindi
 * nag-load ang FullCalendar CDN. Nagpapalit ng "Loading..." sa friendly error
 * card + reload button, at dini-disable ang custom toolbar para hindi mag-throw
 * sa walang calendar object.
 */
(function () {
    'use strict';

    var TOOLBAR_IDS = ['cal-prev', 'cal-next', 'cal-today', 'cal-title'];

    function findMount() {
        return document.getElementById('booking-calendar-mount')
            || document.getElementById('admin-calendar-mount');
    }

    function disableToolbar() {
        TOOLBAR_IDS.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.disabled = true;
                el.setAttribute('aria-disabled', 'true');
            }
        });
        document.querySelectorAll('.cal-view-btn[data-view]').forEach(function (btn) {
            btn.disabled = true;
            btn.setAttribute('aria-disabled', 'true');
        });
    }

    function showCalendarLoadError(reason) {
        var titleEl = document.getElementById('cal-title-text');
        if (titleEl) titleEl.textContent = 'Calendar unavailable';

        var mount = findMount();
        if (mount && !mount.querySelector('.calendar-load-error')) {
            while (mount.firstChild) mount.removeChild(mount.firstChild);
            var note = document.createElement('div');
            note.className = 'calendar-load-error';
            note.setAttribute('role', 'alert');
            note.innerHTML =
                '<i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i>'
                + '<p><strong>Events calendar could not load.</strong> '
                + 'Check your internet connection, then reload the page. '
                + 'The rest of this page still works.</p>';
            var retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'calendar-reload-btn';
            retry.textContent = 'Reload page';
            retry.addEventListener('click', function () {
                window.location.reload();
            });
            note.appendChild(retry);
            mount.appendChild(note);
        }

        disableToolbar();

        if (reason && window.console && console.error) {
            console.error('[calendar-load-guard] ' + reason);
        }
    }

    /* Tinitawag ng page script kapag bumigong mag-init/render ang FullCalendar. */
    window.showBookingCalendarLoadError = showCalendarLoadError;

    /* Watchdog: kapag matapos ang timeout ay "Loading..." pa rin ang title at
       walang FullCalendar output (.fc), ibig sabihin may naunang JS error —
       ipakita ang fallback sa halip na nakatagan sa Loading. */
    document.addEventListener('DOMContentLoaded', function () {
        window.setTimeout(function () {
            var titleEl = document.getElementById('cal-title-text');
            if (!titleEl || titleEl.textContent.indexOf('Loading') === -1) return;
            var mount = findMount();
            if (mount && mount.querySelector('.fc')) return;
            showCalendarLoadError('watchdog: calendar still showed "Loading..." after timeout');
        }, 4000);
    });
})();
