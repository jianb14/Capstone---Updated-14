/* ==========================================================================
   STATS COUNT-UP - HOME PAGE
   --------------------------------------------------------------------------
   - Ang mga numero sa .stats-section .stat-item h3 ay bumibilang mula 0
     papunta sa totoong value kapag pumasok na sila sa viewport.
   - Data-driven: kinukuha ang unang numero sa loob ng text, at ang natitira
     (prefix/suffix tulad ng "+", "%", "HR", "★") ay pinapanatili mismo.
   - Scroll-triggered gamit ang IntersectionObserver (isang beses lang).
   - Nirerespeto ang prefers-reduced-motion (static, hindi nagbibilang).
   ========================================================================== */

(function () {
    'use strict';

    var statHeads = document.querySelectorAll('.stats-section .stat-item h3');
    if (!statHeads.length) return;

    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    /* Kinukuha ang numero sa loob ng text (hal. "500+" -> 500, "4.9★" -> 4.9,
       "24HR" -> 24). Kung walang numero, ibabalik ang null para maiwan lang
       ang orihinal na text (hindi na ia-animate). */
    function parseStat(text) {
        var match = text.match(/^([^\d]*)([\d][\d.,]*)([\s\S]*)$/);
        if (!match) return null;

        var raw = match[2];
        var hasComma = raw.indexOf(',') !== -1;
        var hasDot = raw.indexOf('.') !== -1;

        /* Kung may comma at dot: ang dot ang decimal separator (hal. "1,500.50").
           Kung comma lang: thousands separator ito kung pang-3 digit ang gap
           (hal. "1,500"), kung hindi, decimal comma (hal. "4,9"). */
        var normalized = raw;
        var decimals = 0;
        if (hasDot) {
            normalized = raw.replace(/,/g, '');
            decimals = (normalized.split('.')[1] || '').length;
        } else if (hasComma) {
            var parts = raw.split(',');
            /* Kung lahat ng grupo pagkatapos ng unang number ay eksaktong
               3 digit, thousands separator ang mga comma (1,500 / 12,345,678);
               kung hindi, decimal comma (hal. "4,9"). */
            var allGroupsOfThree = parts.slice(1).every(function (p) { return p.length === 3; });
            if (allGroupsOfThree) {
                normalized = parts.join('');
            } else {
                normalized = parts.join('.');
                decimals = (parts[parts.length - 1] || '').length;
            }
        }

        var value = parseFloat(normalized);
        if (isNaN(value)) return null;

        return {
            prefix: match[1],
            suffix: match[3],
            target: value,
            decimals: decimals,
            useGrouping: hasComma
        };
    }

    /* Pag-format ng kasalukuyang value habang bumibilang */
    function formatValue(value, stat) {
        return value.toLocaleString('en-US', {
            minimumFractionDigits: stat.decimals,
            maximumFractionDigits: stat.decimals,
            useGrouping: stat.useGrouping
        });
    }

    /* easeOutCubic: mabilis sa simula, dahan-dahan sa dulo (mas natural
       na dating kaysa linya na straight count) */
    function easeOutCubic(t) {
        return 1 - Math.pow(1 - t, 3);
    }

    function animateStat(stat, duration) {
        var startTime = null;
        function frame(now) {
            if (startTime === null) startTime = now;
            var t = Math.min((now - startTime) / duration, 1);
            var current = stat.target * easeOutCubic(t);
            stat.el.textContent = stat.prefix + formatValue(current, stat) + stat.suffix;
            if (t < 1) {
                requestAnimationFrame(frame);
            } else {
                /* Siguraduhing eksakto ang final value (walang rounding drift) */
                stat.el.textContent = stat.prefix + formatValue(stat.target, stat) + stat.suffix;
            }
        }
        requestAnimationFrame(frame);
    }

    var stats = [];
    statHeads.forEach(function (el) {
        var parsed = parseStat(el.textContent);
        if (parsed) {
            parsed.el = el;
            parsed.original = el.textContent;
            stats.push(parsed);
        }
    });
    if (!stats.length) return;

    /* Reduced motion: huwag nang i-zero at huwag nang magbilang -
       manatili lang ang totoong values */
    if (reducedMotion.matches || !('IntersectionObserver' in window)) {
        return;
    }

    /* I-zero muna ang mga numero habang hindi pa nakikita, tapos bibilangin
       papunta sa totoong value kapag pumasok na ang stats card sa viewport */
    stats.forEach(function (stat) {
        stat.el.textContent = stat.prefix + formatValue(0, stat) + stat.suffix;
    });

    var card = document.querySelector('.stats-section .stats-card') || statHeads[0].closest('.stats-section');
    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            observer.unobserve(entry.target);
            /* konting stagger kada stat para sunud-sunod ang pagbilang */
            stats.forEach(function (stat, i) {
                setTimeout(function () {
                    animateStat(stat, 1600);
                }, i * 150);
            });
        });
    }, { threshold: 0.35 });

    observer.observe(card);
})();