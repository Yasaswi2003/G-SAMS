window.BookingNotifications = function (options) {
  const link = document.getElementById('bookingActivityLink');
  const count = document.getElementById('bookingNotificationCount');
  if (!link || !count) return;
  async function updateCount() {
    try {
      const response = await fetch(options.listUrl, {cache:'no-store', credentials:'same-origin'});
      if (!response.ok) return;
      const data = await response.json();
      count.hidden = !data.unread;
      count.textContent = data.unread > 99 ? '99+' : String(data.unread);
      link.setAttribute('aria-label', 'Notifications & Activity' + (data.unread ? ', '+data.unread+' unread' : ''));
    } catch (_) { /* Keep navigation available during a temporary connection failure. */ }
  }
  document.querySelectorAll('[data-notice-id]').forEach(item => item.addEventListener('click', async event => {
    event.preventDefault();
    const payload = new FormData(); payload.set('notification_id', item.dataset.noticeId);
    try {
      const response = await fetch(options.readUrl, {method:'POST', credentials:'same-origin', headers:{'X-CSRFToken':document.querySelector('#bookingNotificationCsrf [name=csrfmiddlewaretoken]').value}, body:payload});
      if (!response.ok) throw new Error('Unable to open this notification. Refresh and try again.');
      location.href = item.href;
    } catch (error) {
      const message = document.getElementById('bn-error');
      if (message) {message.hidden=false; message.textContent=error.message;}
    }
  }));
  const timer=setInterval(() => {if (!document.hidden) updateCount();},15000);
  window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  updateCount();
};
