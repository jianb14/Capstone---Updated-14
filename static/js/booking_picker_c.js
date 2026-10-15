/* C+D: time popover + init */
(function (g) {
'use strict';
function makeTime(input, kind, getIso) {
  var H = g._BKP; if (!H || !input || input.dataset.customPicker) return null;
  var A = H.A(); if (!A) return null;
  var wrap = input.parentElement;
  /* Icon sa kanan ng input (clock) — clickable toggle ng time dropdown.
     Ini-wrap muna ang input sa .booking-input-holder para pantay ang icon. */
  var icon = null;
  try {
    var holder = document.createElement('span');
    holder.className = 'booking-input-holder';
    wrap.insertBefore(holder, input);
    holder.appendChild(input);
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
  function close() { pop.hidden = true; }
  function open() {
    /* Kapag walang petsa, unavailable ang date, o walang slots (hal. End bago
       pumili ng Start): HUWAG buksan ang dropdown — hint lang sa footer. */
    if (!slots().length) return;
    H.closeOthers(pop); render(); pop.hidden = false;
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
        : 'Pick a start time first (min 2 hours, until 6:00 PM)';
      pop.appendChild(em);
      return;
    }
    for (var i = 0; i < list.length; i++) { (function (m) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'booking-picker-timeopt';
      b.setAttribute('role', 'option');
      b.textContent = A2.minutesToLabel(m);
      b.dataset.value = A2.minutesToValue(m);
      if (input.value === b.dataset.value) b.classList.add('is-selected');
      b.addEventListener('click', function () {
        input.value = b.dataset.value; H.fire(input); close();
        if (g.BookingPickers) g.BookingPickers.refreshAll();
      });
      pop.appendChild(b);
    })(list[i]); }
  }
  try { input.setAttribute('type', 'text'); } catch (e) {}
  input.setAttribute('readonly', 'readonly');
  input.setAttribute('inputmode', 'none');
  input.dataset.customPicker = 'time-' + kind;
  input.setAttribute('aria-haspopup', 'listbox');
  input.placeholder = input.placeholder || (kind === 'start' ? 'Select start' : 'Select end');
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
  input.addEventListener('click', function (e) { e.preventDefault(); if (pop.hidden) open(); else close(); syncHint(); });
  /* WALANG focus auto-open — ang nagiging sanhi ng "may nakalabas agad".
     Bubukas lang kapag click/Enter/Space na may laman ang slots. */
  input.addEventListener('focus', function () { syncHint(); });
  input.addEventListener('blur', function () { setTimeout(syncHint, 150); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (pop.hidden) open(); else close(); }
    else e.preventDefault();
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
  H.outsideCloser(pop, input, function () { close(); syncHint(); }, { syncHint: syncHint });
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
