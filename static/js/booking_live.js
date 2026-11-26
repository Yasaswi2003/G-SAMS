(() => {
window.ClassroomBookingLive=function(options){
 let version=null,busy=false,generation=0;
 async function refresh(force=false){if(busy||BookingLoading.isBusy()||document.hidden||document.querySelector('dialog[open]')||(window.Swal&&Swal.isVisible())||document.activeElement?.closest('form'))return;busy=true;const currentGeneration=generation;try{const response=await fetch(options.versionUrl,{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(currentGeneration!==generation||BookingLoading.isBusy())return;if(version===null&&!force){version=data.version;return;}if(force||data.version!==version){version=data.version;await options.refresh();}}catch(e){/* retry at next interval */}finally{busy=false;}}
 async function acknowledge(){const currentGeneration=++generation;try{const response=await fetch(options.versionUrl,{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(currentGeneration===generation)version=data.version;}catch(e){/* polling will retry */}}
 const interval=setInterval(()=>refresh(),4000);
 window.addEventListener('storage',event=>{if(event.key==='classroom-booking-updated')refresh(true);});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(version===null);});
 window.addEventListener('pagehide',()=>clearInterval(interval),{once:true});
 refresh();
 const update=()=>refresh(true);
 update.acknowledge=acknowledge;
 return update;
};
})();
