(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('cm-planner');
  if (!dialog) return;
  const form = $('cm-form'), fields = form.elements;
  const records = JSON.parse($('cm-records')?.textContent || '{}');
  const roomOptions = JSON.parse($('cm-room-options')?.textContent || '[]');
  const updates = typeof BroadcastChannel === 'function' ? new BroadcastChannel('classroom-maintenance') : null;
  updates?.addEventListener('message', () => {
    if (document.querySelector('[data-cm-region][data-cm-mode="timetable"]') && !dialog.open && !Swal.isVisible()) {
      location.reload();
    }
  });
  const maintenanceAlert = options => Swal.fire({
    ...options,
    customClass: {
      ...options.customClass,
      container: 'cm-alert-layer',
      popup: ['cm-alert-popup', options.customClass?.popup].filter(Boolean).join(' '),
    },
  });
  let current, selections, onCancel;

  function node(tag,text) {
    const item=document.createElement(tag);
    if(text!=null)item.textContent=text;
    return item;
  }
  async function send(url,payload) {
    const response=await fetch(url,{method:'POST',headers:{
      'Content-Type':'application/json','X-CSRFToken':fields.csrfmiddlewaretoken.value,
    },body:JSON.stringify(payload)});
    let data;
    try{data=await response.json();}
    catch{throw new Error('Maintenance could not be updated. Refresh and try again.');}
    if(!response.ok)throw new Error(data.error||'Maintenance request failed.');
    return data;
  }
  function error(text='') {
    $('cm-error').textContent=text;
    $('cm-error').hidden=!text;
  }
  const dateLabel=date=>date?new Date(date+'T12:00:00').toLocaleDateString(undefined,{weekday:'short',year:'numeric',month:'short',day:'numeric'}):'';
  const floorLabel=floor=>floor==='__unrecorded__'?'Not recorded':floor;
  const scopeLabel=scope=>({room:'Classroom',floor:'Entire floor',building:'Entire building'})[scope];
  const selectionText=items=>items.map(item=>dateLabel(item.date)+' · '+item.start+'–'+item.end).join('\n');
  const sortSelections=items=>[...items].sort((a,b)=>a.date.localeCompare(b.date)||a.start.localeCompare(b.start));

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
  function dateRange(first,last) {
    const days=[];
    const cursor=new Date(first+'T12:00:00Z'), end=new Date(last+'T12:00:00Z');
    for(;cursor<=end&&days.length<=366;cursor.setUTCDate(cursor.getUTCDate()+1)){
      days.push({date:cursor.toISOString().slice(0,10),start:'00:00',end:'23:59'});
    }
    return days;
  }
  function scheduleReview(windows,roomLabel) {
    const section=node('section');section.className='cm-schedule-review';
    section.append(node('h3','Selected Maintenance Schedule'));
    const sorted=sortSelections(windows), first=sorted[0], last=sorted.at(-1);
    section.append(rows([
      ['Selected dates',String(new Set(sorted.map(item=>item.date)).size)],
      ['Selected time slots',String(sorted.length)],
      ['First selected date and time',first?dateLabel(first.date)+' · '+first.start:''],
      ['Last selected date and time',last?dateLabel(last.date)+' · '+last.end:''],
    ]));
    const weeks=new Map();
    for(const item of sorted){
      if(!item.date)continue;
      const monday=new Date(item.date+'T12:00:00Z');
      monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
      const key=monday.toISOString().slice(0,10);
      if(!weeks.has(key))weeks.set(key,new Map());
      const dates=weeks.get(key);
      if(!dates.has(item.date))dates.set(item.date,[]);
      dates.get(item.date).push(item);
    }
    const dateFormat=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
    const shortDateFormat=new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'});
    const weekdayFormat=new Intl.DateTimeFormat('en-GB',{weekday:'long',timeZone:'UTC'});
    for(const [week,dates] of weeks){
      const monday=new Date(week+'T12:00:00Z'),end=new Date(monday);
      const lastDay=new Date([...dates.keys()].at(-1)+'T12:00:00Z').getUTCDay();
      end.setUTCDate(end.getUTCDate()+(lastDay===0?6:lastDay===6?5:4));
      const wrap=node('div');wrap.className='cm-table-wrap';
      const table=node('table');table.className='cm-table';
      const header=table.createTHead().insertRow();
      for(const label of ['Date','Day','Selected time slots','Classroom']){
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
        row.insertCell().textContent=roomLabel;
      }
      wrap.append(table);
      const group=expandable(dateFormat.format(monday)+' to '+dateFormat.format(end),wrap);
      group.open=true;
      section.append(group);
    }
    return section;
  }
  function refreshSummary() {
    const target=current.target;
    $('cm-target').replaceChildren(rows([
      ['Scope',scopeLabel(target.scope)],['Campus / Building',target.campus+' / '+current.buildingLabel],
      ['Floor',current.floorLabel],['Classroom(s)',current.roomLabel],
    ]));
    $('cm-selected-schedule').replaceChildren(scheduleReview(current.allDay?boundedWindows():selections,current.roomLabel));
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
  for(const field of [fields.starts_at,fields.expected_completion])field.addEventListener('input',()=>{
    if(current.allDay)refreshSummary();
  });
  function renderEditableWindows() {
    const container=$('cm-selections');container.replaceChildren();
    for(const entry of selections){
      const row=node('div');row.className='cm-day-row';
      for(const [property,label,type] of [['date','Date','date'],['start','From','time'],['end','To','time']]){
        const wrapper=node('label',label),input=node('input');input.type=type;input.required=true;input.value=entry[property];
        input.addEventListener('change',()=>{entry[property]=input.value;refreshSummary();});
        wrapper.append(input);row.append(wrapper);
      }
      const remove=node('button','Remove');remove.type='button';
      remove.addEventListener('click',()=>{selections=selections.filter(item=>item!==entry);renderEditableWindows();refreshSummary();});
      row.append(remove);container.append(row);
    }
  }
  function openDetails(target,windows,options={}) {
    current={target,...options};
    selections=sortSelections(windows).map(entry=>({...entry}));
    onCancel=options.cancel;
    form.reset();error();
    const record=options.record;
    const editRooms=$('cm-edit-rooms'), choices=$('cm-room-choices');
    editRooms.hidden=record?.scope!=='room';
    editRooms.open=false;
    choices.querySelectorAll('label').forEach(label=>label.remove());
    if(!editRooms.hidden){
      for(const room of roomOptions.filter(room=>room.building_key===record.building)){
        const label=node('label'), input=node('input');
        input.type='checkbox';
        input.value=room.key;
        input.checked=record.targets.includes(room.key)||record.room===room.key;
        label.append(input, document.createTextNode(room.room_name+' · Floor '+floorLabel(room.floor_code||'__unrecorded__')));
        choices.append(label);
      }
    }
    fields.reason.value=record?.reasons[0]||'';
    const first=selections[0],last=selections.at(-1);
    fields.starts_at.value=first?first.date+'T'+first.start:'';
    fields.starts_at.readOnly=Boolean(options.selectedWindows?.length);
    const lastWindow=last?last.date+'T'+last.end:'';
    fields.expected_completion.value=record?.expected_completion>lastWindow?record.expected_completion:lastWindow;
    fields.description.value=record?.description||'';
    fields.start_date.value=record?.start_date||'';
    fields.end_date.value=record?.end_date||'';
    $('cm-title').textContent=record?'Edit Maintenance':'Maintenance Details';
    $('cm-edit-schedule').hidden=!record;
    $('cm-edit-schedule').open=false;
    $('cm-recurrence').hidden=!record?.recurrence;
    dialog.querySelector('[data-cm-back]').hidden=!options.cancel;
    if(record)renderEditableWindows();
    else $('cm-selections').replaceChildren();
    refreshSummary();dialog.showModal();
  }
  $('cm-add-window').addEventListener('click',()=>{
    selections.push({...selections.at(-1) || {date:'',start:'08:00',end:'16:00'}});
    renderEditableWindows();
  });
  dialog.querySelector('[data-cm-back]').addEventListener('click',()=>dialog.close());
  function cancelDetails(){dialog.close();onCancel?.();}
  dialog.querySelector('[data-cm-close]').addEventListener('click',cancelDetails);
  dialog.addEventListener('cancel',event=>{event.preventDefault();cancelDetails();});

  function bindSelection(region) {
    const start=region.querySelector('[data-cm-start]'), bar=region.querySelector('[data-cm-selection-bar]');
    if(!start||!bar)return;
    const mode=region.dataset.cmMode, timetable=mode==='timetable';
    const storageKey='maintenance-selection:'+region.dataset.room;
    const cards=[...region.querySelectorAll('[data-cm-card]')], days=[...region.querySelectorAll('[data-cm-day]')];
    const slots=[...region.querySelectorAll('[data-cm-slot]')];
    const cells=[...region.querySelectorAll('[data-cm-date]')];
    const displayedDates=new Set(cells.map(cell=>cell.dataset.cmDate));
    const proceed=bar.querySelector('[data-cm-proceed]'), count=bar.querySelector('[data-cm-count]');
    const first=bar.querySelector('[data-cm-from]'),last=bar.querySelector('[data-cm-to]'),whole=bar.querySelector('[data-cm-whole-building]');
    const pickedSlots=new Map(), pickedCards=new Map();
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
        const input=node('input');input.type='checkbox';input.setAttribute('aria-label','Select '+card.querySelector('strong').textContent);
        card.before(wrapper);wrapper.append(card,input);pickedCards.set(card,input);
        input.addEventListener('change',()=>{
          if(whole&&!input.checked)whole.checked=false;
          synchronize();
        });
      }
      if(!timetable){first.value=date;last.value=date;last.min=date;}
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
      start.closest('details').open=false;
      if(active)return;
      activate();
    });
    bar.querySelector('[data-cm-cancel]').addEventListener('click',cancel);
    region.querySelector('[data-cm-exit]')?.addEventListener('click',()=>{active=false;saveDraft();});
    proceed.addEventListener('click',()=>{
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
  form.addEventListener('submit',async event=>{
    event.preventDefault();error();
    const operation=current;
    const data=new FormData(form),record=operation.record;
    const expected=data.get('expected_completion');
    const start=data.get('starts_at');
    if(!start||!expected||start>=expected){error('Expected completion must be after the start date and time.');return;}
    const fixedSlots=operation.selectedWindows?.length;
    if(fixedSlots&&selections.some(item=>item.date+'T'+item.start<start||item.date+'T'+item.end>expected)){
      error('Start and completion must cover every selected slot. Use Back to change the selected slots.');return;
    }
    const windows=fixedSlots||record?.recurrence?selections:boundedWindows();
    if(!windows.length){error('The date and time range must include at least one selected maintenance window.');return;}
    const reason=data.get('reason');
    const target={...operation.target};
    if(record?.scope==='room'){
      target.targets=[...$('cm-room-choices').querySelectorAll('input:checked')].map(input=>input.value);
      if(!target.targets.length){error('Select at least one classroom.');return;}
      const original=record.targets.length?record.targets:[record.room];
      if(target.targets.length!==original.length||target.targets.some(key=>!original.includes(key))){
        target.booking_ids=[];
        target.timetable_selection=false;
      }
      target.room='';
      target.floor='';
    }
    const payload={...target,action:'preview',duration:record?.duration,
      description:data.get('description'),reasons:record?.reasons[0]===reason?record.reasons:[reason],
      expected_completion:expected,starts_at:record?.recurrence?undefined:start,
      recurrence:Boolean(record?.recurrence),start_date:data.get('start_date'),end_date:data.get('end_date'),
      selections:sortSelections(windows)};
    const submit=form.querySelector('[type="submit"]');
    submit.disabled=true;
    try{
      const review=await send(dialog.dataset.scheduleUrl,payload);
      if(!dialog.open||current!==operation)return;
      const content=node('div');
      content.append(node('p','Place the selected location under maintenance?'),rows([
        ['Scope',scopeLabel(payload.scope)],['Campus / Building',review.campus+' / '+review.building],
        ['Floor',review.floor ? floorLabel(review.floor) : scopeLabel(payload.scope)],['Affected classrooms',review.room_codes.length>1
          ?expandable('View '+review.room_codes.length+' classrooms',node('p',review.room_codes.join(', ')))
          :review.room_codes[0]],
        ['Start Date & Time',start.replace('T',' ')],['End Date & Time',expected.replace('T',' ')],
        ['Reason',payload.reasons.join(', ')],
      ]),scheduleReview(windows,record?.scope==='room'?review.room_codes.join(', '):operation.roomLabel));
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
        await maintenanceAlert({icon:'success',title:'Maintenance saved',showConfirmButton:false,timer:2000});
        location.reload();
      }else if(current===operation&&!dialog.open){
        dialog.showModal();
      }
    }catch(problem){
      if(current===operation&&dialog.open)error(problem.message);
    }
    finally{submit.disabled=false;}
  });
  $('cm-new-reason').addEventListener('click',async()=>{
    dialog.close();
    const result=await maintenanceAlert({title:'Add Maintenance Reason',width:420,customClass:{popup:'cm-reason-popup'},returnFocus:false,input:'text',inputAttributes:{maxlength:120},
      confirmButtonText:'Save reason',confirmButtonColor:'#007367',showCancelButton:true,showLoaderOnConfirm:true,
      preConfirm:async name=>{try{return await send(dialog.dataset.reasonUrl,{name});}catch(problem){Swal.showValidationMessage(problem.message);return false;}}});
    dialog.showModal();
    $('cm-new-reason').focus();
    if(!result.isConfirmed)return;
    const name=result.value.name;
    if(![...fields.reason.options].some(option=>option.value===name))fields.reason.add(new Option(name,name));
    fields.reason.value=name;
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
      ['Expected completion',record.expected_completion],['Created',record.created_by+' · '+new Date(record.created_at).toLocaleString()],
      ['Last modified',record.updated_by+' · '+new Date(record.updated_at).toLocaleString()]]));
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
    maintenanceAlert({title:'Rq ID '+record.id,html:content,width:740,confirmButtonText:'Close',confirmButtonColor:'#007367',
      customClass:{popup:'cm-request-popup'},focusConfirm:false,
      didOpen:popup=>{
        const heading=popup.querySelector('.swal2-title');
        heading.tabIndex=-1;
        heading.focus({preventScroll:true});
      }});
  });
  for(const button of document.querySelectorAll('[data-cm-finish]'))button.addEventListener('click',async()=>{
    const action=button.dataset.cmFinish,label={complete:'End',cancel:'Cancel'}[action];
    const result=await maintenanceAlert({title:label+' this maintenance?',text:'The schedule stays in history and its remaining time is released.',
      input:'textarea',inputLabel:'Reason (optional)',inputAttributes:{maxlength:5000},showCancelButton:true,
      confirmButtonText:label+' maintenance',confirmButtonColor:'#007367',showLoaderOnConfirm:true,
      preConfirm:async reason=>{try{return await send(button.dataset.url,{action,reason});}catch(problem){Swal.showValidationMessage(problem.message);return false;}}});
    if(result.isConfirmed){await maintenanceAlert({icon:'success',title:result.value.message,confirmButtonColor:'#007367'});location.reload();}
  });
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
