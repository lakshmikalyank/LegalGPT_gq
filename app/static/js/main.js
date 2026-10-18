/**
 * main.js
 * Shared JavaScript loaded on every page: sidebar toggle and
 * auto-dismissing flash alerts.
 */

document.addEventListener("DOMContentLoaded", () => {
    initSidebarToggle();
    initAutoDismissAlerts();
});

// ==========================================================================
// CSRF Protection — global fetch wrapper
// ==========================================================================
// Patches window.fetch once, at load time, so every existing fetch() call
// across the app (chat.js, analyze.js, summary.js, generate.js, uploads.js,
// search.js, admin.js) automatically sends the CSRF token on state-changing
// requests without any of those files needing to be modified individually.
// GET/HEAD requests are left untouched since CSRFProtect only checks
// state-changing methods by default.
(function patchFetchForCsrf() {
    const originalFetch = window.fetch;

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : null;
    }

    window.fetch = function (input, init) {
        const options = init || {};
        const method = (options.method || "GET").toUpperCase();

        if (method !== "GET" && method !== "HEAD") {
            const token = getCsrfToken();
            if (token) {
                const headers = new Headers(options.headers || {});
                if (!headers.has("X-CSRFToken")) {
                    headers.set("X-CSRFToken", token);
                }
                options.headers = headers;
            }
        }

        return originalFetch(input, options);
    };
})();

/**
 * Toggles the sidebar between expanded and collapsed states.
 *
 * Fix: previously this function was called from TWO separate
 * DOMContentLoaded listeners in this file, which attached the click
 * handler to the toggle button twice. That meant every single click
 * fired classList.toggle("collapsed") twice in a row — toggling it on,
 * then immediately back off — so the sidebar appeared to do nothing at
 * all when clicked. This file now has exactly one DOMContentLoaded
 * listener (above) that calls this function exactly once.
 */
/**
 * Toggles the sidebar between expanded and collapsed states.
 *
 * On desktop, "collapsed" shrinks the sidebar to an icon-only rail.
 * On mobile (see the @media rule in style.css), "collapsed" instead
 * slides the sidebar in as a full-width overlay drawer, since an
 * icon-only rail toggling between the same 76px width on and off
 * had no visible effect - that was the mobile hamburger bug.
 * The backdrop only matters on mobile; toggling it is harmless
 * on desktop since it's hidden by CSS there.
 */
function initSidebarToggle() {
    const toggleBtn = document.getElementById("sidebarToggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebarBackdrop");

    if (!toggleBtn || !sidebar) return;

    function closeSidebar() {
        sidebar.classList.remove("collapsed");
        if (backdrop) backdrop.classList.remove("active");
    }

    function toggleSidebar() {
        const isOpen = sidebar.classList.toggle("collapsed");
        if (backdrop) backdrop.classList.toggle("active", isOpen);
    }

    toggleBtn.addEventListener("click", toggleSidebar);

    if (backdrop) {
        backdrop.addEventListener("click", closeSidebar);
    }

    // On mobile, tapping a nav link should close the drawer instead of
    // leaving it open over the page you just navigated to.
    sidebar.querySelectorAll(".sidebar-nav a, .logout-link").forEach((link) => {
        link.addEventListener("click", () => {
            if (window.innerWidth <= 900) closeSidebar();
        });
    });
}

/**
 * Automatically dismisses Bootstrap flash alerts after a few seconds.
 */
function initAutoDismissAlerts() {
    const alerts = document.querySelectorAll(".alert");
    alerts.forEach((alert) => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
}

/**
 * Small helper for other scripts: shows a temporary toast-style
 * message at the top of the content body.
 *
 * @param {string} message - Text to display.
 * @param {string} category - Bootstrap alert category (success, danger, info, warning).
 */
function showFlashMessage(message, category = "info") {
    const container = document.querySelector(".content-body") || document.body;

    const alertDiv = document.createElement("div");
    alertDiv.className = `alert alert-${category} alert-dismissible fade show`;
    alertDiv.role = "alert";
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    container.prepend(alertDiv);

    setTimeout(() => {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(alertDiv);
        bsAlert.close();
    }, 5000);
}
