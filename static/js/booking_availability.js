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
 * - Operating hours: Start 07:00–17:45, duration = min..max hours
 *   (overnight allowed: end < start → +24h), overtime beyond included hours
 * ========================================================================== */
(function (global) {
    'use strict';

    var DAY_START_MINUTES = 7 * 60;
    var DAY_END_MINUTES = 18 * 60;
    var START_MAX_MINUTES = 17 * 60 + 45;  // 15-min step → huling start bago 6:00 PM
    var MIN_DURATION_MINUTES = 120;   // fallback — ang server payload ang masusunod
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
            if (!el) return { blockedDates: [], bookedRanges: {}, todayIso: '', leadDays: 0, minDurationHours: 0, includedHours: 0, maxDurationHours: 0 };
            var data = JSON.parse(el.textContent || '{}');
            if (Array.isArray(data.rangeRecords)) {
                data.bookedRanges = {};
                data.rangeRecords.forEach(function (row) {
                    if (String(row.bookingId) === String(data.excludeBookingId)) return;
                    if (!data.bookedRanges[row.date]) data.bookedRanges[row.date] = [];
                    data.bookedRanges[row.date].push([row.start, row.end]);
                });
            }
            var leadRaw = parseInt(data.leadDays, 10);
            return {
                blockedDates: Array.isArray(data.blockedDates) ? data.blockedDates : [],
                bookedRanges: (data.bookedRanges && typeof data.bookedRanges === 'object') ? data.bookedRanges : {},
                todayIso: typeof data.todayIso === 'string' ? data.todayIso : '',
                leadDays: isNaN(leadRaw) || leadRaw < 0 ? 0 : leadRaw,
                minDurationHours: parseInt(data.minDurationHours, 10) || 0,
                includedHours: parseInt(data.includedHours, 10) || 0,
                overtimeRate: data.overtimeRate,
                originalDate: data.originalDate || '',
                maxDurationHours: parseInt(data.maxDurationHours, 10) || 0
            };
        } catch (e) {
            return { blockedDates: [], bookedRanges: {}, todayIso: '', leadDays: 0, minDurationHours: 0, includedHours: 0, maxDurationHours: 0 };
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

    /* Start slots na hindi na kailangang i-error: nasa loob ng 07:00–17:45
       (operating window), hindi nakaraan (kapag today), at may 2h minimum
       na puwang na hindi tinatamaan ng booked ranges. */
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
            /* May 2h minimum na window na dapat walang booked range —
               ang END ay pwedeng lumagpas ng 18:00 (overnight), kaya hindi
               na binobound ang probe sa DAY_END_MINUTES. */
            var probeEnd = minutes + MIN_DURATION_MINUTES;
            if (isSlotOverlapping(dateStr, minutes, probeEnd, data.bookedRanges)) continue;
            slots.push(minutes);
        }
        return slots;
    }

    /* End slots para sa napiling start: start+minDuration → start+maxDuration
       (overnight-aware — lumalampas sa 18:00 at +1 day kapag umabot ng
       hatinggabi). Iniiwasan ang booked ranges ng petsa, at ng SUSUNOD na
       araw kapag crossing midnight ang slot. */
    function getAvailableEndSlots(dateStr, startMinutes, data) {
        var slots = [];
        if (!dateStr || !data || startMinutes === null || startMinutes === undefined) return slots;
        if (isDateUnavailable(dateStr, data)) return slots;
        var policy = getDurationPolicy(data);
        var minEnd = startMinutes + policy.minMinutes;
        var maxEnd = startMinutes + policy.maxMinutes;
        var nextDateStr = null;
        try {
            var cursor = parseLocalDate(dateStr);
            cursor.setDate(cursor.getDate() + 1);
            nextDateStr = formatLocalDate(cursor);
        } catch (e) { nextDateStr = null; }
        for (var minutes = minEnd; minutes <= maxEnd; minutes += SLOT_STEP_MINUTES) {
            var sameDayEnd = Math.min(minutes, 24 * 60);
            if (isSlotOverlapping(dateStr, startMinutes, sameDayEnd, data.bookedRanges)) continue;
            if (minutes > 24 * 60 && nextDateStr &&
                isSlotOverlapping(nextDateStr, 0, minutes - 24 * 60, data.bookedRanges)) continue;
            slots.push(minutes);
        }
        return slots;
    }

    /* HH:MM value — ang ≥1440 na minutes ay bumabalik sa susunod na araw
       (0..1439) para hindi lumabas ang invalid na "24:00"/"25:00" sa input. */
    function minutesToValue(minutes) {
        var wrapped = minutes % (24 * 60);
        var hours = String(Math.floor(wrapped / 60)).padStart(2, '0');
        var mins = String(wrapped % 60).padStart(2, '0');
        return hours + ':' + mins;
    }

    function minutesToLabel(minutes) {
        var daySuffix = minutes >= 24 * 60 ? ' (+1 day)' : '';
        var hour24 = Math.floor(minutes / 60) % 24;
        var minute = minutes % 60;
        var suffix = hour24 >= 12 ? 'PM' : 'AM';
        var hour12 = hour24 % 12;
        if (hour12 === 0) hour12 = 12;
        return hour12 + ':' + String(minute).padStart(2, '0') + ' ' + suffix + daySuffix;
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

    /* Duration policy (mirror ng SiteSettings: min/included/max hours + rate).
       Lahat ng oras ay may-involve sa minutes; overnight = end <= start → +24h. */
    function getDurationPolicy(data) {
        var src = data || safeReadData();
        var minH = parseInt(src.minDurationHours, 10);
        var inclH = parseInt(src.includedHours, 10);
        var maxH = parseInt(src.maxDurationHours, 10);
        var rate = parseFloat(src.overtimeRate);
        return {
            minMinutes: (isNaN(minH) || minH < 1) ? MIN_DURATION_MINUTES : minH * 60,
            includedMinutes: (isNaN(inclH) || inclH < 1) ? 180 : inclH * 60,
            maxMinutes: (isNaN(maxH) || maxH < 1) ? 1440 : maxH * 60,
            overtimeRate: (isNaN(rate) || rate < 0) ? 500 : rate
        };
    }

    /* Duration sa minutes mula sa start/end; +24h kapag overnight (end <= start). */
    function getDurationMinutes(startMinutes, endMinutes) {
        if (startMinutes === null || endMinutes === null) return null;
        var duration = endMinutes - startMinutes;
        if (duration <= 0) duration += 24 * 60;
        return duration;
    }

    /* Return: { startError, endError, violated } — walang DOM side effects.
       Overtime (lampas sa included hours) ay HINDI violation — price lang. */
    function validateTimes(startValue, endValue, dateValue) {
        var startMinutes = toMinutes(startValue);
        var endMinutes = toMinutes(endValue);
        var policy = getDurationPolicy();
        var result = { startError: '', endError: '', violated: false };

        if (startMinutes !== null && (startMinutes < DAY_START_MINUTES || startMinutes > START_MAX_MINUTES)) {
            result.startError = 'Booking hours are 7:00 AM to 6:00 PM only. Please choose a start time between 7:00 AM and 5:45 PM.';
            result.violated = true;
        }

        if (endMinutes !== null && startMinutes !== null) {
            var duration = getDurationMinutes(startMinutes, endMinutes);
            if (duration !== null && duration < policy.minMinutes) {
                result.endError = 'Event duration must be at least ' + Math.floor(policy.minMinutes / 60) + ' hours.';
                result.violated = true;
            } else if (duration !== null && duration > policy.maxMinutes) {
                result.endError = 'Maximum booking duration is ' + Math.floor(policy.maxMinutes / 60) + ' hours only.';
                result.violated = true;
            }
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

    function overtimeNote(hours, includedHours, rate) {
        if (!hours) return 'No overtime charge.';
        return hours + ' hr(s) beyond the ' + includedHours + '-hour package × ₱'
            + Number(rate).toLocaleString('en-PH', { maximumFractionDigits: 2 }) + '/hr.';
    }
    global.BookingAvailability = {
        overtimeNote: overtimeNote,
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
        getDurationPolicy: getDurationPolicy,
        getDurationMinutes: getDurationMinutes,
        computeNextDisabled: computeNextDisabled
    };
})(window);
