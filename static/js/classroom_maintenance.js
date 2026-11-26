(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('cm-planner');
  if (!dialog) return;
  const form = $('cm-form'), fields = form.elements;
  const records = JSON.parse($('cm-records')?.textContent || '{}');
  const roomOptions = JSON.parse($('cm-room-options')?.textContent || '[]');
  const reload = () => BookingLoading.navigate(() => location.reload());
  const updates = typeof BroadcastChannel === 'function' ? new BroadcastChannel('classroom-maintenance') : null;
  updates?.addEventListener('message', () => {
    if (document.querySelector('[data-cm-region][data-cm-mode="timetable"]') && !dialog.open && !Swal.isVisible()) {
      reload();
    }
  });
  const maintenanceAlert = options => Swal.fire({
    ...options,
    customClass: {
      ...options.customClass,
      container: ['cm-alert-layer', options.customClass?.container].filter(Boolean).join(' '),
      popup: ['cm-alert-popup', options.customClass?.popup].filter(Boolean).join(' '),
    },
  });
  let current, selections, onCancel, saving = false, editReview;

  async function requestWithTimeout(url,options) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
    try{return await fetch(url,{...options,signal:controller.signal});}
    catch(problem){if(problem.name==='AbortError')throw new Error('The maintenance request is taking too long. Refresh and check its status before retrying.');throw problem;}
    finally{clearTimeout(timer);}
  }
  function node(tag,text) {
    const item=document.createElement(tag);
    if(text!=null)item.textContent=text;
    return item;
  }
  const send = (url,payload,quiet=false) => {
    const request=async () => {
      const response=await requestWithTimeout(url,{method:'POST',headers:{
        'Content-Type':'application/json','X-CSRFToken':fields.csrfmiddlewaretoken.value,
      },body:JSON.stringify(payload)});
      let data;
      try{data=await response.json();}
      catch{throw new Error('Maintenance could not be updated. Refresh and try again.');}
      if(!response.ok)throw new Error(data.error||'Maintenance request failed.');
      return data;
    };
    return quiet?request():BookingLoading.run(request);
  };
  function error(text='') {
    $('cm-error').textContent=text;
    $('cm-error').hidden=!text;
  }
  const dateLabel=date=>date?new Date(date+'T12:00:00').toLocaleDateString(undefined,{weekday:'short',year:'numeric',month:'short',day:'numeric'}):'';
  const dateTimeLabel=value=>{
    if(!value)return '';
    const [date,time]=value.split('T');
    const label=new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'})
      .format(new Date(date+'T12:00:00Z'));
    return time?label+' · '+time:label;
  };
  const floorLabel=floor=>floor==='__unrecorded__'?'Not recorded':floor;
  const scopeLabel=scope=>({room:'Classroom',floor:'Entire floor',building:'Entire building'})[scope];
  const selectionText=items=>items.map(item=>dateLabel(item.date)+' · '+item.start+'–'+item.end).join('\n');
  const sortSelections=items=>[...items].sort((a,b)=>a.date.localeCompare(b.date)||a.start.localeCompare(b.start));
  const scheduleFields=['starts_at','expected_completion','start_date','end_date'];
  const scheduleState=()=>JSON.stringify([
    ...scheduleFields.map(name=>fields[name].value),
    sortSelections(selections).map(({date,start,end})=>[date,start,end]),
  ]);

  function rows(values) {
    const list=node('dl');list.className='cm-review-list';
    for(const [label,value] of values){
      const row=node('div'), detail=node('dd');
      if(value instanceof Node)detail.append(value);else detail.textContent=value||'—';
      row.append(node('dt',label),detail);list.append(row);
    }
    return list;
  }
  function expandable(label,body) {
    const details=node('details');details.className='cm-review-dropdown';
    details.append(node('summary',label),body);
    return details;
  }
  function classroomSummary(label) {
    const rooms=String(label||'').split(',').map(item=>item.trim()).filter(Boolean);
    if(rooms.length<=8)return label||'—';
    return expandable('View '+rooms.length+' classrooms',node('p',rooms.join(', ')));
  }
  function dateRange(first,last) {
    const days=[];
    const cursor=new Date(first+'T12:00:00Z'), end=new Date(last+'T12:00:00Z');
    for(;cursor<=end&&days.length<=366;cursor.setUTCDate(cursor.getUTCDate()+1)){
      days.push({date:cursor.toISOString().slice(0,10),start:'00:00',end:'23:59'});
    }
    return days;
  }
  function scheduleReview(windows,roomLabel,compact=false) {
    const section=node('section');section.className='cm-schedule-review';
    if(!compact)section.append(node('h3','Selected Maintenance Schedule'));
    const sorted=sortSelections(windows), first=sorted[0], last=sorted.at(-1);
    if(compact){
      const dates=new Set(sorted.map(item=>item.date)).size;
      const counts=node('p',dates+' date'+(dates===1?'':'s')+' · '+sorted.length+' time slot'+(sorted.length===1?'':'s'));
      counts.className='cm-schedule-counts';section.append(counts);
    }else section.append(rows([
      ['Total selected dates',String(new Set(sorted.map(item=>item.date)).size)],
      ['Total selected time slots',String(sorted.length)],
      ['First selected date and time',first?dateLabel(first.date)+' · '+first.start:''],
      ['Last selected date and time',last?dateLabel(last.date)+' · '+last.end:''],
    ]));
    const weeks=new Map();
    for(const item of sorted){
      if(!item.date)continue;
      const monday=new Date(item.date+'T12:00:00Z');
      monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
      const key=compact?'':monday.toISOString().slice(0,10);
      if(!weeks.has(key))weeks.set(key,new Map());
      const dates=weeks.get(key);
      if(!dates.has(item.date))dates.set(item.date,[]);
      dates.get(item.date).push(item);
    }
    const dateFormat=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
    const shortDateFormat=new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'});
    const weekdayFormat=new Intl.DateTimeFormat('en-GB',{weekday:'long',timeZone:'UTC'});
    if(!sorted.length&&compact)section.append(node('p','No complete time slots selected.'));
    for(const dates of weeks.values()){
      const wrap=node('div');wrap.className='cm-table-wrap';
      const table=node('table');table.className='cm-table';
      const header=table.createTHead().insertRow();
      for(const label of ['Date','Day','Selected time slots','Classrooms']){
        const th=node('th',label);th.scope='col';header.append(th);
      }
      const body=table.createTBody();
      for(const [date,slots] of dates){
        const row=body.insertRow();
        const day=new Date(date+'T12:00:00Z');
        const dateCell=row.insertCell();dateCell.className='cm-schedule-date';
        const dateText=node('time',shortDateFormat.format(day));dateText.dateTime=date;dateCell.append(dateText);
        const weekdayCell=row.insertCell();
        weekdayCell.className='cm-schedule-weekday';
        weekdayCell.textContent=weekdayFormat.format(day);
        const ranges=node('ul');ranges.className='cm-schedule-slots';
        for(const slot of slots)ranges.append(node('li',slot.start+'–'+slot.end));
        row.insertCell().append(ranges);
        const classroomCell=row.insertCell(),summary=classroomSummary(roomLabel);
        if(summary instanceof Node)classroomCell.append(summary);else classroomCell.textContent=summary;
      }
      wrap.append(table);
      if(compact){section.append(wrap);continue;}
      const selectedDates=[...dates.keys()];
      const firstDate=dateFormat.format(new Date(selectedDates[0]+'T12:00:00Z'));
      const lastDate=dateFormat.format(new Date(selectedDates.at(-1)+'T12:00:00Z'));
      const label=selectedDates.length===1?'Selected date: '+firstDate
        :'Selected date range: '+firstDate+' to '+lastDate+' ('+selectedDates.length+' selected dates)';
      const group=expandable(label,wrap);
      group.open=true;
      section.append(group);
    }
    return section;
  }
  function refreshSummary() {
    const target=current.target;
    const targetDetails=[
      ['Scope',scopeLabel(target.scope)],['Campus / Building',target.campus+' / '+current.buildingLabel],
      ['Floor',current.floorLabel],
    ];
    if(!current.record)targetDetails.push(['Selected Classrooms',classroomSummary(current.roomLabel)]);
    $('cm-target').replaceChildren(rows(targetDetails));
    const windows=current.record?editScheduleWindows():current.allDay?boundedWindows():selections;
    if(current.record){
      const completion=fields.expected_completion.value;
      const metrics=rows([
        ['Originally selected classrooms',String(current.originalRoomCount)],
        ['Classrooms under this schedule',String(current.roomKeys.length)],
      ]);
      metrics.classList.add('cm-maintenance-summary');
      $('cm-summary-values').replaceChildren(metrics);
      $('cm-current-start').textContent=dateTimeLabel(current.originalStart)||'Not recorded';
      $('cm-current-completion').textContent=dateTimeLabel(completion)||'Not recorded';
      $('cm-schedule-table').replaceChildren(scheduleReview(windows,current.roomLabel,true));
    }else{
      $('cm-selected-schedule').replaceChildren(scheduleReview(windows,current.roomLabel));
    }
  }
  const completeWindows=()=>selections.filter(item=>item.date&&item.start&&item.end&&item.start<item.end);
  function editScheduleWindows() {
    if(current.record.saved_windows?.length&&scheduleState()===current.savedSchedule)return current.record.saved_windows;
    if(!current.record.recurrence)return boundedWindows().filter(item=>item.start<item.end);
    const first=fields.start_date.value, last=fields.end_date.value;
    if(!first||!last||first>last)return [];
    const weekday=day=>new Date(day+'T12:00:00Z').getUTCDay();
    const rules=completeWindows();
    const windows=dateRange(first,last).slice(0,366).flatMap(day=>rules
      .filter(rule=>weekday(rule.date)===weekday(day.date)).map(rule=>({...rule,date:day.date})));
    const limit=fields.expected_completion.value;
    if(!limit||!current.record.history?.some(entry=>entry.extended_until))return windows;
    return windows.filter(slot=>slot.date+'T'+slot.start<limit).map(slot=>({
      ...slot,end:slot.date+'T'+slot.end>limit?limit.slice(11):slot.end,
    }));
  }
  function refreshEditedWindows() {
    if(!current.record.recurrence){
      const valid=completeWindows();
      const starts=valid.map(slot=>slot.date+'T'+slot.start).sort();
      const ends=valid.map(slot=>slot.date+'T'+slot.end).sort();
      if(starts.length&&(!fields.starts_at.value||starts[0]<fields.starts_at.value))fields.starts_at.value=starts[0];
      if(ends.length&&(!fields.expected_completion.value||ends.at(-1)>fields.expected_completion.value))fields.expected_completion.value=ends.at(-1);
    }
    refreshSummary();
  }
  function boundedWindows(){
    const start=fields.starts_at.value, end=fields.expected_completion.value;
    if(!start||!end||start>=end)return [];
    const dates=current.allDay?dateRange(start.slice(0,10),end.slice(0,10)):selections;
    return dates.filter(item=>item.date+'T'+item.start<end&&item.date+'T'+item.end>start).map(item=>({
      ...item,start:item.date===start.slice(0,10)&&item.start<start.slice(11)?start.slice(11):item.start,
      end:item.date===end.slice(0,10)&&item.end>end.slice(11)?end.slice(11):item.end,
    }));
  }
  for(const field of [fields.starts_at,fields.expected_completion,fields.start_date,fields.end_date])field.addEventListener('input',()=>{
    if(current?.allDay||current?.record)refreshSummary();
  });
  function renderEditableWindows() {
    const container=$('cm-selections');container.replaceChildren();
    for(const entry of selections){
      const row=node('div');row.className='cm-day-row';
      for(const [property,label,type] of [['date','Date','date'],['start','From','time'],['end','To','time']]){
        const wrapper=node('label',label),input=node('input');input.type=type;input.required=true;input.value=entry[property];
        input.addEventListener('change',()=>{entry[property]=input.value;refreshEditedWindows();});
        wrapper.append(input);row.append(wrapper);
      }
      const remove=node('button','Remove');remove.type='button';
      remove.addEventListener('click',()=>{selections=selections.filter(item=>item!==entry);renderEditableWindows();refreshEditedWindows();});
      row.append(remove);container.append(row);
    }
  }
  const moreChips=$('cm-more-chips');
  const extension=$('cm-extension-fields'), extendUntil=$('cm-extend-until');
  const tooltip=node('div');tooltip.className='cm-room-tooltip';tooltip.hidden=true;
  tooltip.setAttribute('aria-hidden','true');dialog.append(tooltip);
  const roomCode=key=>current.rooms.get(key)?.room_code||key.split('|').at(-1);
  const sameRooms=(first,second)=>first.length===second.length&&first.every(key=>second.includes(key));
  function roomState(key,selected) {
    if(!selected&&(current.savedRoomKeys.includes(key)||current.releasedKeys.has(key)))return 'released';
    if(selected&&!current.savedRoomKeys.includes(key))return 'selected';
    if(current.rooms.get(key)?.under_maintenance)return 'maintenance';
    return selected?'selected':'available';
  }
  const roomStateLabel={maintenance:'Under maintenance',available:'Available',selected:'Selected for maintenance',released:'Released / removed'};
  function bindRoomTooltip(element,key) {
    function show() {
      const room=current.rooms.get(key)||{};
      const selected=current.roomKeys.includes(key);
      const details=[
        ['Building',room.building||current.buildingLabel],['Room number',roomCode(key)],
        ['Floor',floorLabel(room.floor_code||'__unrecorded__')],['Campus',room.campus||current.target.campus],
        ['Status',room.under_maintenance?'Under maintenance':roomStateLabel[roomState(key,selected)]],
      ];
      tooltip.replaceChildren(...details.map(([label,value])=>node('div',label+': '+value)));
      tooltip.hidden=false;
      const {left,right,bottom,top}=element.getBoundingClientRect();
      const {width,height}=tooltip.getBoundingClientRect();
      tooltip.style.left=Math.max(6,Math.min(left,innerWidth-width-6,right))+'px';
      tooltip.style.top=(bottom+height+8<innerHeight?bottom+6:Math.max(6,top-height-6))+'px';
    }
    element.addEventListener('pointerenter',show);
    element.addEventListener('pointerleave',()=>{tooltip.hidden=true;});
    element.addEventListener('focusin',show);
    element.addEventListener('focusout',()=>{tooltip.hidden=true;});
  }
  dialog.addEventListener('scroll',()=>{tooltip.hidden=true;},true);
  dialog.addEventListener('close',()=>{tooltip.hidden=true;});

  function selectionMessage(previous,next) {
    const removed=previous.filter(key=>!next.includes(key)).map(roomCode);
    if(removed.length)return 'Classroom '+removed.at(-1)+' removed.'+(removed.length>1?' '+removed.length+' classrooms removed in this action.':'');
    return 'Classroom selection updated.';
  }
  function roomRemovalHistory(previous,next,history) {
    const added=new Set(next);
    const removed=previous.filter(key=>!added.has(key));
    return [...new Set([...history.filter(key=>!added.has(key)),...removed])];
  }
  function restoreRoom(keys,key) {
    return [...keys,key].sort((first,second)=>current.roomOrder.get(first)-current.roomOrder.get(second));
  }
  function updateUndo(history,message) {
    const notice=$('cm-room-change'), button=$('cm-undo-rooms'), text=$('cm-room-change-text');
    if(message!==undefined)text.textContent=message;
    notice.hidden=!text.textContent&&!history.length;
    button.disabled=!history.length;
    if(history.length)button.setAttribute('aria-label','Undo removal of classroom '+roomCode(history.at(-1)));
    else button.removeAttribute('aria-label');
  }
  function applyRoomSelection(next) {
    const previous=current.roomKeys;
    if(sameRooms(previous,next))return;
    current.roomUndo=roomRemovalHistory(previous,next,current.roomUndo);
    current.roomKeys=next;
    updateUndo(current.roomUndo,selectionMessage(previous,next));
    renderRoomChips();
  }
  function renderRoomChips() {
    tooltip.hidden=true;
    const rooms=current.roomKeys.map(key=>({key,code:roomCode(key)}));
    const chips=$('cm-room-chips');
    chips.replaceChildren();
    const previewLimit=6;
    if(rooms.length<=previewLimit)current.showAllChips=false;
    if(current.showAllChips)chips.append(moreChips);
    for(const room of current.showAllChips?rooms:rooms.slice(0,previewLimit)){
      const chip=node('span',room.code);chip.className='cm-room-chip';
      chip.dataset.roomState=roomState(room.key,true);
      bindRoomTooltip(chip,room.key);
      if(rooms.length>1){
        const remove=node('button','×');remove.type='button';
        remove.setAttribute('aria-label','Remove classroom '+room.code);
        remove.addEventListener('click',()=>{
          applyRoomSelection(current.roomKeys.filter(key=>key!==room.key));
          $('cm-undo-rooms').focus();
        });
        chip.append(remove);
      }else chip.tabIndex=0;
      chips.append(chip);
    }
    if(!current.showAllChips)chips.append(moreChips);
    moreChips.hidden=rooms.length<=previewLimit;
    moreChips.setAttribute('aria-expanded',String(current.showAllChips));
    moreChips.textContent=current.showAllChips?'Show fewer':'+'+(rooms.length-previewLimit)+' more';
    updateUndo(current.roomUndo);
    $('cm-classroom-count').textContent='Selected Classrooms ('+rooms.length+')';
    current.roomLabel=rooms.map(room=>room.code).join(', ');
    if(current.record.scope==='room'){
      const floors=[...new Set(current.roomKeys.map(key=>current.rooms.get(key)?.floor_code||'__unrecorded__'))].sort();
      current.floorLabel=floors.map(floorLabel).join(', ');
    }
    refreshSummary();
  }
  $('cm-undo-rooms').addEventListener('click',()=>{
    const key=current.roomUndo.pop();
    if(!key)return;
    current.roomKeys=restoreRoom(current.roomKeys,key);
    updateUndo(current.roomUndo,'Classroom '+roomCode(key)+' restored.');
    renderRoomChips();
    if(!current.roomUndo.length)$('cm-classroom-count').focus();
  });
  $('cm-more-chips').addEventListener('click',()=>{
    current.showAllChips=!current.showAllChips;
    renderRoomChips();
    $('cm-room-chips').scrollTop=0;
    moreChips.focus();
  });
  $('cm-extend-button').addEventListener('click',()=>{
    extension.hidden=!extension.hidden;
    $('cm-extend-button').setAttribute('aria-expanded',String(!extension.hidden));
    if(extension.hidden){extendUntil.value='';refreshSummary();}
    else extendUntil.focus();
  });
  $('cm-save-extension').addEventListener('click',()=>form.requestSubmit($('cm-submit')));
  function renderEditHistory(record) {
    const list=$('cm-edit-history-list');
    list.replaceChildren();
    function appendEvent(message,at,by) {
      const event=node('li');
      event.append(node('strong',message),node('small',
        [at?new Date(at).toLocaleString():'',by].filter(Boolean).join(' · ')));
      list.append(event);
    }
    for(const item of [...(record.history||[])].reverse()){
      const releases=item.room_releases||(item.released_rooms||[]).map(room_key=>({room_key,released_at:item.at}));
      for(const release of releases){
        appendEvent('Classroom '+roomCode(release.room_key)+' released from maintenance.',release.released_at,item.by);
      }
      if(item.extended_until)appendEvent('Expected completion: '+(dateTimeLabel(item.previous?.expected_completion)||'Not recorded')
        +' → '+dateTimeLabel(item.extended_until),item.at,item.by);
    }
    $('cm-edit-history').hidden=!list.children.length;
    $('cm-edit-history').open=false;
  }
  function openDetails(target,windows,options={}) {
    current={target,...options};
    selections=sortSelections(windows).map(entry=>({...entry}));
    onCancel=options.cancel;
    form.reset();error();
    const record=options.record;
    dialog.classList.toggle('cm-dialog-edit',Boolean(record));
    $('cm-edit-close').hidden=!record;
    $('cm-submit').textContent=record?'Save Changes':'Review & Submit';
    $('cm-classroom-summary').hidden=!record;
    $('cm-details-heading').hidden=!record;
    $('cm-maintenance-summary').hidden=!record;
    $('cm-selected-schedule').hidden=Boolean(record);
    $('cm-schedule-details').hidden=!record;
    $('cm-schedule-details').open=false;
    $('cm-room-change').hidden=true;
    moreChips.hidden=true;
    $('cm-timing-section').hidden=!record;
    $('cm-edit-history').hidden=true;
    extension.hidden=true;
    extendUntil.value='';
    $('cm-extend-button').setAttribute('aria-expanded','false');
    const bounds=$('cm-time-bounds');
    if(record)$('cm-edit-schedule').append(bounds);
    else $('cm-edit-fields').insertBefore(bounds,$('cm-edit-history'));
    $('cm-inline-reason').hidden=true;
    leaveEditReview();
    if(record){
      const allowedFloors=record.targets.length?record.targets:[record.floor];
      current.roomKeys=[...(record.assigned_room_keys||[])];
      current.savedRoomKeys=[...current.roomKeys];
      current.roomUndo=[];
      current.showAllChips=false;
      updateUndo(current.roomUndo,'');
      current.releasedKeys=new Set();
      const history=record.history||[];
      for(const entry of history){
        for(const key of entry.released_rooms||[])current.releasedKeys.add(key);
        for(const key of entry.added_rooms||[])current.releasedKeys.delete(key);
      }
      const original=history.find(item=>item.previous?.selections?.length)?.previous||record;
      const initial=sortSelections(original.selections)[0];
      current.originalStart=history[0]?.original_start||(initial?initial.date+'T'+initial.start:'');
      current.originalRoomCount=history[0]?.added_rooms?.length||original.room_codes.length;
      current.rooms=new Map(roomOptions.filter(room=>room.building_key===record.building
        &&(record.scope!=='floor'||allowedFloors.includes(room.floor_code||'__unrecorded__'))).map(room=>[room.key,room]));
      for(const key of current.roomKeys){
        if(!current.rooms.has(key))current.rooms.set(key,{key,room_code:key.split('|').at(-1)});
      }
      current.roomOrder=new Map([...new Set([...current.savedRoomKeys,...current.rooms.keys()])]
        .map((key,index)=>[key,index]));
      $('cm-extension-note').textContent=record.recurrence
        ?'Remove completed classrooms first. Remaining classrooms follow the existing weekday pattern.'
        :'Remove completed classrooms first. Maintenance continues for the remaining classrooms.';
      renderEditHistory(record);
    }
    fields.reason.value=record?.reasons[0]||'';
    const first=selections[0],last=selections.at(-1);
    fields.starts_at.value=first?first.date+'T'+first.start:'';
    fields.starts_at.readOnly=Boolean(options.selectedWindows?.length);
    const lastWindow=last?last.date+'T'+last.end:'';
    fields.expected_completion.value=record?.expected_completion||lastWindow;
    fields.description.value=record?.description||'';
    fields.start_date.value=record?.start_date||'';
    fields.end_date.value=record?.end_date||'';
    if(record)current.savedSchedule=scheduleState();
    $('cm-title').textContent=record?'Edit Maintenance':'Maintenance Details';
    $('cm-edit-schedule').hidden=!record;
    $('cm-edit-schedule').open=false;
    $('cm-recurrence').hidden=!record?.recurrence;
    dialog.querySelector('[data-cm-back]').hidden=!options.cancel;
    if(record){renderEditableWindows();renderRoomChips();}
    else {$('cm-selections').replaceChildren();refreshSummary();}
    dialog.showModal();
  }
  $('cm-add-window').addEventListener('click',()=>{
    const last=sortSelections(completeWindows()).at(-1);
    const next=last?new Date(last.date+'T12:00:00Z'):null;
    if(next)next.setUTCDate(next.getUTCDate()+1);
    selections.push({date:next?.toISOString().slice(0,10)||fields.starts_at.value.slice(0,10),start:last?.start||'08:00',end:last?.end||'16:00'});
    renderEditableWindows();refreshEditedWindows();
    $('cm-selections').lastElementChild.querySelector('input').focus();
  });
  dialog.querySelector('[data-cm-back]').addEventListener('click',()=>dialog.close());
  function cancelDetails(){if(saving)return;dialog.close();onCancel?.();}
  $('cm-edit-close').addEventListener('click',cancelDetails);
  dialog.querySelector('[data-cm-close]').addEventListener('click',cancelDetails);
  dialog.addEventListener('cancel',event=>{event.preventDefault();cancelDetails();});

  function bindSelection(region) {
    const start=region.querySelector('[data-cm-start]'), bar=region.querySelector('[data-cm-selection-bar]');
    if(!start||!bar)return;
    const undo = bar.querySelector('[data-cm-finish="undo"]');
    const mode=region.dataset.cmMode, timetable=mode==='timetable';
    const storageKey='maintenance-selection:'+region.dataset.room;
    const cards=[...region.querySelectorAll('[data-cm-card]')], days=[...region.querySelectorAll('[data-cm-day]')];
    const slots=[...region.querySelectorAll('[data-cm-slot]')];
    const cells=[...region.querySelectorAll('[data-cm-date]')];
    const displayedDates=new Set(cells.map(cell=>cell.dataset.cmDate));
    const proceed=bar.querySelector('[data-cm-proceed]'), count=bar.querySelector('[data-cm-count]');
    const first=bar.querySelector('[data-cm-from]'),last=bar.querySelector('[data-cm-to]'),whole=bar.querySelector('[data-cm-whole-building]');
    const pickedSlots=new Map(), pickedCards=new Map();
    const uncheckedRooms = () => [...pickedCards].filter(([, input]) => !input.checked)
      .map(([card]) => card.dataset.cmCard);
    const date=region.dataset.date>=region.dataset.today?region.dataset.date:region.dataset.today;
    let active=false;
    const slotKey=item=>item.id;
    const eligibleIds=new Set(slots.map(slot=>slotKey(slot.dataset)));
    function saveDraft(){
      if(!timetable)return;
      try{
        if(active)sessionStorage.setItem(storageKey,JSON.stringify({active:true,slots:[...pickedSlots.values()]}));
        else sessionStorage.removeItem(storageKey);
      }catch{/* The live selection remains usable without storage. */}
    }
    function synchronize(){
      for(const input of days){
        const eligible=slots.filter(slot=>slot.dataset.date===input.dataset.cmDay);
        input.closest('label').hidden=!active||!eligible.length;
        const some=eligible.some(slot=>pickedSlots.has(slotKey(slot.dataset)));
        input.disabled=!eligible.length;
        input.checked=active&&eligible.length>0&&eligible.every(slot=>pickedSlots.has(slotKey(slot.dataset)));
        input.indeterminate=active&&some&&!input.checked;
        input.closest('th').classList.toggle('cm-day-selected',input.checked);
      }
      for(const input of slots){
        const shown=active;
        const openSlot=input.closest('.cm-slot-control');
        openSlot.hidden=!shown;
        input.checked=shown&&pickedSlots.has(slotKey(input.dataset));
        openSlot.classList.toggle('cm-booking-selected',input.checked);
      }
      for(const [card,input] of pickedCards){
        card.classList.toggle('cm-card-chosen',input.checked);
      }
      if (undo) {
        const total = uncheckedRooms().length;
        undo.disabled = !active || total === 0;
        count.textContent = total + (total === 1 ? ' classroom' : ' classrooms') + ' to release';
        return;
      }
      const total=timetable?pickedSlots.size:[...pickedCards.values()].filter(input=>input.checked).length;
      const dates=timetable?[]:dateRange(first.value,last.value);
      const validDates=timetable||Boolean(first.value&&last.value&&first.checkValidity()&&last.checkValidity()&&dates.length&&dates.length<=366);
      proceed.disabled=!active||!total||!validDates;
      count.textContent=total+(timetable?' time slot':mode==='floor'?' floor':' classroom')+(total===1?' selected':'s selected');
      saveDraft();
    }
    function activate({focus=true}={}){
      if(active)return;
      if(timetable)restoreDraft();
      active=true;region.setAttribute('data-cm-active','');bar.hidden=false;start.setAttribute('aria-expanded','true');
      for(const card of cards){
        const wrapper=node('div');wrapper.className='cm-card-choice';
        const input=node('input');input.type='checkbox';input.checked=Boolean(undo);
        input.setAttribute('aria-label',(undo ? 'Keep under maintenance: ' : 'Select ')+card.querySelector('strong').textContent);
        card.before(wrapper);wrapper.append(card,input);pickedCards.set(card,input);
        input.addEventListener('change',()=>{
          if(whole&&!input.checked)whole.checked=false;
          synchronize();
        });
      }
      if(first){first.value=date;last.value=date;last.min=date;}
      synchronize();
      if(focus)(pickedCards.values().next().value||days.find(input=>!input.disabled))?.focus();
    }
    function cancel(){
      active=false;region.removeAttribute('data-cm-active');bar.hidden=true;start.setAttribute('aria-expanded','false');
      for(const card of pickedCards.keys()){card.classList.remove('cm-card-chosen');card.parentElement.replaceWith(card);}
      pickedCards.clear();pickedSlots.clear();
      if(whole)whole.checked=false;
      synchronize();start.focus();
    }
    for(const card of cards)card.addEventListener('click',event=>{
      if(!active)return;
      event.preventDefault();
      pickedCards.get(card).click();
    },true);
    for(const day of days)day.addEventListener('change',()=>{
      const date=day.dataset.cmDay;
      for(const slot of slots.filter(item=>item.dataset.date===date)){
        const {id,date,start,end}=slot.dataset;
        const key=slotKey(slot.dataset);
        if(day.checked)pickedSlots.set(key,{id,date,start,end});else pickedSlots.delete(key);
      }
      synchronize();
    });
    for(const input of slots)input.addEventListener('change',()=>{
      const {id,date,start,end}=input.dataset,key=slotKey(input.dataset);
      if(input.checked)pickedSlots.set(key,{id,date,start,end});
      else pickedSlots.delete(key);
      synchronize();
    });
    whole?.addEventListener('change',()=>{for(const input of pickedCards.values())input.checked=whole.checked;synchronize();});
    first?.addEventListener('change',()=>{last.min=first.value;if(last.value<first.value)last.value=first.value;synchronize();});
    last?.addEventListener('change',synchronize);
    start.addEventListener('click',()=>{
      const menu=start.closest('details');
      if(menu)menu.open=false;
      if(active)return;
      activate();
    });
    bar.querySelector('[data-cm-cancel]').addEventListener('click',cancel);
    region.querySelector('[data-cm-exit]')?.addEventListener('click',()=>{active=false;saveDraft();});
    undo?.addEventListener('click', () => finishMaintenance(undo, uncheckedRooms()));
    proceed?.addEventListener('click',()=>{
      if(proceed.disabled)return;
      const chosen=[...pickedCards].filter(([,input])=>input.checked).map(([card])=>card);
      const scope=timetable?'room':whole?.checked?'building':mode;
      const target={scope,campus:region.dataset.campus,building:region.dataset.building,
        floor:region.dataset.floor||'',room:region.dataset.room||'',targets:timetable?[region.dataset.room]:chosen.map(card=>card.dataset.cmCard)};
      if(timetable)target.timetable_selection=true;
      openDetails(target,timetable?[...pickedSlots.values()]:dateRange(first.value,last.value),{
        buildingLabel:region.dataset.buildingLabel||target.building.split('|').at(-1),
        floorLabel:scope==='building'?'All floors':mode==='floor'?chosen.map(card=>floorLabel(card.dataset.cmCard)).join(', '):floorLabel(target.floor),
        roomLabel:timetable?(region.dataset.roomLabel||target.room.split('|').at(-1)):mode==='room'?chosen.map(card=>card.querySelector('strong').textContent).join(', '):'All classrooms in the selection',
        allDay:!timetable,selectedWindows:[...pickedSlots.values()],cancel,
        clearDraft:()=>{active=false;saveDraft();},
      });
    });
    function restoreDraft(){
      try{
        const saved=JSON.parse(sessionStorage.getItem(storageKey)||'null');
        if(saved){
          for(const slot of saved.slots){
            if(slot.id?.startsWith('open:')&&slot.date>=region.dataset.today&&(!displayedDates.has(slot.date)||eligibleIds.has(slot.id))){
              pickedSlots.set(slotKey(slot),slot);
            }
          }
        }
      }catch{/* Ignore stale browser-only drafts. */}
    }
    if(timetable){
      try{
        if(JSON.parse(sessionStorage.getItem(storageKey)||'null')?.active===true)activate({focus:false});
      }catch{/* The user can still enter maintenance mode manually. */}
    }
  }
  document.querySelectorAll('[data-cm-region]').forEach(bindSelection);

  function affectedTable(items) {
    const wrap=node('div');wrap.className='cm-table-wrap';
    const table=node('table');table.className='cm-table';
    const heading=table.createTHead().insertRow();
    for(const text of ['Date','Time','Faculty','Classroom','Status'])heading.append(node('th',text));
    const body=table.createTBody();
    for(const item of items){
      const row=body.insertRow();
      for(const text of [dateLabel(item.date),item.start+'–'+item.end,item.faculty,item.room,item.status])row.insertCell().textContent=text;
    }
    wrap.append(table);return wrap;
  }
  function setSaving(active,message='') {
    saving=active;
    const status=$('cm-save-status');
    status.textContent=message;
    status.hidden=!message;
    form.setAttribute('aria-busy',String(active));
    for(const button of [$('cm-submit'),$('cm-save-extension'),$('cm-back-to-edit'),$('cm-edit-close'),dialog.querySelector('[data-cm-close]')]){
      button.disabled=active;
    }
    $('cm-confirm-edit').disabled=active||Boolean(editReview?.blocking&&!editReview.acknowledgement.checked);
  }
  function leaveEditReview() {
    editReview=null;
    $('cm-inline-review').hidden=true;
    $('cm-inline-review').replaceChildren();
    $('cm-edit-fields').hidden=false;
    $('cm-back-to-edit').hidden=true;
    $('cm-confirm-edit').hidden=true;
    $('cm-submit').hidden=false;
  }
  $('cm-back-to-edit').addEventListener('click',()=>{
    leaveEditReview();error();$('cm-submit').focus();
  });
  $('cm-confirm-edit').addEventListener('click',async()=>{
    if(saving||!editReview)return;
    const {payload,token,acknowledgement,blocking}=editReview;
    if(blocking&&!acknowledgement.checked)return;
    error();setSaving(true,'Saving changes…');
    try{
      await send(dialog.dataset.scheduleUrl,{...payload,action:'save',token,acknowledge_overlaps:acknowledgement.checked},true);
    }catch(problem){
      error(problem.message);setSaving(false);return;
    }
    setSaving(false);
    dialog.close();
    updates?.postMessage({type:'saved'});
    await maintenanceAlert({icon:'success',title:payload.extend_until?'Maintenance extended':'Maintenance changes saved',
      text:payload.extend_until?dateTimeLabel(payload.extend_until):undefined,showConfirmButton:false,timer:900});
    reload();
  });
  form.addEventListener('invalid',event=>{
    if(event.target.closest('#cm-edit-schedule')){
      $('cm-schedule-details').open=true;
      $('cm-edit-schedule').open=true;
    }
  },true);
  form.addEventListener('submit',async event=>{
    event.preventDefault();error();
    if(saving||editReview)return;
    const operation=current;
    const data=new FormData(form),record=operation.record;
    const reason=data.get('reason');
    const description=data.get('description');
    const target={...operation.target};
    let classroomsOnly=false;
    if(record){
      target.classroom_keys=[...operation.roomKeys];
      if(!target.classroom_keys.length){error('Please select at least one classroom.');return;}
      if(!sameRooms(target.classroom_keys,operation.savedRoomKeys)){
        classroomsOnly=scheduleState()===operation.savedSchedule&&reason===record.reasons[0]
          && description===(record.description||'');
        target.booking_ids=[];
        target.timetable_selection=false;
      }
      if(record.scope==='room'){
        target.targets=target.classroom_keys;
        target.room='';
        target.floor='';
      }
    }
    const extending=Boolean(record&&!extension.hidden);
    const expected=extending?extendUntil.value:data.get('expected_completion');
    const start=data.get('starts_at');
    if(extending&&(scheduleState()!==operation.savedSchedule||reason!==record.reasons[0]
      ||description!==(record.description||''))){
      error('Save date, time, or reason edits separately before extending maintenance.');return;
    }
    if(extending&&target.classroom_keys.some(key=>!operation.savedRoomKeys.includes(key))){
      error('Only classrooms already in this schedule can be extended. Save added classrooms separately first.');return;
    }
    if(extending&&!expected){error('Enter the new expected completion date and time.');return;}
    if(!extending&&!classroomsOnly&&record&&completeWindows().length!==selections.length){
      error('Enter a date and an end time after the start time for every slot.');return;
    }
    if(!extending&&!classroomsOnly&&(!start||!expected||start>=expected)){
      error('Expected completion must be after the start date and time.');return;
    }
    const fixedSlots=operation.selectedWindows?.length;
    if(fixedSlots&&selections.some(item=>item.date+'T'+item.start<start||item.date+'T'+item.end>expected)){
      error('Start and completion must cover every selected slot. Use Back to change the selected slots.');return;
    }
    const windows=fixedSlots||record?.recurrence?selections:boundedWindows();
    if(!extending&&!classroomsOnly&&!windows.length){
      error('The date and time range must include at least one selected maintenance window.');return;
    }
    const reasons=record?.reasons[0]===reason?record.reasons:[reason];
    const payload=extending?{id:record.id,classroom_keys:target.classroom_keys,extend_until:expected,action:'preview'}
      :classroomsOnly?{id:record.id,classroom_keys:target.classroom_keys,classrooms_only:true,action:'preview'}
      :{...target,action:'preview',duration:record?.duration,
      description,reasons,
      expected_completion:expected,starts_at:record?.recurrence?undefined:start,
      recurrence:Boolean(record?.recurrence),start_date:data.get('start_date'),end_date:data.get('end_date'),
      selections:sortSelections(windows)};
    const submit=form.querySelector('[type="submit"]');
    if(record)setSaving(true,'Checking maintenance schedule…');
    else submit.disabled=true;
    try{
      const review=await send(dialog.dataset.scheduleUrl,payload,Boolean(record));
      if(!dialog.open||current!==operation)return;
      const content=node('div');
      const heading=node(record?'h3':'p',record?'Review Changes':'Place the selected location under maintenance?');
      content.append(heading,rows([
        ['Scope',scopeLabel(target.scope)],['Campus / Building',review.campus+' / '+review.building],
        ['Floor',review.floor ? floorLabel(review.floor) : scopeLabel(target.scope)],['Affected classrooms',review.room_codes.length>1
          ?expandable('View '+review.room_codes.length+' classrooms',node('p',review.room_codes.join(', ')))
          :review.room_codes[0]],
        ['Start Date & Time',start.replace('T',' ')],['End Date & Time',expected.replace('T',' ')],
        ['Reason',reasons.join(', ')],
      ]));
      if(extending){
        const released=operation.savedRoomKeys.filter(key=>!operation.roomKeys.includes(key)).map(roomCode);
        content.append(rows([
          ['Classrooms to release', released.length?classroomSummary(released.join(', ')):'None'],
          ['Classrooms to remain under maintenance',classroomSummary(review.room_codes.join(', '))],
        ]),node('p','Released classrooms return to normal availability, subject to other schedules and bookings.'));
      }
      if(extending){
        content.append(node('h3','Current schedule'),
          scheduleReview(editScheduleWindows(),operation.savedRoomKeys.map(roomCode).join(', '),true),
          node('h3','Extension for remaining classrooms'),
          scheduleReview(review.extension_windows,review.room_codes.join(', '),true));
      }else{
        content.append(scheduleReview(record?editScheduleWindows():windows,
          record?review.room_codes.join(', '):operation.roomLabel,Boolean(record)));
      }
      const canAcknowledge=review.blocking&&!payload.timetable_selection&&!payload.booking_ids?.length;
      const acknowledgement=node('input');acknowledgement.type='checkbox';
      if(review.affected.length){
        const message=canAcknowledge?'This maintenance overlaps existing classes or approved bookings. Their reservations will stay in place.':review.blocking?'Resolve other overlapping classes or approved bookings before submitting.':'The listed bookings will retain their current status.';
        content.append(node('p',message),expandable('View affected classes and bookings ('+review.affected.length+')',affectedTable(review.affected)));
      }
      if(canAcknowledge){
        const label=node('label');label.className='cm-overlap-acknowledgement';
        label.append(acknowledgement,document.createTextNode('I acknowledge the overlaps and want to submit this maintenance.'));
        content.append(label);
      }
      if(record){
        editReview={payload,token:review.token,acknowledgement,blocking:review.blocking};
        if(!canAcknowledge&&review.blocking)content.append(node('p','Resolve the overlapping classes or bookings before saving.'));
        acknowledgement.addEventListener('change',()=>{
          $('cm-confirm-edit').disabled=!acknowledgement.checked;
        });
        $('cm-inline-review').replaceChildren(content);
        $('cm-inline-review').hidden=false;
        $('cm-edit-fields').hidden=true;
        $('cm-submit').hidden=true;
        $('cm-back-to-edit').hidden=false;
        $('cm-confirm-edit').hidden=false;
        $('cm-confirm-edit').textContent=extending?'Confirm Extension':'Confirm Save';
        heading.tabIndex=-1;heading.focus();
        return;
      }
      dialog.close();
      const result=await maintenanceAlert({title:'Confirm Classroom Maintenance',html:content,width:760,returnFocus:false,
        showDenyButton:true,confirmButtonText:'Submit Maintenance',denyButtonText:'Go Back & Edit',
        focusConfirm:!review.blocking,focusDeny:review.blocking,
        didOpen:()=>{
          if(!review.blocking)return;
          const button=Swal.getConfirmButton();button.disabled=true;
          if(canAcknowledge)acknowledgement.addEventListener('change',()=>{button.disabled=!acknowledgement.checked;});
        },
        confirmButtonColor:'#007367',showLoaderOnConfirm:true,allowOutsideClick:()=>!Swal.isLoading(),allowEscapeKey:()=>!Swal.isLoading(),
        preConfirm:async()=>{
          if(review.blocking&&!(canAcknowledge&&acknowledgement.checked))return false;
          try{return await send(dialog.dataset.scheduleUrl,{...payload,action:'save',token:review.token,acknowledge_overlaps:acknowledgement.checked});}
          catch(problem){Swal.showValidationMessage(problem.message);return false;}
        }});
      if(result.isConfirmed){
        operation.clearDraft?.();
        updates?.postMessage({type:'saved'});
        await maintenanceAlert({icon:'success',title:'Maintenance saved',showConfirmButton:false,timer:900});
        reload();
      }else if(current===operation&&!dialog.open){
        dialog.showModal();
      }
    }catch(problem){
      if(current===operation&&dialog.open)error(problem.message);
    }
    finally{if(record)setSaving(false);else submit.disabled=false;}
  });
  function chooseReason(name) {
    if(![...fields.reason.options].some(option=>option.value===name))fields.reason.add(new Option(name,name));
    fields.reason.value=name;
  }
  const reasonName=$('cm-inline-reason-name');
  $('cm-cancel-reason').addEventListener('click',()=>{
    $('cm-inline-reason').hidden=true;
    $('cm-new-reason').focus();
  });
  reasonName.addEventListener('keydown',event=>{
    if(event.key==='Enter'){event.preventDefault();$('cm-save-reason').click();}
  });
  $('cm-save-reason').addEventListener('click',async()=>{
    if(saving)return;
    error();setSaving(true,'Saving reason…');
    $('cm-save-reason').disabled=true;
    $('cm-cancel-reason').disabled=true;
    try{
      const result=await send(dialog.dataset.reasonUrl,{name:reasonName.value},true);
      chooseReason(result.name);
      $('cm-inline-reason').hidden=true;
      fields.reason.focus();
    }catch(problem){error(problem.message);}
    finally{
      $('cm-save-reason').disabled=false;
      $('cm-cancel-reason').disabled=false;
      setSaving(false);
    }
  });
  $('cm-new-reason').addEventListener('click',async()=>{
    if(current.record){
      reasonName.value='';
      $('cm-inline-reason').hidden=false;
      reasonName.focus();
      return;
    }
    dialog.close();
    const result=await maintenanceAlert({title:'Add Maintenance Reason',width:420,customClass:{popup:'cm-reason-popup'},returnFocus:false,input:'text',inputAttributes:{maxlength:120},
      confirmButtonText:'Save reason',confirmButtonColor:'#007367',showCancelButton:true,showLoaderOnConfirm:true,
      preConfirm:async name=>{try{return await send(dialog.dataset.reasonUrl,{name});}catch(problem){Swal.showValidationMessage(problem.message);return false;}}});
    dialog.showModal();
    $('cm-new-reason').focus();
    if(!result.isConfirmed)return;
    chooseReason(result.value.name);
  });

  for(const button of document.querySelectorAll('[data-cm-edit]'))button.addEventListener('click',()=>{
    const record=records[button.dataset.cmEdit];
    openDetails({id:record.id,scope:record.scope,campus:record.campus,building:record.building,
      floor:record.floor,room:record.room,targets:record.targets,booking_ids:record.booking_ids,
      timetable_selection:record.timetable_selection},record.selections,{
      record,buildingLabel:record.building_name,roomLabel:record.room_codes.join(', '),
      floorLabel:record.floor?floorLabel(record.floor):record.scope==='floor'?record.targets.map(floorLabel).join(', '):'All floors',
    });
  });
  for(const button of document.querySelectorAll('[data-cm-view]'))button.addEventListener('click',()=>{
    const record=records[button.dataset.cmView],content=node('div');
    content.append(rows([['Status',record.status],['Campus / Building',record.campus+' / '+record.building_name],
      ['Floor',record.scope==='building'?'All floors':record.floor_labels.join(', ')||'Not recorded'],
      ...(record.scope==='room'?[['Classrooms',record.room_codes.join(', ')]]:[]),
      ['Days and hours',record.selections.length>1
        ?expandable('View '+record.selections.length+' time slots',node('p',selectionText(record.selections)))
        :selectionText(record.selections)],
      ['Recurrence',record.recurrence?record.start_date+' to '+record.end_date:'One-time dates'],
      ['Reasons',record.reasons.join(', ')],['Description',record.description],
      ['Expected completion',record.expected_completion],['Created',new Date(record.created_at).toLocaleString()],
      ['Last modified',new Date(record.updated_at).toLocaleString()]]));
    content.append(node('h3','History'));
    for(const [index,entry] of record.history.entries()){
      content.append(rows([[entry.action,entry.by+' · '+new Date(entry.at).toLocaleString()+(entry.reason?'\n'+entry.reason:'')]]));
      if(entry.previous){
        const before=entry.previous;
        const after=record.history.slice(index+1).find(item=>item.previous)?.previous||record;
        const added=after.room_codes.filter(code=>!before.room_codes.includes(code));
        const removed=before.room_codes.filter(code=>!after.room_codes.includes(code));
        if(added.length||removed.length){
          content.append(rows([['Added classrooms',added.join(', ')],['Removed classrooms',removed.join(', ')]]));
        }
        const snapshotRows=snapshot=>rows([
          ['Scope',scopeLabel(snapshot.scope)],['Classrooms',snapshot.room_codes.join(', ')],
          ['Days and hours',selectionText(snapshot.selections)],['Reasons',snapshot.reasons.join(', ')],
          ['Description',snapshot.description],['Expected completion',snapshot.expected_completion],
        ]);
        const comparison=node('div');
        comparison.append(node('h4','Before'),snapshotRows(before),node('h4','After'),snapshotRows(after));
        content.append(expandable('View changes',comparison));
      }
    }
    if(!record.timetable_url){
      content.append(node('p','The timetable location is not available in the room catalog.'));
    }
    maintenanceAlert({title:'Maintenance Details',html:content,width:740,confirmButtonText:'Close',confirmButtonColor:'#007367',
      customClass:{popup:'cm-request-popup cm-details-popup'},focusConfirm:false,
      didOpen:popup=>{
        if(record.timetable_url){
          const link=node('a','View in Timetable');
          link.href=record.timetable_url;
          link.className='cm-view-timetable';
          popup.querySelector('.swal2-actions').prepend(link);
        }
        const heading=popup.querySelector('.swal2-title');
        heading.tabIndex=-1;
        heading.focus({preventScroll:true});
      }});
  });
  async function finishMaintenance(button, rooms) {
    const action=button.dataset.cmFinish,label={complete:'End',cancel:'Cancel',undo:'Undo'}[action];
    const text = action === 'undo'
      ? `This releases ${rooms.length} unchecked ${rooms.length === 1 ? 'classroom' : 'classrooms'} for all remaining dates in these maintenance schedules.`
      : 'The schedule stays in history and its remaining time is released.';
    const result=await maintenanceAlert({title:label+' this maintenance?',text,
      customClass:{container:'cm-finish-layer',popup:'cm-finish-popup'},
      input:'textarea',inputLabel:'Reason (optional)',inputAttributes:{maxlength:5000},showCancelButton:true,
      confirmButtonText:label+' maintenance',confirmButtonColor:'#007367',showLoaderOnConfirm:true,
      preConfirm:async reason=>{try{return await send(button.dataset.url,{action,reason,token:button.dataset.token,rooms});}catch(problem){Swal.showValidationMessage(problem.message);return false;}}});
    if(result.isConfirmed){
      if (action === 'undo') updates?.postMessage({type:'saved'});
      await maintenanceAlert({icon:'success',title:result.value.message,confirmButtonColor:'#007367',
        customClass:{container:'cm-finish-layer',popup:'cm-success-popup'}});
      reload();
    }
  }
  for (const button of document.querySelectorAll('[data-cm-finish]:not([data-cm-finish="undo"])')) {
    button.addEventListener('click', () => finishMaintenance(button));
  }
  const filterForm=document.querySelector('.cm-filters');
  if(filterForm){
    const options=roomOptions,saved=JSON.parse($('cm-filter-values').textContent);
    const filters=filterForm.elements;
    function select(name,items,placeholder,value=''){
      filters[name].replaceChildren(new Option(placeholder,''),...items.map(([key,label])=>new Option(label,key)));
      filters[name].value=value;
    }
    function update(selected={}){
      const rooms=options.filter(room=>!filters.campus.value||room.campus.toLowerCase()===filters.campus.value.trim().toLowerCase());
      select('building',[...new Map(rooms.map(room=>[room.building_key,room.building]))],'All buildings',selected.building);
      const inBuilding=rooms.filter(room=>!filters.building.value||room.building_key===filters.building.value);
      select('floor',[...new Set(inBuilding.map(room=>room.floor_code||'__unrecorded__'))].sort().map(floor=>[floor,floorLabel(floor)]),'All floors',selected.floor);
      select('room',inBuilding.filter(room=>!filters.floor.value||(room.floor_code||'__unrecorded__')===filters.floor.value).map(room=>[room.key,room.room_name]),'All classrooms',selected.room);
    }
    update(saved);
    filters.campus.addEventListener('change',()=>update());
    filters.building.addEventListener('change',()=>update({building:filters.building.value}));
    filters.floor.addEventListener('change',()=>update({building:filters.building.value,floor:filters.floor.value}));
  }
})();
