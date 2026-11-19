/* Row menus are non-modal dialogs, portalled to body to avoid table clipping. */
(() => {
  let active = null;
  const items = menu => [...menu.querySelectorAll('[role="menuitem"]')];

  function position() {
    if (!active) return;
    const {trigger, menu} = active;
    const anchor = trigger.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = window.innerHeight;
    const margin = 10;
    menu.style.maxHeight = Math.max(80, height - margin * 2) + 'px';
    const bounds = menu.getBoundingClientRect();
    const below = anchor.bottom + 6;
    const top = below + bounds.height <= height - margin ? below : anchor.top - bounds.height - 6;
    menu.style.setProperty('left', Math.max(margin, Math.min(anchor.right - bounds.width, width - bounds.width - margin)) + 'px', 'important');
    menu.style.setProperty('top', Math.max(margin, Math.min(top, height - bounds.height - margin)) + 'px', 'important');
  }

  function close(restoreFocus = false) {
    if (!active) return;
    const {trigger, menu, marker} = active;
    active = null;
    trigger.setAttribute('aria-expanded', 'false');
    menu.close();
    marker.replaceWith(menu);
    menu.style.removeProperty('left');
    menu.style.removeProperty('top');
    if (restoreFocus && trigger.isConnected) trigger.focus();
  }

  function open(trigger, last = false) {
    if (active?.trigger === trigger) {close(true); return;}
    close();
    const menu = document.getElementById(trigger.dataset.bookingMenu);
    if (!menu) return;
    const marker = document.createComment('booking-row-menu');
    menu.replaceWith(marker);
    document.body.append(menu);
    active = {trigger, menu, marker};
    trigger.setAttribute('aria-expanded', 'true');
    menu.style.visibility = 'hidden';
    menu.show();
    position();
    menu.style.removeProperty('visibility');
    const choices = items(menu);
    (last ? choices.at(-1) : choices[0])?.focus({preventScroll: true});
  }

  // Capture closes the menu before existing View/action handlers open a modal.
  document.addEventListener('click', event => {
    const timeline = event.target.closest('.bw-timeline-toggle');
    if (timeline) {
      const panel = document.getElementById(timeline.getAttribute('aria-controls'));
      const expanded = timeline.getAttribute('aria-expanded') !== 'true';
      timeline.setAttribute('aria-expanded', String(expanded));
      panel.classList.toggle('is-expanded', expanded);
      panel.inert = !expanded;
      return;
    }
    const trigger = event.target.closest('[data-booking-menu]');
    if (trigger) {event.preventDefault(); open(trigger); return;}
    if (active && (event.target.closest('[role="menuitem"]') || !active.menu.contains(event.target))) close();
  }, true);

  document.addEventListener('keydown', event => {
    const trigger = event.target.closest('[data-booking-menu]');
    if (trigger && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault(); open(trigger, event.key === 'ArrowUp'); return;
    }
    if (!active) return;
    if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); close(true); return;}
    if (event.key === 'Tab') {close(true); return;}
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const choices = items(active.menu);
    const index = choices.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 :
      (index + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
    choices[next]?.focus();
  });

  window.addEventListener('resize', () => close());
  window.addEventListener('scroll', event => {
    if (active && (event.target === window || event.target === document || !active.menu.contains(event.target))) close();
  }, true);
  document.addEventListener('focusin', event => {
    if (active && !active.menu.contains(event.target) && event.target !== active.trigger) close();
  });
  window.addEventListener('pagehide', () => close(), {once: true});
})();
