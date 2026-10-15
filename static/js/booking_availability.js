/* ============================================================================
 * Booking Availability Guards (Phase 1 — decoupled module, vanilla JS only)
 * ----------------------------------------------------------------------------
 * Hiwalay na file para hindi madamay kapag nag-error ang ibang bahagi ng
 * 2000-line inline script ng booking page (hal. FullCalendar CDN failure).
 * WALANG dependency sa FullCalendar object o ibang page scripts — ang inputs
 * ay plain JSON data (blocked dates + booked ranges) mula sa Django.
 *
 * Data contract (mula sa template via json_script):
 *   #booking-availability-data  → {
 *       blockedDates: [{date: "YYYY-MM-DD", reason: "..."}],
 *       bookedRanges: {"YYYY-MM-DD": [[startMin, endMin], ...]},
 *       todayIso: "YYYY-MM-DD"
 *     }
 * Rules (mirror ng backend bookings.py — server pa rin ang source of truth):
 * - Blocked (admin) date → unavailable
 * - Fully-booked = union ng ranges ang sumasakop sa buong 07:00–18:00
 * - Operating hours: Start 07:00–16:00, End 07:00–18:00, minimum 2 hours
 * ========================================================================== */
(function (global) {
    'use strict';

    var DAY_START_MINUTES = 7 * 60;
    var DAY_END_MINUTES = 18 * 60;
    var START_MAX_MINUTES = 16 * 60;
    var MIN_DURATION_MINUTES = 120;
    var SUGGESTION_WINDOW_DAYS = 60;
    var SUGGESTION_LIMIT = 3;
    var SLOT_STEP_MINUTES = 15;

    function toMinutes(timeValue) {
        if (!timeValue || timeValue.indexOf(':') === -1) return null;
        var parts = timeValue.split(':');
        var hour = parseInt(parts[0], 10);
        var minute = parseInt(parts[1], 10);
        if (isNaN(hour) || isNaN(minute)) return null;
        return (hour * 60) + minute;
    }

    function parseLocalDate(dateStr) {
        var parts = dateStr.split('-').map(Number);
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    function formatLocalDate(dateObj) {
        var month = String(dateObj.getMonth() + 1).padStart(2, '0');
        var day = String(dateObj.getDate()).padStart(2, '0');
        return dateObj.getFullYear() + '-' + month + '-' + day;
    }

    function safeReadData() {
        try {
            var el = document.getElementById('booking-availability-data');
            if (!el) return { blockedDates: [], bookedRanges: {}, todayIso: '', leadDays: 0 };
            var data = JSON.parse(el.textContent || '{}');
            var leadRaw = parseInt(data.leadDays, 10);
            return {
                blockedDates: Array.isArray(data.blockedDates) ? data.blockedDates : [],
                bookedRanges: (data.bookedRanges && typeof data.bookedRanges === 'object') ? data.bookedRanges : {},
                todayIso: typeof data.todayIso === 'string' ? data.todayIso : '',
                leadDays: isNaN(leadRaw) || leadRaw < 0 ? 0 : leadRaw
            };
        } catch (e) {
            return { blockedDates: [], bookedRanges: {}, todayIso: '', leadDays: 0 };
        }
    }

    /* Lead-time floor (mirror ng SiteSettings.booking_lead_time_days):
       today + leadDays ang pinaka-maagang pwedeng petsa. */
    function getMinBookableDate(data) {
        var todayStr = (data && data.todayIso) || formatLocalDate(new Date());
        var lead = (data && data.leadDays) || 0;
        if (!lead) return todayStr;
        var cursor = parseLocalDate(todayStr);
        cursor.setDate(cursor.getDate() + lead);
        return formatLocalDate(cursor);
    }

    function isPastOrLeadBlocked(dateStr, data) {
        if (!dateStr || !data) return false;
        return dateStr < getMinBookableDate(data);
    }

    function isBlockedDate(dateStr, blockedDates) {
        if (!dateStr || !Array.isArray(blockedDates)) return false;
        for (var i = 0; i < blockedDates.length; i++) {
            if (blockedDates[i] && blockedDates[i].date === dateStr) return true;
        }
        return false;
    }

    /* Union check: fully-booked kapag sakop ng ranges ang buong 07:00–18:00
       nang walang butas kahit isang minuto. */
    function isFullyBookedDate(dateStr, bookedRanges) {
        if (!dateStr || !bookedRanges) return false;
        var ranges = bookedRanges[dateStr];
        if (!ranges || !ranges.length) return false;

        var sorted = ranges.slice().sort(function (a, b) { return a[0] - b[0]; });
        var coveredUntil = DAY_START_MINUTES;
        for (var i = 0; i < sorted.length; i++) {
            if (sorted[i][0] > coveredUntil) return false;
            coveredUntil = Math.max(coveredUntil, sorted[i][1]);
            if (coveredUntil >= DAY_END_MINUTES) return true;
        }
        return coveredUntil >= DAY_END_MINUTES;
    }

    function isDateUnavailable(dateStr, data) {
        if (!dateStr || !data) return false;
        if (isPastOrLeadBlocked(dateStr, data)) return true;
        if (isBlockedDate(dateStr, data.blockedDates)) return true;
        return isFullyBookedDate(dateStr, data.bookedRanges);
    }

    /* Bakit naka-block ang isang petsa — para sa picker tooltip/label:
       past | lead-time | blocked | fully-booked | '' (available). */
    function getDateBlockReason(dateStr, data) {
        if (!dateStr || !data) return '';
        var todayStr = data.todayIso || formatLocalDate(new Date());
        if (dateStr < todayStr) return 'past';
        if (isPastOrLeadBlocked(dateStr, data)) return 'lead-time';
        if (isBlockedDate(dateStr, data.blockedDates)) return 'blocked';
        if (isFullyBookedDate(dateStr, data.bookedRanges)) return 'fully-booked';
        return '';
    }

    /* Overlap check ng isang [start,end) slot laban sa booked ranges ng petsa. */
    function isSlotOverlapping(dateStr, startMin, endMin, bookedRanges) {
        if (!dateStr || startMin === null || endMin === null) return false;
        var ranges = (bookedRanges || {})[dateStr];
        if (!ranges || !ranges.length) return false;
        for (var i = 0; i < ranges.length; i++) {
            var bookedStart = ranges[i][0];
            var bookedEnd = ranges[i][1];
            if (startMin < bookedEnd && endMin > bookedStart) return true;
        }
        return false;
    }

    /* Start slots na hindi na kailangang i-error: nasa loob ng 07:00–16:00,
       hindi nakaraan (kapag today), at may puwang pa para sa 2h minimum. */
    function getAvailableStartSlots(dateStr, data, nowMinutesOverride) {
        var slots = [];
        if (!dateStr || !data) return slots;
        if (isDateUnavailable(dateStr, data)) return slots;
        var nowMinutes = (typeof nowMinutesOverride === 'number')
            ? nowMinutesOverride
            : (function () {
                var now = new Date();
                return Math.ceil(((now.getHours() * 60) + now.getMinutes()) / SLOT_STEP_MINUTES) * SLOT_STEP_MINUTES;
            })();
        var floor = DAY_START_MINUTES;
        if (dateStr === (data.todayIso || formatLocalDate(new Date()))) {
            floor = Math.max(floor, nowMinutes);
        }
        for (var minutes = DAY_START_MINUTES; minutes <= START_MAX_MINUTES; minutes += SLOT_STEP_MINUTES) {
            if (minutes < floor) continue;
            /* Kailangang may 2h pang natitira bago mag-18:00. */
            if (minutes + MIN_DURATION_MINUTES > DAY_END_MINUTES) continue;
            /* Kailangang may 2h window na hindi tinatamaan ng booked ranges. */
            var probeEnd = Math.min(minutes + MIN_DURATION_MINUTES, DAY_END_MINUTES);
            if (isSlotOverlapping(dateStr, minutes, probeEnd, data.bookedRanges)) continue;
            slots.push(minutes);
        }
        return slots;
    }

    /* End slots para sa napiling start: start+2h hanggang 18:00, lampas sa
       booked ranges ang hindi na isinasama. */
    function getAvailableEndSlots(dateStr, startMinutes, data) {
        var slots = [];
        if (!dateStr || !data || startMinutes === null || startMinutes === undefined) return slots;
        if (isDateUnavailable(dateStr, data)) return slots;
        var minEnd = startMinutes + MIN_DURATION_MINUTES;
        for (var minutes = minEnd; minutes <= DAY_END_MINUTES; minutes += SLOT_STEP_MINUTES) {
            if (isSlotOverlapping(dateStr, startMinutes, minutes, data.bookedRanges)) continue;
            slots.push(minutes);
        }
        return slots;
    }

    function minutesToValue(minutes) {
        var hours = String(Math.floor(minutes / 60)).padStart(2, '0');
        var mins = String(minutes % 60).padStart(2, '0');
        return hours + ':' + mins;
    }

    function minutesToLabel(minutes) {
        var hour24 = Math.floor(minutes / 60);
        var minute = minutes % 60;
        var suffix = hour24 >= 12 ? 'PM' : 'AM';
        var hour12 = hour24 % 12;
        if (hour12 === 0) hour12 = 12;
        return hour12 + ':' + String(minute).padStart(2, '0') + ' ' + suffix;
    }

    /* Mirror ng server-side na check_date_availability: hanggang 3 mungkahi
       sa loob ng 60 araw, iniiwasan ang past/blocked/fully-booked. */
    function getNearestOpenDates(fromDateStr, data, limit) {
        var maxSuggestions = limit || SUGGESTION_LIMIT;
        var suggestions = [];
        if (!fromDateStr || !data) return suggestions;
        try {
            var todayStr = data.todayIso || formatLocalDate(new Date());
            var cursor = parseLocalDate(fromDateStr);
            var daysChecked = 0;
            while (suggestions.length < maxSuggestions && daysChecked < SUGGESTION_WINDOW_DAYS) {
                cursor.setDate(cursor.getDate() + 1);
                daysChecked += 1;
                var candidate = formatLocalDate(cursor);
                if (candidate < todayStr) continue;
                if (isDateUnavailable(candidate, data)) continue;
                suggestions.push(candidate);
            }
        } catch (e) { /* defensive: ibalik kung ano man ang nakuha */ }
        return suggestions;
    }

    /* Return: { startError, endError, violated } — walang DOM side effects. */
    function validateTimes(startValue, endValue) {
        var startMinutes = toMinutes(startValue);
        var endMinutes = toMinutes(endValue);
        var result = { startError: '', endError: '', violated: false };

        if (startMinutes !== null && (startMinutes < DAY_START_MINUTES || startMinutes > START_MAX_MINUTES)) {
            result.startError = 'Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time between 7:00 AM and 4:00 PM.';
            result.violated = true;
        }
        if (endMinutes !== null && (endMinutes < DAY_START_MINUTES || endMinutes > DAY_END_MINUTES)) {
            result.endError = 'Booking hours are 7:00 AM to 6:00 PM only. End time must be between 7:00 AM and 6:00 PM.';
            result.violated = true;
        } else if (startMinutes !== null && endMinutes !== null && (endMinutes - startMinutes) < MIN_DURATION_MINUTES) {
            result.endError = 'Event duration must be at least 2 hours.';
            result.violated = true;
        }
        return result;
    }

    /* Buong Step-2 state sa isang tawag: date + time. Kahit walang laman ang
       oras, naka-disabled pa rin kapag blocked/fully-booked ang petsa. */
    function computeNextDisabled(dateValue, startValue, endValue, data) {
        try {
            if (dateValue && isDateUnavailable(dateValue, data)) return true;
            return validateTimes(startValue, endValue).violated;
        } catch (e) {
            return false;
        }
    }

    global.BookingAvailability = {
        DAY_START_MINUTES: DAY_START_MINUTES,
        DAY_END_MINUTES: DAY_END_MINUTES,
        START_MAX_MINUTES: START_MAX_MINUTES,
        MIN_DURATION_MINUTES: MIN_DURATION_MINUTES,
        SLOT_STEP_MINUTES: SLOT_STEP_MINUTES,
        toMinutes: toMinutes,
        parseLocalDate: parseLocalDate,
        formatLocalDate: formatLocalDate,
        readData: safeReadData,
        isBlockedDate: isBlockedDate,
        isFullyBookedDate: isFullyBookedDate,
        isDateUnavailable: isDateUnavailable,
        getDateBlockReason: getDateBlockReason,
        getMinBookableDate: getMinBookableDate,
        isPastOrLeadBlocked: isPastOrLeadBlocked,
        isSlotOverlapping: isSlotOverlapping,
        getAvailableStartSlots: getAvailableStartSlots,
        getAvailableEndSlots: getAvailableEndSlots,
        minutesToValue: minutesToValue,
        minutesToLabel: minutesToLabel,
        getNearestOpenDates: getNearestOpenDates,
        validateTimes: validateTimes,
        computeNextDisabled: computeNextDisabled
    };
})(window);
