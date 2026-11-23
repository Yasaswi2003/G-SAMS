(() => {
    const overlay = document.getElementById('booking-loading');
    const status = overlay.querySelector('[role="status"]');
    const paths = new Set(document.body.dataset.bookingPaths?.split(' '));
    const bookingPage = paths.has(location.pathname);
    if (bookingPage) document.body.dataset.bookingPage = '';

    const pending = new Set();
    let showTimer, hideTimer, navigation;

    function hide() {
        if (overlay.isConnected) overlay.hidePopover?.();
        overlay.hidden = true;
        status.textContent = '';
        document.body.append(overlay);
    }

    function overlayHost() {
        const dialogs = document.querySelectorAll('dialog[open]');
        return dialogs[dialogs.length - 1] || document.body;
    }

    function show() {
        const host = overlayHost();
        if (overlay.parentElement !== host) host.append(overlay);
        overlay.classList.remove('is-leaving');
        overlay.hidden = false;
        overlay.showPopover?.();
        // Commit the initial opacity before starting the transition.
        overlay.getBoundingClientRect();
        overlay.classList.add('is-visible');
        status.textContent = 'Loading…';
    }

    function begin() {
        let finishParent;
        try {
            if (window.parent !== window) finishParent = window.parent.BookingLoading?.begin();
        } catch { /* A standalone embedded page can use its own indicator. */ }

        const finish = () => {
            if (!pending.delete(finish)) return;
            finishParent?.();
            if (pending.size) return;
            clearTimeout(showTimer);
            if (overlay.hidden) return;
            overlay.classList.remove('is-visible');
            overlay.classList.add('is-leaving');
            hideTimer = setTimeout(hide, 140);
        };
        if (!pending.size && !finishParent) {
            clearTimeout(hideTimer);
            if (overlay.hidden) showTimer = setTimeout(show, 160);
            else if (overlay.parentElement !== overlayHost()) show();
            else {
                overlay.classList.remove('is-leaving');
                overlay.classList.add('is-visible');
            }
        }
        pending.add(finish);
        return finish;
    }

    async function run(operation) {
        const finish = begin();
        try { return await operation(); }
        finally { finish(); }
    }

    function startNavigation() {
        if (navigation) return;
        const finish = begin();
        navigation = () => {
            navigation = null;
            finish();
        };
    }

    function navigate(action) {
        if (pending.size) return;
        startNavigation();
        try { action(); }
        catch (error) {
            navigation?.();
            throw error;
        }
    }

    function loadFrame(frame, url) {
        const finish = begin();
        const controller = new AbortController();
        const stop = () => {
            controller.abort();
            finish();
        };
        frame.addEventListener('load', () => {
            if (frame.contentDocument?.URL !== 'about:blank') stop();
        }, {signal: controller.signal});
        frame.addEventListener('error', stop, {signal: controller.signal});
        try { frame.src = url; }
        catch (error) {
            stop();
            throw error;
        }
        return stop;
    }

    function isPageNavigation(url) {
        return url.origin === location.origin && !url.searchParams.has('export') &&
            paths.has(url.pathname);
    }

    function blockWhilePending(event) {
        if (!pending.size) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }

    // Lock interactions immediately, even while the visual indicator is delayed.
    for (const type of ['click', 'submit', 'change']) {
        window.addEventListener(type, blockWhilePending, true);
    }
    window.addEventListener('keydown', event => {
        if (['Enter', ' ', 'Escape'].includes(event.key)) blockWhilePending(event);
    }, true);

    // Observe native navigation after page handlers have had a chance to cancel it.
    window.addEventListener('click', event => {
        if (event.defaultPrevented || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const link = event.target.closest?.('a[href]');
        if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
        const url = new URL(link.href, location.href);
        if (url.hash && url.pathname === location.pathname && url.search === location.search) return;
        if ((url.protocol === 'http:' || url.protocol === 'https:') && isPageNavigation(url)) startNavigation();
    });
    window.addEventListener('submit', event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        const submitter = event.submitter;
        const method = submitter?.getAttribute('formmethod') || form.method;
        const target = submitter?.getAttribute('formtarget') || form.target;
        if (method.toLowerCase() === 'dialog' || (target && target !== '_self')) return;
        const url = new URL(submitter?.getAttribute('formaction') || form.action, location.href);
        if (isPageNavigation(url)) startNavigation();
    });

    function reset() {
        navigation?.();
        for (const finish of pending) finish();
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        overlay.classList.remove('is-visible', 'is-leaving');
        hide();
    }
    window.addEventListener('pagehide', reset);
    window.addEventListener('pageshow', event => { if (event.persisted) reset(); });
    window.addEventListener('popstate', () => navigation?.());
    window.navigation?.addEventListener('navigateerror', () => navigation?.());

    window.BookingLoading = {begin, run, navigate, loadFrame, isBusy: () => pending.size > 0};
})();
