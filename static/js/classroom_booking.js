(() => {
const color='#007367';
async function request(url,options,timeoutMessage){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
 try{return await fetch(url,{...options,signal:controller.signal});}
 catch(error){if(error.name==='AbortError')throw new Error(timeoutMessage);throw error;}
 finally{clearTimeout(timer);}
}
function post(url,data){return BookingLoading.run(async()=>{
 const response=await request(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]').value},body:data},'Booking is taking too long to save. Check your requests before retrying to avoid a duplicate.');
 let result;try{result=await response.json();}catch(e){throw new Error('The server could not process the request. Please refresh and retry.');}
 if(!response.ok){const error=new Error(result.error||'Request failed.');error.payload=result;throw error;}
 return result;
});}
function announce(){localStorage.setItem('classroom-booking-updated',String(Date.now()));}
function isConflict(error){return error?.payload?.code==='booking_conflict'&&['hold','booked'].includes(error.payload.conflict?.availability);}
function checkAvailability(payload,options){
 if(!options.availabilityUrl)return;
 return BookingLoading.run(async()=>{
  const response=await request(options.availabilityUrl+'?'+new URLSearchParams(payload),{credentials:'same-origin',cache:'no-store'},'Availability is taking too long to check. Please retry.');
  let result;try{result=await response.json();}catch(e){throw new Error('Availability could not be checked. Please retry.');}
  if(!response.ok||result.available!==true){const error=new Error(result.error||'Availability could not be verified.');error.payload=result;throw error;}
 });
}
function showConflict(error,onChange){
 if(!isConflict(error))return Promise.resolve(false);
 const hold=error.payload.conflict.availability==='hold';
 const dialog=document.createElement('dialog');dialog.className='cb-conflict-sheet';dialog.setAttribute('role','alertdialog');
 dialog.setAttribute('aria-labelledby','cb-conflict-title');dialog.setAttribute('aria-describedby','cb-conflict-message');
 dialog.innerHTML='<div class="cb-conflict-icon" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="11" width="32" height="30" rx="5"/><path d="M15 7v9m18-9v9M8 21h32M19 27l10 9m0-9l-10 9"/></svg></div><h2 id="cb-conflict-title"></h2><p id="cb-conflict-message"></p><button type="button" autofocus>Change Classroom</button>';
 dialog.querySelector('h2').textContent=hold?'This classroom is temporarily on hold':'This classroom is already booked';
 dialog.querySelector('p').textContent=hold?
  'Unfortunately, this classroom is currently reserved by another faculty member and is waiting for HOD approval. Please select a different classroom or time slot to continue.':
  'This classroom has an approved booking during the selected time. Please select a different classroom or time slot to continue.';
 document.body.append(dialog);document.documentElement.classList.add('cb-conflict-open');
 return new Promise(resolve=>{
  dialog.querySelector('button').addEventListener('click',()=>dialog.close('change'));
  dialog.addEventListener('close',()=>{dialog.remove();document.documentElement.classList.remove('cb-conflict-open');if(onChange)onChange();resolve(true);},{once:true});
  dialog.showModal();
 });
}
function prepare(form,options){
 form.noValidate=true;
 const rooms=options.rooms, campus=form.elements.campus, building=form.elements.building, room=form.elements.room_key;
 function setOptions(select,items,title){select.replaceChildren(new Option(title,''));new Map(items).forEach((text,value)=>select.add(new Option(text,value)));}
 setOptions(campus,rooms.map(r=>[r.campus,r.campus]),'Select campus');
 function buildings(){setOptions(building,rooms.filter(r=>r.campus===campus.value).map(r=>[r.building_key,r.building]),'Select building');roomList();}
 function roomList(){setOptions(room,rooms.filter(r=>r.campus===campus.value&&r.building_key===building.value).map(r=>[r.key,r.room_name+' ('+r.room_code+')']),'Select classroom');capacity();}
 function capacity(){const selected=rooms.find(r=>r.key===room.value);if(form.elements.floor)form.elements.floor.value=selected?.floor_code||'';const hint=form.querySelector('[data-capacity]');if(hint)hint.textContent=selected?'Floor: '+(selected.floor_code||'Not recorded')+' ? Room capacity: '+(selected.capacity??'Not provided'):'';}
 campus.addEventListener('change',buildings);building.addEventListener('change',roomList);room.addEventListener('change',capacity);
 const start=form.elements.from_time,duration=form.elements.duration_hours,end=form.elements.to_time;
 const summary=form.querySelector('[data-revision-summary]');
 function updateSummary(){
  if(!summary)return;
  const selected=rooms.find(item=>item.key===room.value);
  const date=form.elements.booking_date.value;
  const time=start.value&&end.value?`${start.value} – ${end.value} (${duration.value} ${duration.value==='1'?'hr':'hrs'})`:'';
  const values=[['Campus',selected?.campus],['Building',selected?.building],['Classroom',selected?.room_name],['Floor',selected?.floor_code],
   ['Booking date',date],['Time',time]];
  summary.replaceChildren(...values.map(([label,value])=>{
   const field=document.createElement('div'),term=document.createElement('dt'),description=document.createElement('dd');
   term.textContent=label;description.textContent=value||'—';field.append(term,description);return field;
  }));
 }
 form.elements.booking_date.min=new Date().toLocaleDateString('en-CA');start.min='08:00';start.max=options.respond||options.extended?'21:00':'15:00';start.step='3600';end.readOnly=true;
 function recalculate(){let n=Math.max(1,Math.min(8,Number(duration.value)||1));const parts=start.value.split(':').map(Number),minute=parts[0]*60+parts[1];const max=Number.isFinite(minute)?Math.max(1,Math.floor(((options.respond||options.extended?1320:960)-minute)/60)):8;n=Math.min(n,max);duration.value=n;const finish=minute+n*60;end.value=Number.isFinite(finish)&&finish<=(options.respond||options.extended?1320:960)?String(Math.floor(finish/60)).padStart(2,'0')+':'+String(finish%60).padStart(2,'0'):'';const range=form.querySelector('[data-time-range]');if(range)range.textContent=start.value&&end.value?start.value+' - '+end.value+' ('+n+' hour'+(n===1?'':'s')+')':'';form.querySelectorAll('[data-duration-step]').forEach(button=>button.disabled=Number(button.dataset.durationStep)<0?n<=1:n>=max);updateSummary();}
 function applySelection(values){
  const selected=rooms.find(r=>r.key===values.room_key);
  if(selected){campus.value=selected.campus;buildings();building.value=selected.building_key;roomList();room.value=selected.key;capacity();}
  for(const name of ['booking_date','from_time','duration_hours'])if(values[name])form.elements[name].value=values[name];
  recalculate();
 }
 form.querySelectorAll('[data-duration-step]').forEach(button=>button.addEventListener('click',()=>{duration.value=Number(duration.value)+Number(button.dataset.durationStep);recalculate();}));start.addEventListener('change',recalculate);duration.addEventListener('change',recalculate);
 applySelection(options.initial||{});
 const check=form.querySelector('[data-check-availability]');if(check)check.addEventListener('click',async()=>{try{if(!form.checkValidity()){form.reportValidity();return;}await checkAvailability(new FormData(form),options);const hint=form.querySelector('[data-capacity]');if(hint)hint.textContent='Available. Availability is checked again on submission.';}catch(error){if(isConflict(error))await showConflict(error,()=>room.focus());else if(Swal.isVisible())Swal.showValidationMessage(error.message);else await Swal.fire({icon:'warning',title:'Classroom unavailable',text:error.message,confirmButtonColor:color});}});

 const collect=()=>{recalculate();if(!form.checkValidity()){const invalid=form.querySelector(':invalid');throw new Error(invalid?invalid.validationMessage:'Complete all required booking fields.');}return new FormData(form);};
 return {collect,applySelection};
}
async function success(result,options){announce();await Swal.fire({icon:'success',title:options.respond?'Booking Resubmitted Successfully!':options.mode==='edit'?'Request updated':options.mode==='request_amendment'?'Amendment requested':options.role==='ADMIN'?'Booking confirmed':'Request submitted',text:options.respond?'Your revised classroom booking request has been submitted successfully and is awaiting the required approval.':result.message,confirmButtonText:'OK',confirmButtonColor:color});if(options.onSuccess)await options.onSuccess(result);}
function bind(form,options){
 const {collect}=prepare(form,options);
 form.addEventListener('submit',async event=>{
  event.preventDefault();let payload;
  try{payload=collect();await checkAvailability(payload,options);}catch(error){
   if(isConflict(error))await showConflict(error,()=>form.elements.room_key.focus());
   else await Swal.fire({icon:'warning',title:'Check booking details',text:error.message,confirmButtonColor:color});
   return;
  }
  let conflictError=null;
  const result=await Swal.fire({icon:'question',title:options.role==='ADMIN'?'Confirm direct booking?':'Submit classroom request?',text:'Selected time: '+payload.get('booking_date')+' / '+payload.get('from_time')+' - '+payload.get('to_time'),showCancelButton:true,confirmButtonColor:color,confirmButtonText:options.role==='ADMIN'?'Confirm Booking':'Submit to HOD',showLoaderOnConfirm:true,allowOutsideClick:()=>!Swal.isLoading(),preConfirm:async()=>{
   try{return await post(options.submitUrl,payload);}catch(error){if(isConflict(error)){conflictError=error;Swal.close();return false;}Swal.showValidationMessage(error.message);return false;}
  }});
  if(conflictError){await showConflict(conflictError,()=>form.elements.room_key.focus());return;}
  if(result.isConfirmed)await success(result.value,options);
 });
}

async function chooseRevisionSlot(loadTimetable,checkbox,applySelection){
 const dialog=document.createElement('dialog');dialog.className='cb-revision-timetable';dialog.setAttribute('aria-label','Classroom Utilization');
 const close=document.createElement('button');close.type='button';close.textContent='Back to Form';
 const content=document.createElement('div');content.className='cb-revision-timetable-content';
 const frame=document.createElement('iframe');frame.title='Classroom Utilization';frame.dataset.revisionTimetable='';
 let stopLoading;
 frame.addEventListener('revision-timetable-ready',()=>{close.hidden=true;});
 close.addEventListener('click',()=>dialog.close());
 frame.addEventListener('revision-slot-selected',event=>{applySelection(event.detail);dialog.close();});
 dialog.addEventListener('close',()=>{stopLoading?.();dialog.remove();checkbox.checked=false;checkbox.disabled=false;checkbox.focus();},{once:true});
 content.append(frame);dialog.append(close,content);document.body.append(dialog);dialog.showModal();
 try{
  await BookingLoading.run(async()=>{
   const url=await loadTimetable();
   if(!dialog.open)return;
   const address=new URL(url,location.href);address.searchParams.set('revision_popup','1');
   stopLoading=BookingLoading.loadFrame(frame,address.href);
  });
 }catch(error){if(dialog.open){dialog.close();Swal.showValidationMessage(error.message);}}
}

function revisionComparison(payload,options){
 const previous=options.original||options.initial;
 const room=options.rooms.find(item=>item.key===payload.get('room_key'));
 const formatDate=value=>value?new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeZone:'UTC'}).format(new Date(value+'T00:00:00Z')):'';
 const formatTime=value=>value?new Intl.DateTimeFormat('en-US',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'}).format(new Date('2000-01-01T'+value+'Z')):'';
 const hours=value=>value?`${value} ${Number(value)===1?'hour':'hours'}`:'';
 const fields=[
  ['Campus',previous.campus,room?.campus],['Building',previous.building,room?.building],
  ['Floor',previous.floor,room?.floor_code],['Classroom',previous.room_name,room?.room_name,previous.room_key!==payload.get('room_key')],
  ['Booking Date',previous.booking_date,payload.get('booking_date'),undefined,formatDate],
  ['Start Time',previous.from_time,payload.get('from_time'),undefined,formatTime],
  ['End Time',previous.to_time,payload.get('to_time'),undefined,formatTime],
  ['Duration',previous.duration_hours,payload.get('duration_hours'),undefined,hours],
  ['Purpose',previous.purpose,payload.get('purpose')],['Response Comment','',payload.get('comment')],
 ];
 const table=document.createElement('table');table.className='cb-revision-comparison';
 const header=table.createTHead().insertRow();
 for(const label of ['Field','Previous Details','Updated Details']){const cell=document.createElement('th');cell.scope='col';cell.textContent=label;header.append(cell);}
 const body=table.createTBody();
 for(const [label,oldValue,newValue,changed,format=String] of fields){
  const before=String(oldValue??'').trim(),after=String(newValue??'').trim();
  if(!(changed??(before!==after)))continue;
  const row=body.insertRow(),field=document.createElement('th');field.scope='row';field.textContent=label;row.append(field);
  row.insertCell().textContent=format(before)||'—';row.insertCell().textContent=format(after)||'—';
 }
 if(body.rows.length)return table;
 const note=document.createElement('p');note.textContent='No changes were detected.';return note;
}

async function open(options){
 const form=document.createElement('form');form.className='cb-popup-form'+(options.respond||options.selectOnly?' cb-revision-form':'');form.noValidate=true;
 form.innerHTML='<div class="cb-grid"><label>Campus<select name="campus" required></select></label><label>Building<select name="building" required></select></label><label>Classroom<select name="room_key" required></select></label><label>Floor<input name="floor" readonly placeholder="Not recorded"></label><label>Booking date<input name="booking_date" type="date" required></label><label>Starting time<input name="from_time" type="time" required></label><label>Duration<div class="cb-duration"><button type="button" data-duration-step="-1" aria-label="Decrease duration">&minus;</button><input name="duration_hours" value="1" type="number" min="1" max="8" readonly aria-label="Duration in hours"><span>Hour(s)</span><button type="button" data-duration-step="1" aria-label="Increase duration">+</button></div></label><label>Ending time<input name="to_time" type="time" readonly required></label><label>Subject code<input name="subject_code" maxlength="50"></label><label>Subject name<input name="subject_name" maxlength="150"></label></div><p data-capacity></p><p class="cb-time-range" data-time-range></p><label>Purpose of booking<textarea name="purpose" rows="3" required maxlength="5000"></textarea></label>';
 form.elements.subject_code.value=options.subjectCode||'';form.elements.subject_name.value=options.subjectName||'';
 form.elements.purpose.value=options.initial?.purpose||'';
 if(options.mode){form.elements.subject_code.readOnly=true;form.elements.subject_name.readOnly=true;}
 if(options.respond&&!options.selectOnly){const label=document.createElement('label');label.textContent='Comment (optional)';const comment=document.createElement('textarea');comment.name='comment';comment.rows=2;comment.maxLength=5000;comment.value=options.initial?.comment||'';comment.placeholder='Enter your changes';label.append(comment);form.append(label);}
 if(options.respond){const summary=document.createElement('p');summary.className='cb-subject-summary';summary.textContent=[options.subjectCode,options.subjectName].filter(Boolean).join(' / ');if(summary.textContent)form.append(summary);for(const name of ['subject_code','subject_name'])form.elements[name].closest('label').hidden=true;}

 if(options.selectOnly){for(const name of ['purpose','subject_code','subject_name']){form.elements[name].required=false;form.elements[name].closest('label').hidden=true;}}
 if(options.respond||options.selectOnly){
  const summary=document.createElement('dl');summary.className='cb-revision-summary';summary.dataset.revisionSummary='';form.prepend(summary);
  for(const name of ['campus','building','room_key','floor','booking_date','from_time','to_time',...(options.selectOnly?[]:['duration_hours'])])form.elements[name].closest('label').hidden=true;
  form.querySelector('[data-capacity]').hidden=true;form.querySelector('[data-time-range]').hidden=true;
 }
 if(options.mode==='request_amendment'){const label=document.createElement('label');label.textContent='Reason for amendment';const reason=document.createElement('textarea');reason.name='comment';reason.required=true;reason.rows=2;label.append(reason);form.append(label);}
 const {collect,applySelection}=prepare(form,options);
 if(options.respond&&!options.selectOnly&&options.revisionStartUrl){
  const link=document.createElement('label');link.className='cb-timetable-navigation';
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.className='cb-timetable-checkbox';
  const text=document.createElement('span');text.textContent='Select a different room or time using the Classroom Timetable';link.append(checkbox,text);
  checkbox.addEventListener('change',async()=>{
   if(!checkbox.checked||checkbox.disabled)return;
   checkbox.disabled=true;
   await chooseRevisionSlot(async()=>{
    const data=new FormData(form);data.set('booking_id',options.bookingId);data.set('expected_revision',options.revision);
    if(options.revisionToken)data.set('revision_token',options.revisionToken);
    const result=await post(options.revisionStartUrl,data);
    options.revisionToken=result.token;
    return result.timetable_url;
   },checkbox,applySelection);
  });
  form.prepend(link);
 }
 const result=await Swal.fire({title:options.selectOnly?'Select a replacement slot':options.respond?'Booking Revision':options.mode==='edit'?'Edit & Resubmit Booking':options.mode==='request_amendment'?'Request Booking Amendment':options.role==='ADMIN'?'Admin Direct Booking':'Book a Classroom',html:form,width:options.respond&&!options.selectOnly?840:760,customClass:options.respond&&!options.selectOnly?{popup:'cb-revision-popup'}:{},showCancelButton:true,cancelButtonText:options.onBackToForm?'Back to Form':'Cancel',confirmButtonText:options.selectOnly?'Use this slot':options.mode==='edit'?'Save & Resubmit':options.mode==='request_amendment'?'Submit Amendment':options.role==='ADMIN'?'Confirm Booking':'Submit to HOD',confirmButtonColor:color,showLoaderOnConfirm:true,allowOutsideClick:()=>!Swal.isLoading(),preConfirm:async()=>{try{const payload=collect();if(options.mode){payload.set('action',options.mode);payload.set('booking_id',options.bookingId);if(options.revision)payload.set('expected_revision',options.revision);}if(options.revisionToken)payload.set('revision_token',options.revisionToken);if(options.respond&&!options.selectOnly)return {revisionPayload:payload};return await post(options.submitUrl,payload);}catch(error){if(isConflict(error)){await showConflict(error,()=>form.elements.room_key.focus());if(options.respond&&!options.selectOnly)form.querySelector('.cb-timetable-checkbox:not(:checked)')?.click();return false;}Swal.showValidationMessage(error.message);if(options.respond&&!options.selectOnly&&error.payload?.code==='slot_unavailable')form.querySelector('.cb-timetable-checkbox:not(:checked)')?.click();return false;}}});
 if(result.isConfirmed){
  if(options.selectOnly){if(options.onSelection)await options.onSelection(result.value);}
  else if(result.value?.revisionPayload){
   const payload=result.value.revisionPayload;
   const confirmation=await Swal.fire({
    title:'Review Your Booking Changes',html:revisionComparison(payload,options),width:760,
    showDenyButton:true,showCancelButton:true,confirmButtonText:'Confirm & Submit',
    denyButtonText:'Go Back & Edit',cancelButtonText:'Cancel',confirmButtonColor:color,denyButtonColor:'#386e67',
    showLoaderOnConfirm:true,allowOutsideClick:()=>!Swal.isLoading(),allowEscapeKey:()=>!Swal.isLoading(),
    preConfirm:async()=>{try{return await post(options.submitUrl,payload);}catch(error){Swal.showValidationMessage(error.message);return false;}},
   });
   if(confirmation.isConfirmed)await success(confirmation.value,options);
   else await open({...options,initial:Object.fromEntries(payload)});
  }else await success(result.value,options);
 }else if(result.dismiss===Swal.DismissReason.cancel){
  options.onBackToForm?.();
 }
}
window.ClassroomBooking={bind,open,announce,showConflict};
})();
