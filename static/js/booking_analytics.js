/* All cross-filter aggregation is local to the raw date-range rows. */
(function (root) {
  'use strict';
  const STAGES = ['Requested', 'Reviewed', 'Confirmed', 'Completed'];
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const KEYS = ['department', 'weekday', 'roomType', 'stage', 'room', 'status', 'source'];
  const FIELDS = {department:'department', weekday:'weekday', roomType:'room_type', status:'status', source:'source'};
  const PALETTE = ['#007f78', '#72cbb2', '#f4bc54', '#ed8a80', '#8eaab7', '#6094af', '#ac96bc'];

  function stageIndex(row, now = Date.now()) {
    const status = String(row.status || '').toLowerCase();
    if (status === 'completed') return 3;
    if (['confirmed', 'confirmed by admin'].includes(status)) {
      const end = Date.parse(row.ends_at || '');
      return Number.isFinite(end) && end <= now ? 3 : 2;
    }
    return ['reviewed', 'changes_requested', 'hod_approved', 'approved by hod', 'hod_rejected', 'rejected by hod',
      'admin_rejected', 'rejected by admin', 'cancelled'].includes(status) ? 1 : 0;
  }

  function matches(row, filters, skipKey = null, now = Date.now()) {
    const skip = new Set(Array.isArray(skipKey) ? skipKey : [skipKey]);
    return KEYS.every(key => {
      if (skip.has(key) || filters[key] == null) return true;
      if (key === 'stage') return stageIndex(row, now) >= STAGES.indexOf(filters.stage);
      if (key === 'room') return [row.room_key,row.room_name].includes(filters.room);
      return row[FIELDS[key]] === filters[key];
    });
  }

  function matchesReportScope(row, values) {
    const normalize = value => String(value ?? '').trim().toUpperCase();
    return ['campus','building'].every(key => !values[key] || normalize(row[key]) === normalize(values[key])) &&
      (!values.room || [row.room_key,row.room_code].includes(values.room));
  }

  function counts(rows, field) {
    const result = new Map();
    rows.forEach(row => result.set(row[field], (result.get(row[field]) || 0) + 1));
    return result;
  }

  function summarize(rows, now = Date.now()) {
    const confirmed = rows.filter(row => stageIndex(row, now) >= 2).length;
    const peak = [...counts(rows, 'hour')].sort((a,b) => b[1]-a[1] || Number(a[0])-Number(b[0]))[0];
    return {total:rows.length, confirmed, rate:rows.length ? Math.round(confirmed/rows.length*1000)/10 : null,
      peak:peak ? Number(peak[0]) : null};
  }

  function bucket(value, group) {
    if (group === 'month') return value.slice(0,7);
    if (group !== 'week') return value;
    const day = new Date(value+'T00:00:00Z');
    day.setUTCDate(day.getUTCDate()-(day.getUTCDay()+6)%7);
    return day.toISOString().slice(0,10);
  }

  function dateBuckets(start, end, group = 'day') {
    const labels = new Set(), day = new Date(start+'T00:00:00Z'), stop = new Date(end+'T00:00:00Z');
    if (!Number.isFinite(+day) || !Number.isFinite(+stop)) return [];
    for (let i=0; day<=stop && i<366; i++,day.setUTCDate(day.getUTCDate()+1)) labels.add(bucket(day.toISOString().slice(0,10),group));
    return [...labels];
  }

  function trendSeries(items,start,end,group,now=Date.now()) {
    const labels=dateBuckets(start,end,group),total=labels.map(label=>items.filter(row=>bucket(row.date,group)===label).length);
    const confirmed=labels.map(label=>items.filter(row=>bucket(row.date,group)===label&&stageIndex(row,now)>=2).length);
    const average=total.map((value,index)=>{const slice=total.slice(Math.max(0,index-6),index+1);return Math.round(slice.reduce((a,b)=>a+b,0)/slice.length*100)/100;});
    return {labels,total,confirmed,average};
  }
  function durationHours(row){const start=String(row.time||'').split(':').map(Number),end=String(row.end_time||'').split(':').map(Number);return (end[0]*60+end[1]-start[0]*60-start[1])/60;}
  root.BookingAnalyticsCore = {STAGES,WEEKDAYS,KEYS,stageIndex,matches,matchesReportScope,counts,summarize,bucket,dateBuckets,trendSeries,durationHours};
  if (typeof document === 'undefined' || !document.getElementById('booking-analytics')) return;

  const $ = id => document.getElementById(id);
  const page = $('booking-analytics'), rows = JSON.parse($('bookings-data').textContent);
  const filters = Object.fromEntries(KEYS.map(key=>[key,null]));
  const sharedFilters = {};
  const statusLabels = new Map([...$('ba-status').options].filter(item=>item.value).map(item=>[item.value,item.textContent]));
  const sourceLabels = new Map([...$('ba-source').options].filter(item=>item.value).map(item=>[item.value,item.textContent]));
  const charts = {}, reducedMotion = root.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const format = new Intl.NumberFormat(undefined,{maximumFractionDigits:1});
  let selectedRows = [], previousKpis = [], group = 'day';
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }
  function button(text, action, pressed) {
    const element = node('button',text); element.type = 'button';
    if (pressed !== undefined) element.setAttribute('aria-pressed',String(pressed));
    element.addEventListener('click',action); return element;
  }
  const faded = (color,active) => color+(active?'ff':'40');
  const scope = (skip=null,now=Date.now()) => rows.filter(row=>matchesReportScope(row,sharedFilters)&&matches(row,filters,skip,now));
  const hourLabel = hour => hour===null?'-':(hour%12||12)+(hour<12?' AM':' PM');

  function restore() {
    const params = new URLSearchParams(location.search);
    KEYS.forEach(key=>filters[key]=params.get(key)||(key==='roomType'?params.get('room_type'):null)||null);
    for(const key of ['campus','building','room'])sharedFilters[key]=params.get('util_'+key)||'';
    filters.department ||= params.get('util_department') || null;
    if(!statusLabels.has(filters.status))filters.status=null;
    if(!sourceLabels.has(filters.source))filters.source=null;
    if (filters.stage && !STAGES.includes(filters.stage)) filters.stage=null;
    if (filters.weekday && !WEEKDAYS.includes(filters.weekday)) filters.weekday=null;
  }
  function persist() {
    const url = new URL(location.href);
    KEYS.forEach(key=>filters[key]===null?url.searchParams.delete(key):url.searchParams.set(key,filters[key]));
    url.searchParams.delete('room_type');
    url.searchParams.delete('util_department');
    if (page.dataset.start) url.searchParams.set('start',page.dataset.start);
    if (page.dataset.end) url.searchParams.set('end',page.dataset.end);
    history.pushState(null,'',url);
  }
  function toggle(key,value) {filters[key]=filters[key]===value?null:value;persist();render();}

  function renderChips() {
    const box=$('ba-chips');box.replaceChildren();
    const labels={department:'Department',weekday:'Weekday',roomType:'Room type',stage:'Stage',room:'Room',status:'Status',source:'Source'};
    $('ba-status').value=filters.status||'';$('ba-source').value=filters.source||'';
    const active=KEYS.filter(key=>filters[key]!==null);
    box.hidden=!active.length;
    active.forEach(key=>{
      const value=key==='status'?statusLabels.get(filters[key]):key==='source'?sourceLabels.get(filters[key]):key==='room'?(rows.find(row=>row.room_key===filters.room)?.room_name||filters.room):filters[key];
      const chip=button(labels[key]+': '+value+' \u00d7',()=>toggle(key,filters[key]));
      chip.setAttribute('aria-label','Remove '+labels[key]+' filter: '+value);box.append(chip);
    });
    if (active.length) {
      const clear=node('a','Clear all');clear.href='#';
      clear.addEventListener('click',event=>{event.preventDefault();KEYS.forEach(key=>filters[key]=null);persist();render();});box.append(clear);
    }

  }

  function miniChart(values) {
    if (values.length<3) return null;
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),line=document.createElementNS(ns,'polyline');
    svg.setAttribute('viewBox','0 0 260 42');svg.setAttribute('aria-hidden','true');
    const max=Math.max(...values,1);
    line.setAttribute('points',values.map((value,i)=>(i/(values.length-1)*260)+','+(38-value/max*32)).join(' '));
    line.setAttribute('fill','none');line.setAttribute('stroke','#c6ffe2');line.setAttribute('stroke-width','2');svg.append(line);return svg;
  }

  function openMetric(title,description,now) {
    $('ba-metric-title').textContent=title;$('ba-metric-description').textContent=description;
    const content=$('ba-metric-content');content.replaceChildren();
    const summary=summarize(selectedRows,now),list=node('dl');
    [['Date range',page.dataset.start+' to '+page.dataset.end],['Matching bookings',summary.total],
      ['Confirmed + Completed',summary.confirmed],['Confirmation rate',summary.rate===null?'-':summary.rate+'%'],
      ['Peak hour',hourLabel(summary.peak)]].forEach(([label,value])=>{const pair=node('div');pair.append(node('dt',label),node('dd',value));list.append(pair);});
    content.append(list,node('p','These values use all active filters. Close this popup to select chart segments.'));
    if (!$('ba-metric-dialog').open) $('ba-metric-dialog').showModal();
  }

  function renderKpis(now) {
    const summary=summarize(selectedRows,now),labels=['Total bookings','Confirmed','Confirmation rate','Peak hour'];
    const values=[summary.total,summary.confirmed,summary.rate,summary.peak];
    const descriptions=['All matching booking requests','Confirmed and Completed reservations',
      'Confirmed + Completed, divided by matching bookings','Most common start hour; earliest hour wins ties'];
    const box=$('ba-cards');box.replaceChildren();
    labels.forEach((label,index)=>{
      const card=button('',()=>openMetric(label,descriptions[index],now));
      card.className='ba-kpi'+(previousKpis[index]!==undefined&&previousKpis[index]!==values[index]?' ba-kpi-changed':'');
      const value=!summary.total?'-':index===3?hourLabel(values[index]):format.format(values[index])+(index===2?'%':'');
      card.append(node('span',label,'ba-kpi-label'),node('strong',value),node('small',descriptions[index]));
      const dates=[...new Set(selectedRows.map(row=>row.date))].sort();
      const series=dates.map(date=>{const item=summarize(selectedRows.filter(row=>row.date===date),now);return index===0?item.total:index===1?item.confirmed:index===2?item.rate:item.peak;});
      const spark=miniChart(series);if(spark)card.append(spark);
      card.append(node('span','Explore metric \u2197','ba-kpi-link'));box.append(card);
    });previousKpis=values;
  }

  function chartOptions() {
    return {responsive:true,maintainAspectRatio:false,animation:{duration:reducedMotion?0:400},
      plugins:{legend:{display:false},tooltip:{enabled:true}},
      onHover(event,elements,chart){chart.canvas.style.cursor=elements.length?'pointer':'default';},
      scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}}};
  }
  function updateChart(key,type,data,options) {
    if (typeof root.Chart!=='function') return;
    if (!charts[key]) charts[key]=new root.Chart($('ba-'+key+'-chart'),{type,data,options});
    else {charts[key].config.type=type;charts[key].data=data;charts[key].options=options;charts[key].update();}
  }
  function clicked(event,chart) {return chart.getElementsAtEventForMode(event,'nearest',{intersect:true},true)[0];}

  const roomGroup=$('ba-room-group');
  if(roomGroup){
    const daily=JSON.parse($('ba-room-daily').textContent);
    const period=$('ba-room-window-period'), detail=$('ba-room-window-detail');
    const hours=minutes=>Math.round(minutes/60*100)/100;
    const clock=minutes=>String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');
    const dayLabel=value=>new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(value+'T00:00:00Z'));
    const length=day=>day.window_end-day.window_start;
    let grouped=[];
    function describeWindow(index){
      const day=grouped[index]?.longest;
      if(!day)return;
      detail.textContent=length(day)
        ? `${dayLabel(day.date)} · ${clock(day.window_start)}–${clock(day.window_end)} · ${hours(length(day))} h unoccupied`
        : 'No unoccupied time in this period.';
    }
    function renderRoomTrends(){
      const byPeriod=new Map();
      for(const day of daily){
        const key=bucket(day.date,roomGroup.value);
        if(!byPeriod.has(key))byPeriod.set(key,{label:key,occupied:0,capacity:0,longest:day});
        const item=byPeriod.get(key);item.occupied+=day.occupied;item.capacity+=day.capacity;
        if(length(day)>length(item.longest))item.longest=day;
      }
      grouped=[...byPeriod.values()];
      const labels=grouped.map(item=>dayLabel(item.label)), options=chartOptions();
      options.scales.x.stacked=true;options.scales.y.stacked=true;options.scales.y.title={display:true,text:'Hours'};
      options.plugins.legend={display:true,position:'bottom',labels:{usePointStyle:true,boxWidth:8}};
      options.plugins.tooltip={mode:'index',intersect:false};
      updateChart('room-usage','bar',{labels,datasets:[
        {label:'Occupied',data:grouped.map(item=>hours(item.occupied)),backgroundColor:'#007f78'},
        {label:'Unoccupied',data:grouped.map(item=>hours(item.capacity-item.occupied)),backgroundColor:'#9acdbd'},
      ]},options);
      const windowOptions=chartOptions();windowOptions.scales.y.title={display:true,text:'Hours'};
      windowOptions.plugins.tooltip.callbacks={afterLabel:item=>{const day=grouped[item.dataIndex].longest;return length(day)?`${dayLabel(day.date)} · ${clock(day.window_start)}–${clock(day.window_end)}`:'No unoccupied time';}};
      windowOptions.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item){period.value=item.index;describeWindow(item.index);}};
      updateChart('room-window','bar',{labels,datasets:[
        {label:'Longest unoccupied window',data:grouped.map(item=>hours(length(item.longest))),backgroundColor:'#72bba6',borderRadius:4},
      ]},windowOptions);
      period.replaceChildren(...labels.map((label,index)=>new Option(roomGroup.value==='week'?'Week of '+label:label,index)));
      const best=grouped.reduce((index,item,i)=>length(item.longest)>length(grouped[index].longest)?i:index,0);
      period.value=best;
      describeWindow(best);
    }
    if(daily.length>15)roomGroup.value='week';
    roomGroup.addEventListener('change',renderRoomTrends);
    period.addEventListener('change',()=>describeWindow(Number(period.value)));
    renderRoomTrends();
  }

  function showBookings(title,items){
    $('ba-metric-title').textContent=title;$('ba-metric-description').textContent=items.length+' matching bookings';
    const content=$('ba-metric-content');content.replaceChildren();const wrapper=node('div',null,'ba-table-scroll ba-recent-scroll'),table=node('table'),head=node('thead'),header=node('tr');
    ['ID','Date','Time','Room','Faculty','Status'].forEach(label=>header.append(node('th',label)));head.append(header);table.append(head);const body=node('tbody');
    [...items].sort((a,b)=>b.date.localeCompare(a.date)||b.id-a.id).slice(0,50).forEach(row=>{const tr=node('tr');[row.id,row.date,row.time+' - '+row.end_time,row.room_name,row.faculty_name,row.status_label].forEach(value=>tr.append(node('td',value)));body.append(tr);});
    if(!items.length)emptyRow(body,6);table.append(body);wrapper.append(table);content.append(wrapper,node('p','Showing up to 50 matching bookings.'));
    if(!$('ba-metric-dialog').open)$('ba-metric-dialog').showModal();
  }
  function renderTrend() {
    const data=trendSeries(selectedRows,page.dataset.start,page.dataset.end,group),style=$('ba-trend-style')?.value||'line';
    const options=chartOptions();options.interaction={mode:'index',intersect:false};options.plugins.legend={display:true,position:'bottom',labels:{usePointStyle:true,boxWidth:8}};
    options.plugins.tooltip={enabled:true,mode:'index',intersect:false};options.scales.y.title={display:true,text:'Booking requests'};
    options.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)showBookings('Bookings: '+data.labels[item.index],selectedRows.filter(row=>bucket(row.date,group)===data.labels[item.index]&&(item.datasetIndex!==1||stageIndex(row)>=2)));};
    updateChart('trend',style,{labels:data.labels,datasets:[
      {type:style,label:'All requests',data:data.total,borderColor:'#008b7e',backgroundColor:'#008b7e18',fill:style==='line',tension:.3,pointRadius:data.labels.length>60?0:3,borderRadius:4,order:3},
      {type:'line',label:'Confirmed + completed',data:data.confirmed,borderColor:'#72b69c',backgroundColor:'#72b69c',fill:false,tension:.3,pointRadius:2,order:2},
      {type:'line',label:'Moving average (up to 7 periods)',data:data.average,borderColor:'#d49b35',borderDash:[5,4],fill:false,tension:.3,pointRadius:0,order:1}]},options);
    $('ba-trend-summary').textContent=selectedRows.length?selectedRows.length+' matching requests. Click a point to inspect its bookings.':'No bookings match these filters.';
  }
  function renderDemand(now){
    const hours=Array.from({length:24},(_,index)=>index),options=chartOptions();options.plugins.legend={display:true,position:'bottom',labels:{usePointStyle:true,boxWidth:8}};options.scales.x.stacked=true;options.scales.y.stacked=true;options.scales.x.ticks={maxTicksLimit:12};options.scales.y.title={display:true,text:'Bookings'};
    options.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)showBookings('Bookings starting at '+hourLabel(hours[item.index]),selectedRows.filter(row=>Number(row.hour)===hours[item.index]&&(item.datasetIndex===0?stageIndex(row,now)>=2:stageIndex(row,now)<2)));};
    updateChart('demand','bar',{labels:hours.map(hourLabel),datasets:[{label:'Confirmed + completed',data:hours.map(hour=>selectedRows.filter(row=>Number(row.hour)===hour&&stageIndex(row,now)>=2).length),backgroundColor:'#008b7e',borderRadius:3},{label:'Other requests',data:hours.map(hour=>selectedRows.filter(row=>Number(row.hour)===hour&&stageIndex(row,now)<2).length),backgroundColor:'#b1ded0',borderRadius:3}]},options);
    const durations=Array.from({length:8},(_,index)=>index+1),durationOptions=chartOptions();durationOptions.scales.x.title={display:true,text:'Duration in hours'};durationOptions.scales.y.title={display:true,text:'Bookings'};
    durationOptions.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)showBookings(durations[item.index]+' hour bookings',selectedRows.filter(row=>durationHours(row)===durations[item.index]));};
    updateChart('duration','bar',{labels:durations.map(value=>value+'h'),datasets:[{label:'Bookings',data:durations.map(value=>selectedRows.filter(row=>durationHours(row)===value).length),backgroundColor:'#72bba6',borderRadius:5}]},durationOptions);
  }

  function legend(container,labels,key,totals,names=new Map(),colors=PALETTE) {
    container.replaceChildren();labels.forEach((label,index)=>{
      const item=button((names.get(label)||label)+(totals?' ('+(totals.get(label)||0)+')':''),()=>toggle(key,label),filters[key]===label);
      item.style.setProperty('--legend-color',colors[index%colors.length]);
      item.className=filters[key]!==null&&filters[key]!==label?'ba-faded':'';container.append(item);
    });
  }
  function renderStatus(now) {
    const totals=counts(scope('status',now),'status');
    const keys=[...statusLabels.keys()].filter(key=>totals.has(key)||filters.status===key);
    const colors=keys.map(key=>({pending:'#cc860e',changes_requested:'#b47838',hod_approved:'#519d86',confirmed:'#007f78',hod_rejected:'#c75563',admin_rejected:'#a83a4b',cancelled:'#8296a3',withdrawn:'#85928c'})[key]||'#6094af');
    const options=chartOptions();options.indexAxis='y';options.scales.x.ticks={precision:0};
    options.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)toggle('status',keys[item.index]);};
    updateChart('status','bar',{labels:keys.map(key=>statusLabels.get(key)),datasets:[{label:'Requests',data:keys.map(key=>totals.get(key)||0),backgroundColor:colors.map((color,index)=>faded(color,!filters.status||filters.status===keys[index])),borderRadius:4}]},options);
    legend($('ba-status-legend'),keys,'status',totals,statusLabels,colors);
  }
  function renderDepartment(now) {
    const candidates=scope('department',now),totals=counts(candidates,'department');
    const confirmed=counts(candidates.filter(row=>stageIndex(row,now)>=2),'department');
    const ranked=[...totals.keys()].sort((a,b)=>totals.get(b)-totals.get(a)||a.localeCompare(b));
    const labels=ranked.slice(0,8);
    if(totals.has(filters.department)&&!labels.includes(filters.department))labels[labels.length-1]=filters.department;
    const plot=$('ba-department-plot'),summary=$('ba-department-summary');
    plot.hidden=!labels.length;
    plot.style.height=`${Math.max(150,labels.length*31+68)}px`;
    summary.hidden=labels.length>0&&ranked.length<=labels.length;
    summary.textContent=labels.length?'Showing '+labels.length+' of '+ranked.length+' departments by booking volume.':'No departmental bookings match these filters.';
    const options=chartOptions();options.indexAxis='y';
    options.scales.x.stacked=true;options.scales.x.ticks={precision:0};options.scales.y.stacked=true;
    options.plugins.legend={display:true,position:'bottom',labels:{usePointStyle:true,boxWidth:8}};
    options.plugins.tooltip={mode:'index',intersect:false,callbacks:{footer:items=>{
      const total=totals.get(labels[items[0]?.dataIndex])||0;
      return `${total} total ${total===1?'request':'requests'} · ${Math.round(total/candidates.length*100)}% of matching requests`;
    }}};
    options.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)toggle('department',chart.data.labels[item.index]);};
    const colors=color=>labels.map(label=>faded(color,!filters.department||filters.department===label));
    updateChart('department','bar',{labels,datasets:[
      {label:'Confirmed',data:labels.map(label=>confirmed.get(label)||0),backgroundColor:colors('#007f78'),borderRadius:4},
      {label:'Other requests',data:labels.map(label=>totals.get(label)-(confirmed.get(label)||0)),backgroundColor:colors('#9acdbd'),borderRadius:4},
    ]},options);
    legend($('ba-department-legend'),labels,'department',totals,new Map(),['#007f78']);
  }
  function renderWeekday(now) {
    const candidates=scope(['weekday','source'],now),sources=[...sourceLabels.keys()];
    const options=chartOptions();options.scales.x.stacked=true;options.scales.y.stacked=true;
    options.onClick=(event,elements,chart)=>{const item=clicked(event,chart);if(item)toggle('weekday',chart.data.labels[item.index]);};
    updateChart('weekday','bar',{labels:WEEKDAYS,datasets:sources.map((source,index)=>({label:sourceLabels.get(source),
      data:WEEKDAYS.map(day=>candidates.filter(row=>row.weekday===day&&row.source===source).length),
      backgroundColor:WEEKDAYS.map(day=>faded(PALETTE[index],(!filters.weekday||filters.weekday===day)&&(!filters.source||filters.source===source))),borderRadius:3}))},options);
    legend($('ba-source-legend'),sources,'source',counts(candidates,'source'),sourceLabels);legend($('ba-weekday-buttons'),WEEKDAYS,'weekday');
  }

  const funnelButtons=STAGES.map(stage=>{
    const item=button('',()=>toggle('stage',stage),false);item.className='ba-funnel-step';
    item.append(node('span',stage,'ba-funnel-title'),node('span','','ba-funnel-value'),node('i','','ba-funnel-fill'));
    $('ba-funnel').append(item);return item;
  });
  function renderFunnel(now) {
    const candidates=scope('stage',now);
    funnelButtons.forEach((item,index)=>{
      const count=candidates.filter(row=>stageIndex(row,now)>=index).length,percent=candidates.length?Math.round(count/candidates.length*1000)/10:0;
      item.querySelector('.ba-funnel-value').textContent=format.format(count)+' \u00b7 '+percent+'% of first step';
      item.querySelector('.ba-funnel-fill').style.width=percent+'%';item.style.setProperty('--stage-color',PALETTE[index]);
      item.classList.toggle('ba-faded',!!filters.stage&&filters.stage!==STAGES[index]);item.setAttribute('aria-pressed',String(filters.stage===STAGES[index]));
    });
  }
  function emptyRow(body,columns) {const row=node('tr'),cell=node('td','No bookings match these filters.');cell.colSpan=columns;cell.className='ba-empty';row.append(cell);body.append(row);}
  function renderRooms(now) {
    const candidates=scope('room',now),totals=counts(candidates,'room_key');
    const details=new Map(candidates.map(row=>[row.room_key,row]));
    const top=[...totals].sort((a,b)=>b[1]-a[1]||details.get(a[0]).room_name.localeCompare(details.get(b[0]).room_name)).slice(0,10);
    if(details.has(filters.room)&&!top.some(([key])=>key===filters.room))top.push([filters.room,totals.get(filters.room)]);
    const body=$('ba-top-rooms');body.replaceChildren();
    top.forEach(([key,count])=>{
      const booking=details.get(key),selected=filters.room===key||filters.room===booking.room_name;
      const row=node('tr');row.tabIndex=0;row.setAttribute('aria-selected',String(selected));
      row.classList.toggle('ba-selected',selected);row.classList.toggle('ba-faded',!!filters.room&&!selected);
      row.append(node('td',booking.room_name),node('td',[booking.campus,booking.building].filter(Boolean).join(' / ')||'-'),node('td',count));
      const select=()=>toggle('room',selected?filters.room:key);row.addEventListener('click',select);
      row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}});body.append(row);
    });if(!top.length)emptyRow(body,3);
  }
  function renderRecent(now) {
    const body=$('ba-recent-rows');body.replaceChildren();$('ba-recent-heading').textContent='Recent bookings ('+selectedRows.length+')';
    [...selectedRows].sort((a,b)=>b.created_at.localeCompare(a.created_at)||Number(b.id)-Number(a.id)).slice(0,50).forEach(booking=>{
      const row=node('tr');[booking.id,booking.date,(booking.time||String(booking.hour).padStart(2,'0')+':00')+(booking.end_time?' - '+booking.end_time:''),
        booking.room_name,booking.room_type,booking.department,booking.faculty_name].forEach(value=>row.append(node('td',value)));
      const cell=node('td'),stage=stageIndex(booking,now),pill=node('span',stage===3?'Completed':booking.status_label||booking.status,'ba-pill ba-stage-'+stage);
      if(['hod_rejected','admin_rejected','cancelled','withdrawn'].includes(booking.status))pill.classList.add('ba-pill-closed');
      cell.append(pill);row.append(cell);body.append(row);
    });if(!selectedRows.length)emptyRow(body,8);
  }
  function renderList(id,field) {
    const box=$(id);box.replaceChildren();[...counts(selectedRows,field)].sort((a,b)=>b[1]-a[1]).forEach(([label,value])=>{
      const item=node('div',null,'ba-summary-row');item.append(node('span',label),node('strong',value));box.append(item);
    });if(!selectedRows.length)box.append(node('p','No bookings match these filters.','ba-empty'));
  }
  function render() {
    const now=Date.now();selectedRows=scope(null,now);
    renderChips();
    const hasBookings=selectedRows.length>0,roomSelected=Boolean(sharedFilters.room||filters.room);
    $('ba-no-bookings').hidden=hasBookings;
    for(const id of ['ba-cards','ba-tabs','ba-overview'])$(id).hidden=!hasBookings;
    document.querySelectorAll('[data-overview-only]').forEach(panel=>panel.hidden=roomSelected);
    if(!hasBookings)return;
    renderKpis(now);renderTrend();renderStatus(now);renderDemand(now);renderRecent(now);
    if(!roomSelected){renderDepartment(now);renderWeekday(now);renderFunnel(now);renderRooms(now);}
  }
  function chooseTab(tab,focus=false) {
    document.querySelectorAll('[data-tab]').forEach(item=>{const selected=item.dataset.tab===tab;item.setAttribute('aria-selected',String(selected));item.tabIndex=selected?0:-1;if(focus&&selected)item.focus();});
    ['overview'].forEach(name=>$('ba-'+name).hidden=name!==tab);Object.values(charts).forEach(chart=>chart.resize());
  }
  document.querySelectorAll('[data-tab]').forEach((item,index,items)=>{
    item.addEventListener('click',()=>chooseTab(item.dataset.tab));
    item.addEventListener('keydown',event=>{const next=event.key==='ArrowRight'?(index+1)%items.length:event.key==='ArrowLeft'?(index+items.length-1)%items.length:event.key==='Home'?0:event.key==='End'?items.length-1:null;
      if(next!==null){event.preventDefault();chooseTab(items[next].dataset.tab,true);}});
  });
  $('ba-group').addEventListener('change',event=>{group=event.target.value;render();});
  $('ba-trend-style')?.addEventListener('change',render);
  $('ba-refresh').addEventListener('click',()=>location.reload());
  const utilOptions=JSON.parse($('ba-util-options')?.textContent||'null')||{},utilRooms=utilOptions.rooms||[];
  function utilSelect(id,values,placeholder){const select=$(id);if(!select)return;select.replaceChildren(new Option(placeholder,''));values.forEach(item=>select.add(new Option(item.label,item.value)));}
  $('ba-util-campus')?.addEventListener('change',()=>{
    const campus=$('ba-util-campus').value;
    const buildings=[...new Set(utilRooms.filter(room=>!campus||room.campus===campus).map(room=>room.building))].sort();
    utilSelect('ba-util-building',buildings.map(value=>({value,label:value})),'All buildings');updateUtilRooms();
  });
  function updateUtilRooms(){const campus=$('ba-util-campus').value,building=$('ba-util-building').value;
    utilSelect('ba-util-room',utilRooms.filter(room=>(!campus||room.campus===campus)&&(!building||room.building===building)).map(room=>({value:room.key,label:room.name+' ('+room.code+') \u00b7 '+room.building})),'All rooms');}
  $('ba-util-building')?.addEventListener('change',updateUtilRooms);

  $('ba-export').addEventListener('click',()=>{
    const fields=['id','date','time','end_time','campus','building','room_name','room_type','department','faculty_name','status_label','source_label'];
    const quote=value=>'"'+String(/^[=+@-]/.test(String(value??''))?"'"+value:value??'').replaceAll('"','""')+'"';
    const csv='\ufeff'+[fields,...selectedRows.map(row=>fields.map(field=>row[field]))].map(row=>row.map(quote).join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'})),link=node('a');link.href=url;link.download='booking-analytics-'+page.dataset.start+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  root.addEventListener('popstate',()=>{restore();render();});
  root.addEventListener('pagehide',()=>Object.values(charts).forEach(chart=>chart.destroy()),{once:true});
  if(typeof root.Chart!=='function')$('ba-chart-error').hidden=false;
  restore();render();
  root.BookingAnalytics={filters,toggle,matches,render,charts,getRows:()=>[...selectedRows]};
})(typeof window==='undefined'?globalThis:window);
