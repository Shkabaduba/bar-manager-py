(function () {
  "use strict";

  var activeRequests = 0;

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.getAttribute("content")) {
      return meta.getAttribute("content");
    }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function getDrawerElements() {
    return {
      backdrop: document.getElementById("drawer-backdrop"),
      panel: document.getElementById("drawer-panel"),
      body: document.getElementById("drawer-body"),
    };
  }

  function openDrawer() {
    var els = getDrawerElements();
    if (!els.panel || !els.backdrop) {
      return;
    }
    els.backdrop.classList.add("is-open");
    els.panel.classList.add("is-open");
    els.panel.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    var els = getDrawerElements();
    if (!els.panel || !els.backdrop) {
      return;
    }
    els.backdrop.classList.remove("is-open");
    els.panel.classList.remove("is-open");
    els.panel.setAttribute("aria-hidden", "true");
  }

  function openSidebar() {
    var wrap = document.getElementById("app-sidebar-wrap");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (wrap) {
      wrap.classList.add("is-open");
    }
    if (backdrop) {
      backdrop.classList.add("is-open");
    }
  }

  function closeSidebar() {
    var wrap = document.getElementById("app-sidebar-wrap");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (wrap) {
      wrap.classList.remove("is-open");
    }
    if (backdrop) {
      backdrop.classList.remove("is-open");
    }
  }

  function showToast(level, message) {
    if (!message) {
      return;
    }
    var stack = document.getElementById("toast-stack");
    if (!stack) {
      return;
    }
    var safeLevel = ["success", "warning", "error", "info"].indexOf(level) !== -1
      ? level
      : "info";

    var item = document.createElement("div");
    item.className = "toast-item toast-" + safeLevel;
    item.setAttribute("role", "status");

    var textSpan = document.createElement("span");
    textSpan.textContent = String(message);

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "toast-close";
    closeBtn.textContent = "\u00d7";
    closeBtn.setAttribute("aria-label", "Dismiss");
    closeBtn.addEventListener("click", function () {
      item.remove();
    });

    item.appendChild(textSpan);
    item.appendChild(closeBtn);
    stack.appendChild(item);

    window.setTimeout(function () {
      if (item.parentNode) {
        item.remove();
      }
    }, 4500);
  }

  function updateProgressBar(delta) {
    activeRequests = Math.max(0, activeRequests + delta);
    var bar = document.getElementById("htmx-progress-bar");
    if (!bar) {
      return;
    }
    if (activeRequests > 0) {
      bar.classList.add("is-loading");
    } else {
      bar.classList.remove("is-loading");
    }
  }

  function notifyRecipeLiveInputs() {
    var container = document.getElementById("recipe-live-inputs");
    if (container) {
      container.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function addRecipeRow() {
    var rowsContainer = document.getElementById("recipe-rows");
    var template = document.getElementById("empty-recipe-row-template");
    var totalInput = document.getElementById("id_recipe_items-TOTAL_FORMS");
    if (!rowsContainer || !template || !totalInput) {
      return;
    }
    var index = parseInt(totalInput.value || "0", 10);
    var rowHtml = template.innerHTML.replace(/__prefix__/g, String(index));
    var wrapper = document.createElement("div");
    wrapper.innerHTML = rowHtml.trim();
    var newRow = wrapper.firstElementChild;
    if (!newRow) {
      return;
    }
    newRow.setAttribute("data-recipe-row", "dynamic");
    rowsContainer.appendChild(newRow);
    totalInput.value = String(index + 1);
    if (window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(newRow);
    }
    notifyRecipeLiveInputs();
  }

  function removeRecipeRow(button) {
    var row = button.closest("[data-recipe-row], .recipe-row");
    if (!row) {
      return;
    }
    var deleteCheckbox = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (deleteCheckbox) {
      deleteCheckbox.checked = true;
      row.style.display = "none";
    } else {
      row.remove();
    }
    notifyRecipeLiveInputs();
  }

  var reducedMotion = Boolean(
    window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );

  function animateCountUp(root) {
    if (reducedMotion || typeof window.requestAnimationFrame !== "function") {
      return;
    }
    var scope = root && root.querySelectorAll ? root : document;
    var targets = scope.querySelectorAll("[data-count-up]");
    targets.forEach(function (el) {
      if (el.dataset.counted === "1") {
        return;
      }
      var raw = (el.textContent || "").trim();
      var match = raw.match(/^([^0-9-]*)(-?\d+(?:[.,]\d+)?)(.*)$/);
      if (!match) {
        return;
      }
      var prefix = match[1];
      var numText = match[2];
      var suffix = match[3];
      var sep = numText.indexOf(",") !== -1 ? "," : ".";
      var normalized = numText.replace(",", ".");
      var targetVal = parseFloat(normalized);
      if (!isFinite(targetVal) || targetVal === 0) {
        el.dataset.counted = "1";
        return;
      }
      var decimals = normalized.indexOf(".") !== -1
        ? normalized.split(".")[1].length
        : 0;
      el.dataset.counted = "1";
      var duration = 600;
      var startTime = null;

      function tick(ts) {
        if (startTime === null) {
          startTime = ts;
        }
        var progress = Math.min((ts - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        var current = targetVal * eased;
        var formatted = decimals > 0
          ? current.toFixed(decimals).replace(".", sep)
          : String(Math.round(current));
        el.textContent = prefix + formatted + suffix;
        if (progress < 1) {
          window.requestAnimationFrame(tick);
        } else {
          el.textContent = raw;
        }
      }

      window.requestAnimationFrame(tick);
    });
  }

  function initLiveClock() {
    function updateClock() {
      var clocks = document.querySelectorAll("[data-live-clock]");
      if (!clocks.length) {
        return;
      }
      var now = new Date();
      var hh = String(now.getHours()).padStart(2, "0");
      var mm = String(now.getMinutes()).padStart(2, "0");
      var ss = String(now.getSeconds()).padStart(2, "0");
      var formatted = hh + ":" + mm + ":" + ss;
      clocks.forEach(function (node) {
        node.textContent = formatted;
      });
    }

    updateClock();
    window.setInterval(updateClock, 1000);
  }

  // HTMX CSRF Header & Status Handling
  document.addEventListener("htmx:configRequest", function (evt) {
    var verb = (evt.detail.verb || "get").toUpperCase();
    if (verb !== "GET" && verb !== "HEAD" && verb !== "OPTIONS") {
      var token = getCsrfToken();
      if (token) {
        evt.detail.headers["X-CSRFToken"] = token;
      }
    }
  });

  document.addEventListener("htmx:beforeRequest", function () {
    updateProgressBar(1);
  });

  document.addEventListener("htmx:afterRequest", function () {
    updateProgressBar(-1);
  });

  document.addEventListener("htmx:responseError", function () {
    updateProgressBar(-1);
  });

  document.addEventListener("htmx:sendError", function () {
    updateProgressBar(-1);
  });

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var xhr = evt.detail.xhr;
    if (!xhr) {
      return;
    }
    var status = xhr.status;
    var hasRetarget = Boolean(xhr.getResponseHeader("HX-Retarget"));
    var isDrawerTarget = evt.detail.target && evt.detail.target.id === "drawer-body";
    if ((status === 400 || status === 409 || status === 422) && (hasRetarget || isDrawerTarget)) {
      evt.detail.shouldSwap = true;
      evt.detail.isError = false;
    }
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.detail.target && evt.detail.target.id === "drawer-body") {
      openDrawer();
    }
  });

  document.addEventListener("htmx:afterSettle", function (evt) {
    animateCountUp(evt.detail.target || document);
  });

  // HX-Trigger Custom Events
  document.body.addEventListener("showToast", function (evt) {
    var detail = evt.detail || {};
    showToast(detail.level || "info", detail.message || "");
  });

  document.body.addEventListener("closeDrawer", function () {
    closeDrawer();
  });

  // Delegated UI Clicks
  document.addEventListener("click", function (evt) {
    if (evt.target.closest("[data-drawer-close]") || evt.target.id === "drawer-backdrop") {
      closeDrawer();
      return;
    }
    if (evt.target.closest("[data-sidebar-toggle]")) {
      openSidebar();
      return;
    }
    if (evt.target.closest("[data-sidebar-close]") || evt.target.id === "sidebar-backdrop") {
      closeSidebar();
      return;
    }
    var addBtn = evt.target.closest("[data-add-recipe-row]");
    if (addBtn) {
      evt.preventDefault();
      addRecipeRow();
      return;
    }
    var removeBtn = evt.target.closest("[data-remove-recipe-row]");
    if (removeBtn) {
      evt.preventDefault();
      removeRecipeRow(removeBtn);
    }
  });

  // Cyberpunk Card Cursor Spotlight
  if (!reducedMotion) {
    document.addEventListener("mousemove", function (evt) {
      var card = evt.target.closest(".bento-card, .drink-card, .cyber-hero");
      if (!card) {
        return;
      }
      var rect = card.getBoundingClientRect();
      card.style.setProperty("--mouse-x", evt.clientX - rect.left + "px");
      card.style.setProperty("--mouse-y", evt.clientY - rect.top + "px");
    });
  }

  // Global Hotkeys: '/' to focus search, 'Escape' to close overlays
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape") {
      closeDrawer();
      closeSidebar();
      return;
    }
    if (evt.key === "/" && !evt.ctrlKey && !evt.metaKey && !evt.altKey) {
      var activeTag = document.activeElement ? document.activeElement.tagName : "";
      if (activeTag === "INPUT" || activeTag === "TEXTAREA" || activeTag === "SELECT") {
        return;
      }
      var searchInput = document.querySelector(
        '[data-search-input], input[name="name"], input[name="username"]'
      );
      if (searchInput) {
        evt.preventDefault();
        searchInput.focus();
      }
    }
  });

  // Auto-dismiss Server Flash Messages, Count-Up KPIs & Live Shift Clock
  window.addEventListener("DOMContentLoaded", function () {
    animateCountUp(document);
    initLiveClock();
    var alerts = document.querySelectorAll("[data-auto-dismiss]");
    alerts.forEach(function (alertEl) {
      window.setTimeout(function () {
        if (alertEl.parentNode) {
          alertEl.remove();
        }
      }, 5000);
    });
  });
})();
