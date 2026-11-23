(() => {
window.ClassroomBookingLive=function(options){
 let version=null,busy=false;
 async function refresh(force=false){if(busy||BookingLoading.isBusy()||document.hidden||document.querySelector('dialog[open]')||(window.Swal&&Swal.isVisible())||document.activeElement?.closest('form'))return;busy=true;try{const response=await fetch(options.versionUrl,{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(BookingLoading.isBusy())return;if(version===null&&!force){version=data.version;return;}if(force||data.version!==version){version=data.version;await options.refresh();}}catch(e){/* retry at next interval */}finally{busy=false;}}
 const interval=setInterval(()=>refresh(),4000);
 window.addEventListener('storage',event=>{if(event.key==='classroom-booking-updated')refresh(true);});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(true);});
 window.addEventListener('pagehide',()=>clearInterval(interval),{once:true});
 refresh();return ()=>refresh(true);
};
})();
