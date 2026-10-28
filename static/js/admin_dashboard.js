/* Dashboard filters update one report and preserve the current document. */
(() => {
    'use strict';
    const root=document.getElementById('dashboardWorkspace');if(!root)return;
    const form=root.querySelector('#dashboardFilters'),results=root.querySelector('#dashboardResults');
    const operations=root.querySelector('#dashboardOperations'),errorBox=root.querySelector('#dashboardError');
    const status=root.querySelector('#dashboardLoadStatus'),refresh=root.querySelector('#dashboardRefresh');
    const analytics=root.querySelector('#dashboardAnalytics'),selects=window.AdminSelects.create(form);
    const motion=matchMedia('(prefers-reduced-motion: reduce)'),charts=new Map();
    const field=name=>form.elements.namedItem(name);
    const number=new Intl.NumberFormat('en-PH'),pesos=new Intl.NumberFormat('en-PH',{style:'currency',currency:'PHP',maximumFractionDigits:2});
    const metrics={bookings:'Bookings',completed_value:'Completed booking value',collections:'Verified collections'};
    let metric='bookings',data,controller,version=0,draft=0;
    let applied=Object.fromEntries(new FormData(form));
    const clockZone='Asia/Manila';
    const clockDate=new Intl.DateTimeFormat('en-PH',{timeZone:clockZone,weekday:'long',month:'long',day:'numeric',year:'numeric'});
    const clockTime=new Intl.DateTimeFormat('en-PH',{timeZone:clockZone,hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true});
    const clockHour=new Intl.DateTimeFormat('en-PH',{timeZone:clockZone,hour:'numeric',hourCycle:'h23'});
    const clockDay=new Intl.DateTimeFormat('en-CA',{timeZone:clockZone,year:'numeric',month:'2-digit',day:'2-digit'});
    let clockRaw='',clockAnchor=Date.now(),clockStarted=performance.now(),greetingPeriod='';
    function updateClock(){
        const raw=operations.querySelector('[data-server-clock]')?.dataset.serverClock;
        if(raw!==clockRaw&&Number.isFinite(Date.parse(raw))){clockRaw=raw;clockAnchor=Date.parse(raw);clockStarted=performance.now();}
        const now=new Date(clockAnchor+performance.now()-clockStarted),hour=Number(clockHour.format(now));
        const period=hour>=5&&hour<12?'morning':hour>=12&&hour<18?'afternoon':'evening';
        if(period!==greetingPeriod){
            greetingPeriod=period;root.querySelector('[data-greeting]').textContent=`Good ${period}`;
            root.querySelector('[data-greeting-symbol]').innerHTML=period==='evening'
                ?'<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>'
                :'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>';
        }
        const date=root.querySelector('[data-dashboard-date]'),time=root.querySelector('[data-dashboard-time]');
        date.textContent=clockDate.format(now);date.dateTime=clockDay.format(now);
        time.textContent=clockTime.format(now);time.dateTime=now.toISOString();
    }
    function message(text=''){errorBox.textContent=text;errorBox.hidden=!text;}
    function palette(){const style=getComputedStyle(root);return Object.fromEntries(['blue','green','teal','red','amber','muted','ink','bg','line'].map(key=>[key,style.getPropertyValue('--ac-'+key).trim()]));}
    function presets(value){root.querySelectorAll('[data-period]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.period===value)));}
    function sync(filters,keepDraft=false){
        applied=filters;
        for(const name of ['date_basis','event_type','filter_preset'])field(name).value=filters[name]||'';
        if(!keepDraft){field('start_date').value=filters.start_date;field('end_date').value=filters.end_date;presets(filters.filter_preset);}
        selects.sync();
    }
    function currentParams(){return new URLSearchParams(applied);}
    function controlParams(){
        const params=currentParams();
        for(const name of ['date_basis','event_type'])params.set(name,field(name).value);
        return params;
    }
    function options(p,animate){return {responsive:true,maintainAspectRatio:false,
        animation:{duration:animate&&!motion.matches?620:0,easing:'easeOutQuart'},
        interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{displayColors:false,
            backgroundColor:p.ink,titleColor:p.bg,bodyColor:p.bg,padding:12,cornerRadius:8}},
        scales:{x:{grid:{display:false},border:{display:false},ticks:{color:p.muted,font:{size:10},maxTicksLimit:7,maxRotation:0}},
            y:{beginAtZero:true,border:{display:false},grid:{color:p.line,drawTicks:false},ticks:{color:p.muted,font:{size:10},precision:0,maxTicksLimit:6}}}};}
    function plot(key,config,animate){
        const canvas=results.querySelector(`[data-chart="${key}"]`),existing=charts.get(key);
        if(existing&&existing.canvas===canvas){existing.data=config.data;existing.options=config.options;existing.update(animate&&!motion.matches?undefined:'none');}
        else{existing?.destroy();charts.set(key,new Chart(canvas,config));}
    }
    function trendTable(){
        const host=results.querySelector('[data-trend-table]'),trend=data.trend;
        const table=document.createElement('table'),head=table.createTHead().insertRow();
        ['Selected dates',metrics[metric],...(trend.has_comparison?['Previous dates',metrics[metric]]:[])].forEach(label=>{const cell=document.createElement('th');cell.scope='col';cell.textContent=label;head.append(cell);});
        const body=table.createTBody(),series=trend.series[metric],format=value=>metric==='bookings'?number.format(value):pesos.format(value);
        trend.ranges.forEach((range,index)=>{
            const row=body.insertRow();[range,format(series.current[index]),...(trend.has_comparison?[trend.previous_ranges[index]||'No matching interval',series.previous[index]==null?'No matching interval':format(series.previous[index])]:[])].forEach(text=>row.insertCell().textContent=text);
        });host.replaceChildren(table);
    }
    function draw(animate=false){
        data=JSON.parse(results.querySelector('#dashboardChartData').textContent);
        root.querySelectorAll('[data-trend]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trend===metric)));
        const caption=results.querySelector('[data-trend-caption]');
        caption.textContent=metric==='bookings'?'Each point counts bookings by the selected date basis. Previous dates are aligned within each period.':metric==='completed_value'?'Saved value of completed bookings, grouped by the selected booking date basis. This is not a receipt-date or profit report.':'Verified payments applied to the selected bookings, grouped by the booking date basis, regardless of payment date.';
        trendTable();
        for(const [key,chart] of charts)if(!results.querySelector(`[data-chart="${key}"]`)){chart.destroy();charts.delete(key);}
        if(!window.Chart){status.textContent='Charts unavailable. View the trend data and status totals below.';return;}
        Chart.defaults.font.family=getComputedStyle(root).fontFamily;
        const p=palette(),trend=data.trend,series=trend.series[metric];
        if(results.querySelector('[data-chart="trend"]')){
            const config=options(p,animate),accent=metric==='bookings'?p.blue:metric==='completed_value'?p.green:p.teal;
            config.scales.x.offset=trend.labels.length===1;
            config.scales.y.ticks.callback=value=>metric==='bookings'?number.format(value):pesos.format(value);
            config.plugins.tooltip.callbacks={title:items=>trend.ranges[items[0].dataIndex],
                label:item=>`${item.dataset.label}: ${metric==='bookings'?number.format(item.parsed.y):pesos.format(item.parsed.y)}`,
                afterLabel:item=>item.datasetIndex===1?trend.previous_ranges[item.dataIndex]:''};
            const datasets=[{label:'Selected period',data:series.current,borderColor:accent,backgroundColor:accent+'14',fill:true,
                borderWidth:2,tension:.22,pointRadius:trend.labels.length>18?0:3,pointHoverRadius:5,pointBackgroundColor:accent}];
            if(trend.has_comparison)datasets.push({label:'Previous period',data:series.previous,borderColor:p.muted,
                borderWidth:1.5,borderDash:[4,5],tension:.22,pointRadius:trend.labels.length>18?0:2,pointHoverRadius:4});
            plot('trend',{type:'line',data:{labels:trend.labels,datasets},options:config},animate);
            results.querySelector('.ar-trend-key i').style.borderColor=accent;
        }
        if(results.querySelector('[data-chart="status"]')){
            const config=options(p,animate);delete config.scales;config.cutout='78%';config.interaction={mode:'nearest',intersect:true};
            config.plugins.tooltip.callbacks={label:item=>`${item.label}: ${number.format(item.raw)} (${data.statuses[item.dataIndex].share}%)`};
            plot('status',{type:'doughnut',data:{labels:data.statuses.map(row=>row.label),datasets:[{
                data:data.statuses.map(row=>row.count),backgroundColor:data.statuses.map(row=>p[row.color]),
                borderColor:p.bg,borderWidth:3,borderRadius:4,hoverOffset:3}]},options:config},animate);
        }
    }
    function replaceResults(html){
        const template=document.createElement('template');template.innerHTML=html;
        for(const [key,chart] of charts){
            const next=template.content.querySelector(`[data-chart-frame="${key}"]`);
            if(!next)continue;
            const old=chart.canvas.parentElement,newCenter=next.querySelector('.ar-donut-center');
            if(newCenter)old.querySelector('.ar-donut-center')?.replaceWith(newCenter);
            next.replaceWith(old);
        }
        results.replaceChildren(template.content);results.dataset.refresh='true';
    }
    async function load(params,push=true){
        controller?.abort();const current=controller=new AbortController(),requestID=++version,atDraft=draft;
        const timeout=setTimeout(()=>current.abort(),20000);
        const url=new URL(root.dataset.dashboardUrl,location.origin);url.search=params.toString();
        selects.close();message();status.textContent='Updating dashboard...';results.setAttribute('aria-busy','true');
        try{
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:current.signal,
                headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest'}});
            if(response.redirected)throw new Error('Your session ended. Please sign in again.');
            const result=await response.json().catch(()=>({}));
            if(!response.ok)throw new Error(result.error||'The dashboard could not be updated. Please try again.');
            if(!result.html||!result.operations_html||!result.filters)throw new Error('The server returned an incomplete dashboard. Please try again.');
            if(requestID!==version)return;
            sync(result.filters,atDraft!==draft);
            if(operations.contains(document.activeElement))refresh.focus({preventScroll:true});
            operations.innerHTML=result.operations_html;updateClock();replaceResults(result.html);analytics.href=result.analytics_url;draw(true);
            const actual=new URL(root.dataset.dashboardUrl,location.origin);actual.search=new URLSearchParams(applied).toString();
            if(push&&actual.href!==location.href)history.pushState({},'',actual);else history.replaceState({},'',actual);
            status.textContent=`Updated ${result.updated} (PH time)`;
        }catch(error){
            if(requestID===version){message(error.name==='AbortError'?'The request took too long. Your current dashboard is still here.':error.message);status.textContent='Showing the last applied report';}
        }finally{clearTimeout(timeout);if(requestID===version)results.setAttribute('aria-busy','false');}
    }
    form.addEventListener('input',event=>{if(event.target.matches('input[type="date"]')){draft++;field('filter_preset').value='';presets('');}});
    form.addEventListener('submit',event=>{
        event.preventDefault();if(!form.reportValidity())return;
        if(field('start_date').value>field('end_date').value){message('The start date cannot be after the end date.');return;}
        const params=new URLSearchParams(new FormData(form));params.delete('filter_preset');load(params);
    });
    form.addEventListener('change',event=>{
        if(event.target.matches('select'))load(controlParams());
    });
    form.addEventListener('click',event=>{
        const preset=event.target.closest('[data-period]'),reset=event.target.closest('[data-dashboard-reset]');
        if(preset||reset){const params=controlParams();params.set('filter_preset',reset?'7days':preset.dataset.period);params.delete('comparison');load(params);}
    });
    refresh.addEventListener('click',()=>load(currentParams(),false));
    root.querySelector('.db-welcome-shortcuts').addEventListener('click',event=>{
        const link=event.target.closest('[data-dashboard-jump]');
        if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
        const target=root.querySelector(link.hash);if(!target)return;
        event.preventDefault();target.tabIndex=-1;target.focus({preventScroll:true});
        target.scrollIntoView({behavior:motion.matches?'instant':'smooth',block:'start'});
    });
    results.addEventListener('click',event=>{const button=event.target.closest('[data-trend]');if(button){metric=button.dataset.trend;draw(true);}});
    window.addEventListener('popstate',()=>{draft++;load(new URLSearchParams(location.search),false);});
    new MutationObserver(()=>draw(false)).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    motion.addEventListener('change',()=>draw(false));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateClock();});
    window.addEventListener('pageshow',updateClock);
    setInterval(()=>{if(!document.hidden)updateClock();},1000);
    selects.enhance();presets(applied.filter_preset);draw(true);updateClock();
})();
