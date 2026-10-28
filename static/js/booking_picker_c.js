/* C+D: time popover + init */
(function (g) {
'use strict';
function makeTime(input, kind, getIso) {
  var H = g._BKP; if (!H || !input || input.dataset.customPicker) return null;
  var A = H.A(); if (!A) return null;
  var wrap = input.parentElement;
  // Preserve HH:MM for validation/submission; show a separate AM/PM control.
  var display = document.createElement('input');
  display.type = 'text';
  display.id = input.id + '_display';
  display.className = input.className;
  display.readOnly = true;
  display.setAttribute('inputmode', 'none');
  display.setAttribute('aria-label', kind === 'start' ? 'Start time' : 'End time');
  display.setAttribute('aria-required', 'true');
  display.dataset.customPicker = 'time-' + kind;
  display.placeholder = kind === 'start' ? 'Select start time' : 'Select end time';
  display.setAttribute('aria-describedby', input.id + '_error');
  input.type = 'hidden';
  input.style.display = 'none';
  input.required = false;
  input.focus = function () { display.focus(); };
  function syncDisplay() {
    var mins = A.toMinutes(input.value);
    if (kind === 'end' && mins !== null) {
      var start = document.getElementById(input.id.indexOf('edit_') === 0 ? 'edit_start_time' : 'start_time');
      var sm = A.toMinutes(start ? start.value : '');
      if (sm !== null && mins <= sm) mins += 1440;
    }
    display.value = mins === null ? '' : A.minutesToLabel(mins);
    display.classList.toggle('is-invalid', input.classList.contains('is-invalid'));
  }
  input.addEventListener('change', syncDisplay);
  input.addEventListener('input', syncDisplay);
  if (input.form) input.form.addEventListener('reset', function () { setTimeout(syncDisplay, 0); });
  /* Icon sa kanan ng input (clock) — clickable toggle ng time dropdown.
     Ini-wrap muna ang input sa .booking-input-holder para pantay ang icon. */
  var icon = null;
  try {
    var holder = document.createElement('span');
    holder.className = 'booking-input-holder';
    wrap.insertBefore(holder, input);
    holder.appendChild(input);
    holder.appendChild(display);
    icon = document.createElement('span');
    icon.className = 'booking-picker-icon';
    icon.setAttribute('data-custom-picker', 'time-icon-' + kind);
    icon.setAttribute('role', 'button');
    icon.setAttribute('tabindex', '0');
    icon.setAttribute('aria-label', kind === 'start' ? 'Open start time list' : 'Open end time list');
    icon.innerHTML = '<i class="far fa-clock" aria-hidden="true"></i>';
    holder.appendChild(icon);
  } catch (e) { icon = null; }
  var pop = document.createElement('div');
  pop.className = 'booking-picker-pop booking-picker-time';
  pop.setAttribute('role', 'listbox');
  pop.hidden = true;
  /* I-attach sa holder (bandang input mismo) para 6px lang ang agwat sa taas
     ng dropdown — hindi na apektado ng taas ng label/hint/error sa field. */
  var popHost = (holder && holder.parentNode) ? holder : wrap;
  if (popHost) {
    if (getComputedStyle(popHost).position === 'static') popHost.style.position = 'relative';
    popHost.appendChild(pop);
  }
  function close() { pop.hidden = true; display.setAttribute('aria-expanded', 'false'); }
  function open() {
    /* Kapag walang petsa, unavailable ang date, o walang slots (hal. End bago
       pumili ng Start): HUWAG buksan ang dropdown — hint lang sa footer. */
    if (!slots().length) return;
    H.closeOthers(pop); render(); pop.hidden = false;
    display.setAttribute('aria-expanded', 'true');
  }
  function slots() {
    var d = null; try { d = H.RD(); } catch (e) { return []; }
    if (!d) return [];
    var iso = ''; try { iso = getIso(); } catch (e) {}
    if (!iso || A.isDateUnavailable(iso, d)) return [];
    if (kind === 'start') return A.getAvailableStartSlots(iso, d);
    var sVal = '';
    try {
      var sEl = document.getElementById('start_time');
      sVal = sEl ? sEl.value : '';
      var cur = document.getElementById('edit_start_time');
      if (input.id === 'edit_start_time' || input.id === 'edit_end_time') {
        sVal = cur ? cur.value : '';
      }
    } catch (e) {}
    var sm = A.toMinutes(sVal);
    if (sm === null) return [];
    return A.getAvailableEndSlots(iso, sm, d);
  }
  function render() {
    var A2 = H.A(); pop.innerHTML = '';
    var list = slots();
    if (!list.length) {
      var em = document.createElement('div');
      em.className = 'booking-picker-foot';
      em.textContent = kind === 'start'
        ? 'No available start times for this date'
        : 'Pick a start time first (min 2 hours)';
      pop.appendChild(em);
      return;
    }
    /* Overtime label sa End dropdown: options na lampas sa included hours
       ay may "+₱X" suffix (galing sa SiteSettings overtime rate) — para
       alam ng customer na may dagdag bayad BAGO pa niya piliin ang oras. */
    var otPolicy = null; var otStart = null;
    if (kind === 'end') {
      try { otPolicy = A2.getDurationPolicy(H.RD()); } catch (e) { otPolicy = null; }
      try {
        var otStartEl = (input.id === 'edit_start_time' || input.id === 'edit_end_time')
          ? document.getElementById('edit_start_time')
          : document.getElementById('start_time');
        otStart = A2.toMinutes(otStartEl ? otStartEl.value : '');
      } catch (e) { otStart = null; }
    }
    var lastGroup = '';
    function groupHeading(paid) {
      var heading = document.createElement('div');
      heading.className = 'booking-time-group-label' + (paid ? ' is-overtime' : '');
      heading.setAttribute('role', 'presentation');
      var until = A2.minutesToLabel(otStart + otPolicy.includedMinutes);
      heading.textContent = paid
        ? 'Additional fee · after ' + until
        : 'Included in your package · until ' + until;
      pop.appendChild(heading);
    }
    for (var i = 0; i < list.length; i++) { (function (m) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'booking-picker-timeopt';
      b.setAttribute('role', 'option');
      var optLabel = A2.minutesToLabel(m);
      var otHours = 0;
      if (kind === 'end' && otPolicy && otStart !== null && otStart !== undefined) {
        var durMin = A2.getDurationMinutes(otStart, m);
        if (durMin !== null && durMin > otPolicy.includedMinutes) {
          otHours = Math.ceil((durMin - otPolicy.includedMinutes) / 60);
          optLabel += '  +₱' + (otHours * otPolicy.overtimeRate).toLocaleString('en-PH');
        }
        var group = otHours > 0 ? 'overtime' : 'included';
        if (lastGroup !== group) { groupHeading(otHours > 0); lastGroup = group; }
      }
      b.textContent = optLabel;
      if (otHours > 0) b.classList.add('is-overtime');
      b.dataset.value = A2.minutesToValue(m);
      b.setAttribute('aria-selected', input.value === b.dataset.value ? 'true' : 'false');
      if (input.value === b.dataset.value) b.classList.add('is-selected');
      b.addEventListener('click', async function () {
        close();
        var previous = input.value;
        var originalDate = getIso();
        var startEl = document.getElementById(input.id.indexOf('edit_') === 0 ? 'edit_start_time' : 'start_time');
        var originalStart = startEl ? startEl.value : '';
        if (otHours > 0 && otPolicy.overtimeRate > 0 && previous !== b.dataset.value) {
          var fee = otHours * otPolicy.overtimeRate;
          var message = 'Your package includes time until ' + A2.minutesToLabel(otStart + otPolicy.includedMinutes)
            + '. Ending at ' + A2.minutesToLabel(m) + ' has a total overtime fee of ₱' + fee.toLocaleString('en-PH')
            + ' (' + otHours + ' billable hour(s) × ₱' + otPolicy.overtimeRate.toLocaleString('en-PH')
            + '). Each started overtime hour is charged in full. This is the overtime amount in your updated booking total.';
          var confirmed;
          if (g.Swal && typeof g.Swal.fire === 'function') {
            var result = await g.Swal.fire({
              title: 'Extend your booking?', text: message, icon: 'info',
              showCancelButton: true, confirmButtonText: 'Confirm +₱' + fee.toLocaleString('en-PH'),
              cancelButtonText: previous ? 'Keep previous time' : 'Choose another time', focusCancel: true, returnFocus: false,
              customClass: { popup: 'app-dialog-popup' }
            });
            confirmed = result.isConfirmed;
          } else {
            confirmed = g.confirm(message);
          }
          if (!confirmed) { display.focus(); return; }
          // Discard a confirmation if the underlying date/start changed meanwhile.
          if (getIso() !== originalDate || (startEl && startEl.value !== originalStart)) return;
        }
        input.value = b.dataset.value;
        input.dataset.overtimeConfirmed = otHours > 0 ? '1' : '';
        syncDisplay(); H.fire(input);
        if (g.BookingPickers) g.BookingPickers.refreshAll();
        display.focus();
      });
      pop.appendChild(b);
    })(list[i]); }
    /* 📌 End-dropdown footer: ipakita ang included window + overtime rate —
       hal. "Beyond 10:00 AM = overtime (+₱500/hr)" — kahit hindi pa nagse-select. */
    if (kind === 'end' && otPolicy && otStart !== null) {
      try {
        var _ft = document.createElement('div');
        _ft.className = 'booking-picker-foot';
        var _until = otStart + (otPolicy.includedMinutes || 180);
        var _uh = Math.floor((_until % (24 * 60)) / 60);
        var _um = _until % 60;
        var _suf = _uh >= 12 ? 'PM' : 'AM';
        var _h12 = _uh % 12 || 12;
        var _untilLbl = _h12 + ':' + String(_um).padStart(2, '0') + ' ' + _suf;
        var _rate = otPolicy.overtimeRate;
        _ft.textContent = 'Beyond ' + _untilLbl + ' = overtime (+₱' + Number(_rate).toLocaleString('en-PH') + '/hr)';
        pop.appendChild(_ft);
      } catch (e) { /* footer optional lang */ }
    }
  }
  input.dataset.customPicker = 'time-' + kind;
  display.setAttribute('aria-haspopup', 'listbox');
  display.setAttribute('aria-expanded', 'false');
  /* Foot hint: paliwanag kung bakit hindi nagbubukas ang dropdown —
     walang laman kapag walang date o walang start (para sa End). */
  function hintMsg() {
    var d = null; try { d = H.RD(); } catch (e) {}
    var iso = ''; try { iso = getIso(); } catch (e) {}
    if (!iso) return 'Pick an event date first';
    try { if (A.isDateUnavailable(iso, d)) return 'This date is unavailable'; } catch (e) {}
    if (kind === 'end') return 'Pick a start time first';
    return 'No available times for this date';
  }
  function syncHint() {
    syncDisplay();
    try {
      /* Gamitin ang original wrap (hindi ang bagong .booking-input-holder)
         para sa ilalim pa rin ng input lilitaw ang hint. */
      var w = wrap;
      var hint = w ? w.querySelector('.booking-picker-timehint') : null;
      if (!hint) {
        hint = document.createElement('small');
        hint.className = 'booking-picker-timehint';
        if (w) w.appendChild(hint);
      }
      if (hint) {
        if (pop.hidden && !slots().length) {
          hint.textContent = hintMsg();
          hint.style.display = '';
        } else {
          hint.textContent = '';
          hint.style.display = 'none';
        }
      }
    } catch (e) {}
  }
  display.addEventListener('click', function (e) { e.preventDefault(); if (pop.hidden) open(); else close(); syncHint(); });
  /* WALANG focus auto-open — ang nagiging sanhi ng "may nakalabas agad".
     Bubukas lang kapag click/Enter/Space na may laman ang slots. */
  display.addEventListener('focus', function () { syncHint(); });
  display.addEventListener('blur', function () { setTimeout(syncHint, 150); });
  display.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (pop.hidden) open(); else close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); open(); var first = pop.querySelector('button'); if (first) first.focus(); }
    setTimeout(syncHint, 0);
  });
  /* Icon toggle: isara muna ang ibang dropdown bago buksan ang sarili —
     kahit walang slots ang napindot, hindi maiiwan ang ibang pop. */
  function toggleFromIcon() {
    H.closeOthers(pop);
    if (pop.hidden) open(); else close();
    syncHint();
  }
  if (icon) {
    icon.addEventListener('click', function (e) { e.preventDefault(); toggleFromIcon(); });
    icon.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleFromIcon(); }
      else if (e.key === 'Escape') { close(); syncHint(); }
    });
  }
  pop.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); display.focus(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      var buttons = Array.prototype.slice.call(pop.querySelectorAll('button'));
      var index = buttons.indexOf(document.activeElement);
      if (buttons.length) buttons[(index + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
    }
  });
  H.outsideCloser(pop, display, function () { close(); syncHint(); }, { syncHint: syncHint });
  setTimeout(syncHint, 0);
  return { input: input, render: render, close: close, kind: kind, syncHint: syncHint };
}
g._BKP.makeTime = makeTime;
var groups = [];
function byId(id) { return document.getElementById(id); }
function refresh(gr) {
  var H = g._BKP; if (!H) return;
  var A = H.A(); if (!A) return;
  var d = null; try { d = A.readData(); } catch (e) { return; }
  if (!d) return;
  var dateEl = byId(gr.dateId);
  if (!dateEl) return;
  var iso = dateEl.value || '';
  if (iso) { try { dateEl.setAttribute('min', A.getMinBookableDate(d)); } catch (e) {} }
  var bad = iso ? A.isDateUnavailable(iso, d) : false;
  var sEl = byId(gr.startId), eEl = byId(gr.endId);
  if (bad) {
    if (sEl && sEl.value) { sEl.value = ''; H.fire(sEl); }
    if (eEl && eEl.value) { eEl.value = ''; H.fire(eEl); }
  }
  /* Kapag nagbago ang date: isara ang lahat ng bukas na popover (stale slots)
     at i-refresh ang time hints ("Pick an event date first", etc.). */
  try { H.closeOthers(null); } catch (e) {}
  try {
    var arr = (H.pops || []);
    for (var i = 0; i < arr.length; i++) {
      try {
        if (arr[i] && arr[i].extra && typeof arr[i].extra.syncHint === 'function') arr[i].extra.syncHint();
      } catch (e2) {}
    }
  } catch (e) {}
}
function init(cfg) {
  var H = g._BKP; if (!H || !H.makeDate || !H.makeTime) return null;
  var dateEl = byId(cfg.dateId);
  var sEl = byId(cfg.startId);
  var eEl = byId(cfg.endId);
  if (!dateEl) return null;
  try { H.makeDate(dateEl); } catch (e) {}
  var getIso = function () { return dateEl.value || ''; };
  try { if (sEl) H.makeTime(sEl, 'start', getIso); } catch (e) {}
  try { if (eEl) H.makeTime(eEl, 'end', getIso); } catch (e) {}
  var gr = { dateId: cfg.dateId, startId: cfg.startId, endId: cfg.endId };
  groups.push(gr);
  var ownerRoot = dateEl.closest('[data-account-page]');
  AccountPages.cleanup(function () {
    groups = groups.filter(function (item) { return item !== gr; });
    H.pops = H.pops.filter(function (item) { return !ownerRoot || !ownerRoot.contains(item.pop); });
  });
  dateEl.addEventListener('change', function () { refresh(gr); });
  if (sEl) sEl.addEventListener('change', function () { refresh(gr); });
  refresh(gr);
  return gr;
}
g.BookingPickers = {
  init: init, refresh: refresh,
  refreshAll: function () { for (var i = 0; i < groups.length; i++) refresh(groups[i]); }
};
})(window);
