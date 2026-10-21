/* A: helpers + date popover */
(function (g) {
'use strict';
var MO = ['January','February','March','April','May','June','July','August','September','October','November','December'];
function A() { return g.BookingAvailability || null; }
function RD() { try { return A().readData(); } catch (e) { return null; } }
function why(r, d, iso) {
  if (r === 'past') return 'Past date';
  if (r === 'lead-time') return 'Book at least ' + ((d && d.leadDays) || 0) + ' day(s) ahead';
  if (r === 'blocked') {
    var rows = (d && d.blockedDates) || [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i].date === iso && rows[i].reason) return 'Unavailable - ' + rows[i].reason;
    }
    return 'Unavailable (blocked by admin)';
  }
  if (r === 'fully-booked') return 'Fully booked (7AM-6PM taken)';
  return '';
}
function fire(input) {
  try { input.dispatchEvent(new Event('change', { bubbles: true })); }
  catch (e) { try { var ev = document.createEvent('HTMLEvents'); ev.initEvent('change', true, false); input.dispatchEvent(ev); } catch (e2) {} }
}
g._BKP = { MO: MO, A: A, RD: RD, why: why, fire: fire, pops: [],
  track: function (pop, close, extra) {
    try { g._BKP.pops.push({ pop: pop, close: close, extra: extra || null }); } catch (e) {}
  },
  /* Kapag bumukas ang isang popover, isara ang lahat ng iba pa — para hindi
     sabay-sabay na nakalabas ang date + start + end dropdowns. */
  closeOthers: function (exceptPop) {
    try {
      var arr = g._BKP.pops || [];
      for (var i = 0; i < arr.length; i++) {
        try { if (arr[i].pop !== exceptPop && !arr[i].pop.hidden) arr[i].close(); } catch (e) {}
      }
    } catch (e) {}
  },
  /* Matibay na outside-close: pointerdown capture (hindi na-block ng ibang
     click handlers sa modal) + focusin kapag lumipat sa ibang control.
     Kapag lumipat sa kapwa picker input, huwag isara dito — ang bubuksang
     input mismo ang magsasara ng iba via closeOthers. */
  outsideCloser: function (pop, input, close, extra) {
    if (!pop || !close) return;
    g._BKP.track(pop, close, extra);
    document.addEventListener('pointerdown', function (e) {
      try {
        if (pop.hidden) return;
        if (pop.contains(e.target) || e.target === input) return;
        /* Huwag isara kapag icon (calendar/clock) ang pinindot — ang icon
           click handler ang magto-toggle (bubukas/sasara nang tama). */
        if (e.target && e.target.closest && e.target.closest('.booking-picker-icon')) return;
        close();
      } catch (err) {}
    }, true);
    document.addEventListener('focusin', function (e) {
      try {
        if (pop.hidden) return;
        if (e.target === input || pop.contains(e.target)) return;
        if (e.target && e.target.dataset && e.target.dataset.customPicker) return;
        if (e.target && e.target.closest && e.target.closest('.booking-picker-icon')) return;
        close();
      } catch (err) {}
    });
  }
};
})(window);
/* B: date popover */
(function (g) {
'use strict';
function make(input) {
  var H = g._BKP; if (!H || !input || input.dataset.customPicker) return null;
  var A = H.A(); if (!A) return null;
  var wrap = input.parentElement;
  /* Icon sa kanan ng input (calendar) — clickable toggle ng date popover.
     Ini-wrap muna ang input sa .booking-input-holder para pantay ang icon
     sa taas ng input. */
  var icon = null;
  try {
    var holder = document.createElement('span');
    holder.className = 'booking-input-holder';
    wrap.insertBefore(holder, input);
    holder.appendChild(input);
    icon = document.createElement('span');
    icon.className = 'booking-picker-icon';
    icon.setAttribute('data-custom-picker', 'date-icon');
    icon.setAttribute('role', 'button');
    icon.setAttribute('tabindex', '0');
    icon.setAttribute('aria-label', 'Open date picker');
    icon.innerHTML = '<i class="far fa-calendar-days" aria-hidden="true"></i>';
    holder.appendChild(icon);
  } catch (e) { icon = null; }
  var pop = document.createElement('div');
  pop.className = 'booking-picker-pop';
  pop.setAttribute('role', 'dialog');
  pop.hidden = true;
  /* I-attach sa holder (bandang input mismo) para 6px lang ang agwat sa taas
     ng dropdown — hindi na apektado ng taas ng label/hint/error sa field. */
  var popHost = (holder && holder.parentNode) ? holder : wrap;
  if (popHost) {
    if (getComputedStyle(popHost).position === 'static') popHost.style.position = 'relative';
    popHost.appendChild(pop);
  }
  var vy = 0, vm = 0;
  try {
    var d0 = H.RD(); var b0 = d0 && d0.todayIso ? A.parseLocalDate(d0.todayIso) : new Date();
    vy = b0.getFullYear(); vm = b0.getMonth();
    if (input.value) { var c0 = A.parseLocalDate(input.value); vy = c0.getFullYear(); vm = c0.getMonth(); }
  } catch (e) { var n0 = new Date(); vy = n0.getFullYear(); vm = n0.getMonth(); }
  function close() { pop.hidden = true; }
  function open() { H.closeOthers(pop); render(); pop.hidden = false; }
  function render() {
    var d = H.RD(); pop.innerHTML = '';
    var head = document.createElement('div'); head.className = 'booking-picker-head';
    var pv = document.createElement('button'); pv.type = 'button'; pv.className = 'booking-picker-nav'; pv.textContent = '<';
    var ti = document.createElement('strong'); ti.className = 'booking-picker-title'; ti.textContent = H.MO[vm] + ' ' + vy;
    var nx = document.createElement('button'); nx.type = 'button'; nx.className = 'booking-picker-nav'; nx.textContent = '>';
    head.appendChild(pv); head.appendChild(ti); head.appendChild(nx); pop.appendChild(head);
    try {
      var md = A.parseLocalDate(A.getMinBookableDate(d));
      pv.disabled = (vy < md.getFullYear()) || (vy === md.getFullYear() && vm <= md.getMonth());
    } catch (e) {}
    pv.addEventListener('click', function () { vm--; if (vm < 0) { vm = 11; vy--; } render(); });
    nx.addEventListener('click', function () { vm++; if (vm > 11) { vm = 0; vy++; } render(); });
    var grid = document.createElement('div'); grid.className = 'booking-picker-grid';
    var DOW = ['Mo','Tu','We','Th','Fr','Sa','Su'];
    for (var h = 0; h < DOW.length; h++) { var hh = document.createElement('span'); hh.className = 'booking-picker-dow'; hh.textContent = DOW[h]; grid.appendChild(hh); }
    var bl = (new Date(vy, vm, 1).getDay() + 6) % 7;
    for (var b = 0; b < bl; b++) { var s = document.createElement('span'); s.className = 'booking-picker-blank'; grid.appendChild(s); }
    var dim = new Date(vy, vm + 1, 0).getDate();
    for (var day = 1; day <= dim; day++) { (function (dn) {
      var iso = vy + '-' + String(vm + 1).padStart(2, '0') + '-' + String(dn).padStart(2, '0');
      var rs = ''; try { rs = A.getDateBlockReason(iso, d); } catch (e) {}
      var btn = document.createElement('button'); btn.type = 'button';
      btn.className = 'booking-picker-day'; btn.textContent = String(dn);
      if (iso === input.value) btn.classList.add('is-selected');
      if (!rs) {
        btn.addEventListener('click', function () {
          input.value = iso; H.fire(input); close();
          if (g.BookingPickers) g.BookingPickers.refreshAll();
        });
      } else {
        btn.disabled = true; btn.classList.add('is-disabled');
        if (rs === 'blocked') btn.classList.add('is-blocked');
        else if (rs === 'fully-booked') btn.classList.add('is-full');
        else btn.classList.add('is-past');
        btn.title = H.why(rs, d, iso);
      }
      grid.appendChild(btn);
    })(day); }
    pop.appendChild(grid);
    var ft = document.createElement('div'); ft.className = 'booking-picker-foot';
    ft.textContent = 'Unavailable dates are disabled';
    /* Legend ng kulay — kapareho ng isinasaad sa mga cell:
       pula = unavailable (blocked), dilaw = fully booked. */
    var lg = document.createElement('div');
    lg.className = 'booking-picker-legend';
    lg.innerHTML = '<span><span class="lp-dot lp-blocked"></span>Unavailable</span>' +
                   '<span><span class="lp-dot lp-full"></span>Fully booked</span>';
    ft.appendChild(lg);
    pop.appendChild(ft);
  }
  input.setAttribute('readonly', 'readonly');
  input.dataset.customPicker = 'date';
  input.addEventListener('click', function (e) { e.preventDefault(); if (pop.hidden) open(); else close(); });
  /* WALANG focus auto-open: kapag nag-Shift+Tab papunta sa date mula sa
     calendar, hindi dapat kusang bumukas ang dropdown. */
  input.addEventListener('focus', function () { /* huwag mag auto-open */ });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (pop.hidden) open(); else close(); }
    else e.preventDefault();
  });
  /* Klik/keyboard sa calendar icon = kapareho ng klik sa input (toggle). */
  if (icon) {
    icon.addEventListener('click', function (e) { e.preventDefault(); if (pop.hidden) open(); else close(); });
    icon.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (pop.hidden) open(); else close(); }
      else if (e.key === 'Escape') close();
    });
  }
  H.outsideCloser(pop, input, close);
  return { input: input, render: render, close: close };
}
g._BKP.makeDate = make;
})(window);
