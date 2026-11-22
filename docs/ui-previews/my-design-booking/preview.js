(() => {
  'use strict';
  const paths = {
    check:'m5 12 4 4L19 6', plus:'M12 5v14M5 12h14', close:'m6 6 12 12M18 6 6 18',
    arrow:'M4 12h16m-6-6 6 6-6 6', search:'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    info:'M12 11v6m0-10v.01M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0',
    moon:'M21 12.8A9 9 0 0 1 11.2 3 9 9 0 1 0 21 12.8',
    sun:'M12 3V1m0 22v-2M3 12H1m22 0h-2M4.2 4.2 2.8 2.8m18.4 18.4-1.4-1.4M4.2 19.8l-1.4 1.4M21.2 2.8l-1.4 1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    package:'m3 7 9-5 9 5v10l-9 5-9-5V7m0 0 9 5 9-5m-9 5v10M7.5 4.5l9 5',
    entrance:'M5 21V10a7 7 0 0 1 14 0v11M2 21h6m8 0h6',
    stand:'M7 17V7a5 5 0 0 1 10 0v10H7Zm2 0-2 5m8-5 2 5M9 9h6m-5 3h4',
    edit:'m15 5 4 4M4 20l4-1L21 6a2.8 2.8 0 0 0-4-4L4 15l-1 6',
    dots:'M12 5v.01M12 12v.01M12 19v.01'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.info}"/></svg>`;
  const money = value => '₱' + value.toLocaleString('en-PH', {minimumFractionDigits:2, maximumFractionDigits:2});
  const kinds = {package:'Package', entrance:'Entrance Arch', stand:'Welcome Stand'};
  const designs = [
    {id:'p1',kind:'package',offer:'Package 1-A',name:'Blush birthday setup',price:4799,tone:'rose',updated:6},
    {id:'e1',kind:'entrance',offer:'Entrance Z',name:'Blush entrance arch',price:1500,solo:2500,tone:'rose',updated:5},
    {id:'s1',kind:'stand',offer:'Stand Z',name:'A little birthday welcome',price:1200,tone:'rose',updated:4},
    {id:'p2',kind:'package',offer:'Package 1-B',name:'Something blue',price:5799,tone:'blue',updated:3},
    {id:'e2',kind:'entrance',offer:'Entrance X',name:'A blue garden entrance',price:1800,solo:3000,tone:'blue',updated:2},
    {id:'s2',kind:'stand',offer:'Stand A',name:'Welcome to the celebration',price:1000,tone:'blue',updated:1}
  ];
  const selected = {package:'p1',entrance:null,stand:null};
  let filter = 'all', feedbackTimer, summaryFocus;
  const get = id => document.getElementById(id);
  const find = id => designs.find(d => d.id === id);
  const hasBase = () => Boolean(selected.package || selected.entrance);
  const unitPrice = d => d.kind === 'entrance' && !selected.package ? d.solo : d.price;
  const selectedDesigns = () => Object.values(selected).filter(Boolean).map(find);
  const subtotal = () => selectedDesigns().reduce((sum,d) => sum + unitPrice(d),0);

  function scene(d) {
    const colors = d.tone === 'rose' ? ['#e5bac1','#efdadb','#f8eee8','#d5bc91'] : ['#b3cad4','#d5e0e2','#f6eee3','#c9b691'];
    const balloon = (x,y,r,c) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}" stroke="#ffffff" stroke-opacity=".28" stroke-width=".7"/><ellipse cx="${x-r*.22}" cy="${y-r*.36}" rx="${r*.22}" ry="${r*.1}" fill="#fff" opacity=".28"/>`;
    const cluster = list => list.map(([x,y,r],i) => balloon(x,y,r,colors[i%colors.length])).join('');
    let art;
    if (d.kind === 'package') {
      art = `<ellipse cx="160" cy="209" rx="108" ry="6" fill="#e9e3df"/><path d="M107 204V95a47 47 0 0 1 94 0v109Z" fill="${colors[1]}"/><path d="M174 204v-77a32 32 0 0 1 64 0v77Z" fill="${colors[2]}"/><path d="M79 203v-64a25 25 0 0 1 50 0v64Z" fill="#f8f1eb"/><text x="155" y="123" text-anchor="middle" fill="#916d68" font-family="Georgia,serif" font-size="15" font-style="italic">Happy Birthday</text><text x="155" y="146" text-anchor="middle" fill="#725853" font-family="Georgia,serif" font-size="22">Olivia</text><rect x="164" y="181" width="37" height="25" rx="3" fill="#f6f0e9"/><ellipse cx="182.5" cy="181" rx="18.5" ry="4" fill="#fff9f2"/>${cluster([[95,185,17],[88,160,15],[95,135,17],[97,110,16],[111,89,15],[131,70,15],[156,60,12],[181,65,16],[199,81,13],[93,206,15],[114,202,12],[210,192,11],[220,207,14],[238,203,12],[73,187,11],[81,141,10],[111,63,9],[201,61,9],[214,74,8]])}`;
    } else if (d.kind === 'entrance') {
      art = `<ellipse cx="160" cy="211" rx="94" ry="5" fill="#e9e3df"/><path d="M88 209V104a72 72 0 0 1 144 0v105" fill="none" stroke="#c9b797" stroke-width="3"/><path d="M107 209V111a53 53 0 0 1 106 0v98" fill="none" stroke="#e5d8c4" stroke-width="1.5"/>${cluster([[86,199,18],[84,174,16],[87,149,18],[89,121,16],[99,96,18],[110,74,16],[130,56,16],[153,44,13],[179,45,16],[202,57,15],[222,78,17],[233,101,14],[235,125,15],[233,151,13],[236,174,16],[235,199,19],[64,204,12],[106,208,11],[214,209,12],[255,207,13],[104,48,9],[176,27,8],[248,145,8]])}<text x="160" y="153" text-anchor="middle" fill="#95867b" font-family="Georgia,serif" font-size="14" font-style="italic">a lovely way in</text>`;
    } else {
      art = `<ellipse cx="160" cy="216" rx="58" ry="4" fill="#e9e3df"/><path d="m136 162-12 53m59-53 13 53" stroke="#c9b18a" stroke-width="4"/><path d="M122 177V82a38 38 0 0 1 76 0v95Z" fill="${colors[2]}" stroke="#e0d5c9"/><path d="M129 169V85a31 31 0 0 1 62 0v84Z" fill="none" stroke="#d8c8af" stroke-width=".8"/><text x="160" y="98" text-anchor="middle" fill="#826b61" font-family="Georgia,serif" font-size="19" font-style="italic">Welcome</text><text x="160" y="119" text-anchor="middle" fill="#a28c7d" font-family="Georgia,serif" font-size="11" letter-spacing="0">TO OLIVIA'S</text><text x="160" y="137" text-anchor="middle" fill="#826b61" font-family="Georgia,serif" font-size="14">first birthday</text>${cluster([[120,160,13],[119,180,14],[137,183,11],[101,188,10],[198,68,12],[188,53,10],[207,85,10],[116,199,9]])}`;
    }
    return `<svg class="scene" viewBox="0 0 320 240" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${d.offer} sample canvas design"><rect width="320" height="240" fill="#faf9f7"/>${art}</svg>`;
  }

  function notify(message) {
    clearTimeout(feedbackTimer);
    get('feedback').textContent = message;
    feedbackTimer = setTimeout(() => {get('feedback').textContent = '';}, 6500);
  }

  function buildCards() {
    get('designGrid').innerHTML = designs.map(d => `<article class="design-card" id="card-${d.id}" data-design="${d.id}"><div class="design-image">${scene(d)}<span class="pick-marker" aria-hidden="true">${icon('check')}</span><button type="button" class="icon-button image-menu" data-preview="${d.id}" aria-label="Preview ${d.name}">${icon('dots')}</button><span class="type-tag">${icon(d.kind)}${d.offer}</span></div><div class="design-copy"><h2>${d.name}</h2><p class="design-time">Updated ${7-d.updated} ${d.updated === 6 ? 'hour' : 'hours'} ago</p><div class="readiness">${icon('check')}<span>${d.kind === 'stand' ? 'Design complete' : 'Ready to book'}</span></div><p class="card-price"><strong id="price-${d.id}"></strong><small id="rate-${d.id}"></small></p><div class="card-actions"><button type="button" class="button secondary edit-design" data-edit="${d.id}">Edit</button><button type="button" class="button select-design" id="select-${d.id}" data-select="${d.id}" aria-pressed="false" aria-describedby="hint-${d.id}">Select for Booking</button></div><p class="card-hint" id="hint-${d.id}"></p></div></article>`).join('');
  }

  function renderSummary() {
    get('summarySlots').innerHTML = Object.entries(kinds).map(([kind,label]) => {
      const d = find(selected[kind]);
      if (!d) return `<div class="summary-slot is-empty"><span class="slot-art">${icon(kind)}</span><div class="slot-copy"><p class="slot-empty-name">${label}</p><p class="slot-empty-note">${kind === 'package' ? 'Choose a package design' : kind === 'entrance' ? 'Optional · add an entrance' : hasBase() ? 'Optional · add a welcome stand' : 'Choose a package or entrance first'}</p></div></div>`;
      return `<div class="summary-slot"><span class="slot-art">${scene(d)}</span><div class="slot-copy"><span class="slot-kind">${label}</span><strong class="slot-name">${d.offer}</strong><span class="slot-price">${money(unitPrice(d))}</span>${kind === 'entrance' ? `<span class="slot-rate">${selected.package ? 'With package rate' : 'Solo rate'}</span>` : ''}</div><button type="button" class="remove-slot" data-remove="${kind}" aria-label="Remove ${d.offer}">${icon('close')}</button></div>`;
    }).join('');
    const count = selectedDesigns().length;
    get('selectedCount').textContent = `${count}/3`;
    get('subtotal').textContent = money(subtotal());
    get('mobileSubtotal').textContent = money(subtotal());
    get('mobileCount').textContent = count ? `${count} ${count === 1 ? 'design' : 'designs'} selected` : 'Choose a package or entrance';
    const entrance = find(selected.entrance);
    const savings = entrance && selected.package ? entrance.solo - entrance.price : 0;
    get('pricingNote').classList.toggle('has-savings',savings > 0);
    get('pricingNote').innerHTML = savings > 0 ? `<strong>${money(savings)} less on your entrance.</strong><br>With-package rate applied automatically.` : entrance ? 'Your entrance uses its solo rate.<br>Add a package to use the with-package rate.' : hasBase() ? 'Entrance arches and welcome stands are optional. Add them to complete your setup.' : 'Start with a package or a solo entrance arch. A welcome stand needs either one.';
    get('continueBooking').disabled = !hasBase();
    get('nextStep').textContent = hasBase() ? 'Next: event details' : 'Choose a package or entrance to continue';
    get('clearSelection').disabled = count === 0;
  }

  function render() {
    designs.forEach(d => {
      const active = selected[d.kind] === d.id;
      const duplicate = selected[d.kind] && !active;
      const needsBase = d.kind === 'stand' && !hasBase();
      get(`card-${d.id}`).classList.toggle('is-selected',active);
      const button = get(`select-${d.id}`);
      button.setAttribute('aria-pressed',String(active));
      button.disabled = Boolean(duplicate || needsBase);
      button.textContent = active ? 'Remove from Booking' : duplicate ? `${d.kind === 'package' ? 'Package' : d.kind === 'entrance' ? 'Entrance' : 'Stand'} already selected` : 'Select for Booking';
      get(`price-${d.id}`).textContent = money(unitPrice(d));
      get(`rate-${d.id}`).textContent = d.kind === 'entrance' ? selected.package ? 'with package' : 'solo rate' : d.kind === 'stand' ? 'add-on' : 'package price';
      get(`hint-${d.id}`).textContent = needsBase ? 'Choose a package or entrance arch first.' : duplicate ? `Remove your selected ${d.kind} to choose this design.` : active ? 'Included in your booking selection.' : d.kind === 'stand' ? 'Available with your package or entrance.' : d.kind === 'entrance' ? selected.package ? 'With-package price applied automatically.' : 'Lower entrance rate when booked with a package.' : 'Select one package for your event.';
    });
    renderSummary();
    filterCards();
  }

  function filterCards() {
    const query = get('designSearch').value.trim().toLowerCase();
    const order = [...designs].sort((a,b) => get('sortDesigns').value === 'name' ? a.name.localeCompare(b.name) : get('sortDesigns').value === 'price' ? unitPrice(a)-unitPrice(b) : b.updated-a.updated);
    let count = 0;
    order.forEach(d => {
      const card = get(`card-${d.id}`);
      card.hidden = !((filter === 'all' || filter === d.kind) && `${d.name} ${d.offer} ${kinds[d.kind]}`.toLowerCase().includes(query));
      if (!card.hidden) count++;
      get('designGrid').append(card);
    });
    get('emptyResults').hidden = count > 0;
    get('visibleCount').textContent = `Showing ${count} of ${designs.length} sample designs`;
  }

  function remove(kind) {
    const d = find(selected[kind]);
    selected[kind] = null;
    let message = `${d.offer} removed from your booking.`;
    if (!hasBase() && selected.stand) {
      selected.stand = null;
      message += ' Welcome stand also removed: choose a package or entrance first.';
    } else if (kind === 'package' && selected.entrance) {
      message += ' Your entrance now uses its solo rate.';
    }
    render(); notify(message);
  }

  function closeSummary() {
    get('bookingSummary').classList.remove('is-open');
    get('summaryBackdrop').classList.remove('is-open');
    get('summaryBackdrop').hidden = true;
    get('bookingSummary').removeAttribute('role');
    get('bookingSummary').removeAttribute('aria-modal');
    document.body.style.overflow = '';
    if (summaryFocus) summaryFocus.focus();
  }

  buildCards();
  get('themeToggle').innerHTML = icon('moon');
  get('searchIcon').innerHTML = icon('search');
  get('guideIcon').innerHTML = icon('info');
  get('closeSummary').innerHTML = icon('close');
  get('closeNext').innerHTML = icon('close');
  get('continueIcon').innerHTML = icon('arrow');
  get('mobileArrow').innerHTML = icon('arrow');
  render();

  document.addEventListener('click',event => {
    const select = event.target.closest('[data-select]');
    if (select && !select.disabled) {
      const d = find(select.dataset.select);
      if (selected[d.kind] === d.id) {remove(d.kind);return;}
      if (selected[d.kind] || (d.kind === 'stand' && !hasBase())) return;
      selected[d.kind] = d.id;
      render();
      notify(`${d.offer} added.${d.kind === 'package' && selected.entrance ? ' With-package entrance rate applied.' : ''}`);
    }
    const removeButton = event.target.closest('[data-remove]');
    if (removeButton) {const kind = removeButton.dataset.remove;remove(kind);get('closeSummary').offsetParent ? get('closeSummary').focus() : get('summaryTitle').focus();}
    const filterButton = event.target.closest('[data-filter]');
    if (filterButton) {filter=filterButton.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b === filterButton)));filterCards();}
    if (event.target.closest('[data-edit]')) notify('In the actual system, Edit opens this saved design in your canvas editor.');
    const preview = event.target.closest('[data-preview]');
    if (preview) notify(`${find(preview.dataset.preview).name} · sample canvas preview. Use Select for Booking below.`);
  });
  get('designSearch').addEventListener('input',filterCards);
  get('sortDesigns').addEventListener('change',filterCards);
  get('clearSearch').addEventListener('click',()=>{get('designSearch').value='';filterCards();get('designSearch').focus();});
  get('startEmpty').addEventListener('click',()=>{Object.keys(selected).forEach(k=>selected[k]=null);render();notify('Empty selection. Choose a package or entrance first.');});
  get('clearSelection').addEventListener('click',()=>{Object.keys(selected).forEach(k=>selected[k]=null);render();notify('Booking selection cleared. Your saved designs are kept.');});
  get('showFull').addEventListener('click',()=>{Object.assign(selected,{package:'p1',entrance:'e1',stand:'s1'});render();notify('Example: one package, one entrance, and one stand.');});
  get('createDesign').addEventListener('click',()=>notify('The actual Create New Design picker stays the same. This preview focuses on booking selection.'));
  get('themeToggle').addEventListener('click',()=>{const dark=document.documentElement.dataset.theme!=='dark';document.documentElement.dataset.theme=dark?'dark':'light';get('themeToggle').innerHTML=icon(dark?'sun':'moon');get('themeToggle').setAttribute('aria-label',`Switch to ${dark?'light':'dark'} theme`);});
  get('openSummary').addEventListener('click',()=>{summaryFocus=document.activeElement;get('bookingSummary').classList.add('is-open');get('bookingSummary').setAttribute('role','dialog');get('bookingSummary').setAttribute('aria-modal','true');get('summaryBackdrop').hidden=false;get('summaryBackdrop').classList.add('is-open');document.body.style.overflow='hidden';get('closeSummary').focus();});
  get('closeSummary').addEventListener('click',closeSummary);
  get('summaryBackdrop').addEventListener('click',closeSummary);
  document.addEventListener('keydown',event=>{
    if(!get('bookingSummary').classList.contains('is-open') || get('nextDialog').open)return;
    if(event.key==='Escape'){event.preventDefault();closeSummary();}
    if(event.key==='Tab'){
      const controls=[...get('bookingSummary').querySelectorAll('button:not(:disabled)')].filter(b=>b.offsetParent!==null);
      if(event.shiftKey && document.activeElement===controls[0]){event.preventDefault();controls.at(-1).focus();}
      else if(!event.shiftKey && document.activeElement===controls.at(-1)){event.preventDefault();controls[0].focus();}
    }
  });
  get('continueBooking').addEventListener('click',()=>{
    if(!hasBase())return;
    get('handoffItems').innerHTML=selectedDesigns().map(d=>`<div class="handoff-row"><span>${d.offer}<small>${kinds[d.kind]}${d.kind==='entrance' ? selected.package ? ' · with package rate' : ' · solo rate' : ''}</small></span><strong>${money(unitPrice(d))}</strong></div>`).join('');
    get('handoffTotal').textContent=money(subtotal());
    get('nextDialog').showModal();
  });
  get('closeNext').addEventListener('click',()=>get('nextDialog').close());
  get('backToSelection').addEventListener('click',()=>get('nextDialog').close());
  window.matchMedia('(min-width:981px)').addEventListener('change',event=>{if(event.matches)closeSummary();});
})();
