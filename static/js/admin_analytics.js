(() => {
  'use strict';
  const root = document.getElementById('analyticsWorkspace');
  if (!root) return;
  const form = root.querySelector('#analyticsFilters');
  const results = root.querySelector('#analyticsResults');
  const errorBox = root.querySelector('#analyticsError');
  const loadStatus = root.querySelector('#analyticsLoadStatus');
  const exportLink = root.querySelector('#analyticsExport');
  const excelLink = root.querySelector('#analyticsExcel');
  const dateReset = form.querySelector('[data-date-reset]');
  const selects = window.AdminSelects?.create(form);
  selects?.enhance();
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const metrics = {bookings: 'Bookings', completed_value: 'Completed booking value', collections: 'Verified collections'};
  const number = new Intl.NumberFormat('en-PH');
  const pesos = new Intl.NumberFormat('en-PH', {style: 'currency', currency: 'PHP', maximumFractionDigits: 2});
  let metric = 'bookings', data, controller, requestNumber = 0, layoutFrame = 0;
  const charts = new Map();
  let appliedFilters = Object.fromEntries(new FormData(form));
  const field = name => form.elements.namedItem(name);
  const readData = () => JSON.parse(results.querySelector('#analyticsChartData').textContent);
  const colors = () => {
    const style = getComputedStyle(root);
    return Object.fromEntries(['blue','green','teal','red','amber','muted','ink','bg','line'].map(key => [key, style.getPropertyValue('--ac-' + key).trim()]));
  };
  const format = value => metric === 'bookings' ? number.format(value) : pesos.format(value);
  function presetState(value) {
    root.querySelectorAll('[data-period]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.period === value)));
  }
  function dateResetParams(filters) {
    return new URLSearchParams({date_basis:filters.date_basis,event_type:filters.event_type,
      tab:filters.tab,filter_preset:'30days'});
  }
  function plot(key, specification, animate) {
    const canvas=results.querySelector(`[data-chart="${key}"]`), existing=charts.get(key);
    if (existing && existing.canvas===canvas) {
      existing.data=specification.data;
      existing.options=specification.options;
      existing.update(animate && !motion.matches ? undefined : 'none');
    } else {
      existing?.destroy(); charts.set(key,new Chart(canvas,specification));
    }
  }
  function layoutCards() {
    layoutFrame=0;
    results.querySelectorAll('.ar-chart-grid').forEach(grid=>{
      grid.classList.add('ar-masonry');
      const columns=Number(getComputedStyle(grid).getPropertyValue('--ar-columns')) || 2;
      const cards=[...grid.children];
      cards.forEach((card,index)=>{
        const full=columns===1 || (cards.length%2===1 && index===cards.length-1);
        card.style.gridColumn=full ? '1 / -1' : String(index%2+1);
        card.style.gridRowEnd=`span ${Math.ceil(card.getBoundingClientRect().height+18)}`;
      });
    });
  }
  function scheduleLayout() { if(!layoutFrame)layoutFrame=requestAnimationFrame(layoutCards); }
  const cardObserver=new ResizeObserver(scheduleLayout);
  function observeCards() {
    cardObserver.disconnect();
    results.querySelectorAll('.ar-chart-grid,.ar-chart-card').forEach(card=>cardObserver.observe(card));
    layoutCards();
  }
  function replaceResults(html) {
    const template=document.createElement('template');template.innerHTML=html;
    // Keep the chart canvas and its observed parent so Chart.js can animate
    // from the currently drawn values instead of restarting every filter.
    template.content.querySelectorAll('[data-chart]').forEach(canvas=>{
      const chart=charts.get(canvas.dataset.chart);
      if(!chart)return;
      const oldFrame=chart.canvas.parentElement, newFrame=canvas.parentElement;
      const oldCenter=oldFrame.querySelector('.ar-donut-center'),newCenter=newFrame.querySelector('.ar-donut-center');
      if(oldCenter && newCenter)oldCenter.replaceWith(newCenter);
      newFrame.replaceWith(oldFrame);
    });
    cardObserver.disconnect();results.replaceChildren(template.content);results.dataset.refresh='true';
  }
  function trendTable() {
    const host = results.querySelector('[data-trend-table]');
    if (!host) return;
    const table = document.createElement('table');
    const head = table.createTHead().insertRow();
    ['Selected dates', metrics[metric], ...(data.trend.has_comparison ? ['Previous dates', metrics[metric]] : [])].forEach(text => {
      const th = document.createElement('th'); th.scope = 'col'; th.textContent = text; head.append(th);
    });
    const body = table.createTBody(), series = data.trend.series[metric];
    data.trend.ranges.forEach((range, index) => {
      const row = body.insertRow();
      [range, format(series.current[index]), ...(data.trend.has_comparison ? [data.trend.previous_ranges[index] || 'No matching interval', series.previous[index] == null ? '—' : format(series.previous[index])] : [])].forEach(text => {
        row.insertCell().textContent = text;
      });
    });
    host.replaceChildren(table);
  }
  function options(palette, animate) {
    return {responsive: true, maintainAspectRatio: false, color: palette.muted,
      animation: {duration: animate && !motion.matches ? 620 : 0, easing: 'easeOutQuart'},
      interaction: {mode: 'index', intersect: false},
      plugins: {legend: {display: false}, tooltip: {backgroundColor: palette.ink, titleColor: palette.bg,
        bodyColor: palette.bg, padding: 12, cornerRadius: 8, displayColors: false}},
      scales: {x: {grid: {display: false}, border: {display: false}, ticks: {color: palette.muted, font: {size: 10}, maxTicksLimit: 8, maxRotation: 0}},
        y: {beginAtZero: true, border: {display: false}, grid: {color: palette.line, drawTicks: false},
          ticks: {color: palette.muted, padding: 9, font: {size: 10}, precision: 0}}}};
  }
  function makeCharts(animate = true) {
    for(const [key,chart] of charts) {
      if(results.querySelector(`[data-chart="${key}"]`)!==chart.canvas){chart.destroy();charts.delete(key);}
    }
    results.querySelectorAll('[data-trend]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.trend === metric)));
    const caption = results.querySelector('[data-trend-caption]');
    if (caption) caption.textContent = metric === 'bookings' ? 'Each point counts bookings in that date interval. Previous dates are aligned by day within each period.'
      : metric === 'completed_value' ? 'Final prices of completed bookings, grouped by the selected booking date basis. Amounts are in Philippine pesos.'
        : 'Verified payments credited to these bookings, grouped by the selected booking date basis, regardless of payment date. Amounts are in Philippine pesos.';
    trendTable();
    if (!window.Chart) { loadStatus.textContent = 'Charts unavailable. Use View data below each graph.'; return; }
    Chart.defaults.font.family = getComputedStyle(root).fontFamily;
    const p = colors(), canvas = key => results.querySelector(`[data-chart="${key}"]`);
    if (canvas('trend')) {
      const trend = data.trend, series = trend.series[metric], config = options(p, animate);
      config.scales.x.offset = trend.labels.length === 1;
      const accent = metric === 'bookings' ? p.blue : metric === 'completed_value' ? p.green : p.teal;
      config.scales.y.ticks.callback = value => metric === 'bookings' ? number.format(value) : '₱' + number.format(value);
      config.plugins.tooltip.callbacks = {
        title: items => trend.ranges[items[0].dataIndex],
        label: context => `${context.dataset.label}: ${format(context.parsed.y)}`,
        afterLabel: context => context.datasetIndex === 1 ? trend.previous_ranges[context.dataIndex] : ''};
      const datasets = [{label: 'Selected period', data: series.current, borderColor: accent, borderWidth: 2,
        pointRadius: trend.labels.length > 14 ? 0 : 3, pointHoverRadius: 5, pointBackgroundColor: accent,
        tension: .25, fill: true, backgroundColor: context => {
          const area = context.chart.chartArea;
          if (!area) return 'transparent';
          const gradient = context.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
          gradient.addColorStop(0, accent + '22'); gradient.addColorStop(1, accent + '00'); return gradient;
        }}];
      if (trend.has_comparison) datasets.push({label: 'Previous period', data: series.previous,
        borderColor: p.muted, borderWidth: 1.5, borderDash: [4,5], pointRadius: trend.labels.length > 14 ? 0 : 2.5,
        pointBackgroundColor: p.muted, pointHoverRadius: 4, tension: .25});
      plot('trend', {type: 'line', data: {labels: trend.labels, datasets}, options: config},animate);
      results.querySelector('.ar-trend-key i').style.borderColor = accent;
    }
    if (canvas('status')) {
      const config = options(p, animate); delete config.scales;
      config.cutout = '78%'; config.interaction = {mode: 'nearest', intersect: true};
      config.plugins.tooltip.callbacks = {label: item => `${item.label}: ${number.format(item.raw)} (${data.statuses[item.dataIndex].share}%)`};
      plot('status', {type: 'doughnut', data: {labels: data.statuses.map(row => row.label),
        datasets: [{data: data.statuses.map(row => row.count), backgroundColor: data.statuses.map(row => p[row.color]),
          borderColor: p.bg, borderWidth: 3, borderRadius: 4, hoverOffset: 3}]}, options: config},animate);
    }
    const insights = data.insights;
    const chartRows = {events:data.events, setups:data.setups, months:insights.months, weekdays:insights.weekdays,
      hours:insights.hours, packages:insights.offers.packages, arches:insights.offers.arches, stands:insights.offers.stands,
      methods:insights.collections.methods, payment_progress:insights.payment_progress,
      customer_types:insights.customers.types, ratings:insights.customers.ratings};
    if (results.querySelector('[data-receipt-table]')) receiptTable(insights.collections.trend);
    if (canvas('receipts')) {
      const receipt = insights.collections.trend, config = options(p,animate);
      config.scales.x.offset = receipt.labels.length === 1;
      config.scales.y.ticks.callback = value => '₱' + number.format(value);
      config.plugins.tooltip.callbacks = {title:items=>receipt.ranges[items[0].dataIndex],
        label:item=>`${item.dataset.label}: ${pesos.format(item.parsed.y)}`,
        afterLabel:item=>item.datasetIndex===1 ? receipt.previous_ranges[item.dataIndex] : ''};
      const datasets = [{label:'Selected period', data:receipt.current, borderColor:p.teal, backgroundColor:p.teal,
        borderWidth:2, pointRadius:receipt.labels.length>14 ? 0 : 3, tension:.25}];
      if (receipt.previous.length) datasets.push({label:'Previous period', data:receipt.previous,
        borderColor:p.muted, pointBackgroundColor:p.muted, borderWidth:1.5, borderDash:[4,5],
        pointRadius:receipt.labels.length>14 ? 0 : 2.5, tension:.25});
      plot('receipts', {type:'line',data:{labels:receipt.labels,datasets},options:config},animate);
    }
    for (const [key, rows] of Object.entries(chartRows)) {
      if (!canvas(key)) continue;
      const config = options(p, animate), currency = key === 'methods';
      const vertical = ['months','weekdays','hours'].includes(key);
      config.indexAxis = 'y'; config.interaction = {mode: 'nearest', intersect: true};
      config.scales.x = {beginAtZero: true, grid: {color: p.line, drawTicks: false}, border: {display: false}, ticks: {precision: 0, color: p.muted, font: {size: 10}}};
      config.scales.y = {grid: {display: false}, border: {display: false}, ticks: {color: p.muted, font: {size: 10}, callback: index => {
        const label = rows[index].label; return label.length > 24 ? label.slice(0, 22) + '…' : label;
      }}};
      config.plugins.tooltip.callbacks = {title: items => rows[items[0].dataIndex].label,
        label: item => currency ? pesos.format(item.raw) : `${number.format(item.raw)} ${key==='customer_types'?'customers':key==='ratings'?'reviews':'bookings'}`};
      if (currency) config.scales.x.ticks.callback = value => '₱' + number.format(value);
      if (vertical) {
        config.indexAxis = 'x'; config.scales = options(p, animate).scales;
        config.scales.x.ticks.maxTicksLimit = key==='hours' ? 8 : 12;
      }
      canvas(key).parentElement.style.height=vertical?'230px':`${Math.min(310,Math.max(112,rows.length*37+40))}px`;
      plot(key, {type: 'bar', data: {labels: rows.map(row => row.label),
        datasets: [{data: rows.map(row => currency ? Number(row.value) : row.count), backgroundColor: ['events','packages','months','ratings'].includes(key) ? p.blue : p.teal,
          borderRadius: 5, maxBarThickness: 18}]}, options: config},animate);
    }
    observeCards();
  }
  function receiptTable(receipt) {
    const host=results.querySelector('[data-receipt-table]'), table=document.createElement('table');
    const head=table.createTHead().insertRow();
    ['Selected dates','Collections received',...(receipt.previous.length?['Previous dates','Collections received']:[])].forEach(text=>{
      const cell=document.createElement('th');cell.scope='col';cell.textContent=text;head.append(cell);
    });
    const body=table.createTBody();
    receipt.ranges.forEach((range,index)=>{
      const row=body.insertRow();
      [range,pesos.format(receipt.current[index]),...(receipt.previous.length?[receipt.previous_ranges[index]||'No matching interval',receipt.previous[index]==null?'—':pesos.format(receipt.previous[index])]:[])].forEach(text=>row.insertCell().textContent=text);
    });
    host.replaceChildren(table);
  }
  function cancelPending() {
    requestNumber++; controller?.abort(); results.setAttribute('aria-busy','false'); loadStatus.textContent = '';
  }
  function showError(message) { errorBox.textContent = message; errorBox.hidden = false; }
  function validate(params) {
    if (params.get('filter_preset')) return true;
    const start=params.get('start_date'), end=params.get('end_date');
    if (!start || !end) { showError('Enter both a start date and end date.'); return false; }
    if (start > end) { showError('The start date cannot be after the end date.'); return false; }
    return true;
  }
  async function load(params, historyMode = 'push') {
    cancelPending();
    if (!validate(params) && historyMode !== 'restore') return;
    const currentRequest = requestNumber;
    controller = new AbortController(); const activeController = controller;
    const timeout = setTimeout(() => activeController.abort('timeout'), 15000);
    results.setAttribute('aria-busy', 'true'); loadStatus.textContent = 'Updating report…'; errorBox.hidden = true;
    try {
      const url = new URL(root.dataset.reportUrl, location.origin); url.search = params.toString();
      const response = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}, signal: activeController.signal, cache: 'no-store'});
      if (response.redirected || !(response.headers.get('Content-Type') || '').includes('application/json')) throw new Error('Your session may have expired. Sign in again or refresh this page.');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'The report could not be updated. Try again.');
      if (currentRequest !== requestNumber) return;
      const restoreTabFocus = document.activeElement?.matches('[data-report-tab]');
      replaceResults(payload.html); data = readData();
      for (const [key, value] of Object.entries(payload.filters)) field(key).value = value;
      appliedFilters = payload.filters;
      dateReset.href=root.dataset.reportUrl+'?'+dateResetParams(appliedFilters).toString();
      selects?.sync(); presetState(payload.filters.filter_preset); exportLink.href = payload.export_url; excelLink.href = payload.excel_url;
      makeCharts();
      if (restoreTabFocus) results.querySelector(`[data-report-tab="${payload.filters.tab}"]`)?.focus({preventScroll:true});
      url.search = new URLSearchParams(payload.filters).toString();
      if (historyMode === 'push' && url.href !== location.href) history.pushState({}, '', url);
      if (historyMode === 'replace') history.replaceState({}, '', url);
      loadStatus.textContent = 'Report updated';
    } catch (error) {
      if (currentRequest !== requestNumber) return;
      if (!activeController.signal.aborted || activeController.signal.reason === 'timeout') showError(activeController.signal.reason === 'timeout'
        ? 'The report took too long. Try again; the previous report is still displayed.'
        : error instanceof TypeError ? 'Unable to update the report. Check your connection and try again.' : error.message);
      loadStatus.textContent = 'Previous report displayed';
    } finally {
      clearTimeout(timeout);
      if (currentRequest === requestNumber) results.setAttribute('aria-busy', 'false');
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault(); field('filter_preset').value = ''; load(new URLSearchParams(new FormData(form)));
  });
  form.addEventListener('click', event => {
    if (event.target.closest('[data-date-reset]')) {
      if(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button!==0)return;
      event.preventDefault();load(dateResetParams(appliedFilters));return;
    }
    const button = event.target.closest('[data-period]');
    if (!button) return;
    field('filter_preset').value = button.dataset.period;
    load(new URLSearchParams(new FormData(form)));
  });
  form.addEventListener('change', event => {
    if (event.target.matches('select')) load(new URLSearchParams(new FormData(form)));
  });
  form.addEventListener('input', event => {
    if (!event.target.matches('input[type="date"]')) return;
    cancelPending(); field('filter_preset').value = ''; presetState(''); errorBox.hidden = true;
  });
  results.addEventListener('click', event => {
    const tab = event.target.closest('[data-report-tab]');
    if (tab && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0) {
      event.preventDefault();
      if (tab.dataset.reportTab === appliedFilters.tab && !controller?.signal.aborted && results.getAttribute('aria-busy') !== 'true') return;
      const params = new URLSearchParams(appliedFilters);params.set('tab',tab.dataset.reportTab);
      load(params); return;
    }
    const button = event.target.closest('[data-trend]');
    if (!button || metric === button.dataset.trend) return;
    metric = button.dataset.trend; makeCharts();
  });
  window.addEventListener('popstate', () => load(new URLSearchParams(location.search), 'restore'));
  new MutationObserver(() => makeCharts(false)).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  motion.addEventListener('change', () => makeCharts(false));
  window.addEventListener('pagehide', () => { controller?.abort(); });
  data = readData(); presetState(field('filter_preset').value); makeCharts();
})();
