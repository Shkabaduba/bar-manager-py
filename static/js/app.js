(function () {
  "use strict";

  var activeRequests = 0;

  function activateAsyncStyles() {
    var links = document.querySelectorAll("link[data-async-style]");
    links.forEach(function (linkEl) {
      if (linkEl.sheet) {
        linkEl.media = "all";
        return;
      }
      linkEl.addEventListener("load", function () {
        linkEl.media = "all";
      });
      window.setTimeout(function () {
        if (linkEl.media !== "all") {
          linkEl.media = "all";
        }
      }, 100);
    });
  }

  activateAsyncStyles();

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

  function syncOverlayLock() {
    var drawerPanel = document.getElementById("drawer-panel");
    var sidebarWrap = document.getElementById("app-sidebar-wrap");
    var hasOpenOverlay = Boolean(
      (drawerPanel && drawerPanel.classList.contains("is-open")) ||
        (sidebarWrap && sidebarWrap.classList.contains("is-open"))
    );
    document.body.classList.toggle("is-overlay-open", hasOpenOverlay);
  }

  function openDrawer() {
    var els = getDrawerElements();
    if (!els.panel || !els.backdrop) {
      return;
    }
    els.backdrop.classList.add("is-open");
    els.panel.classList.add("is-open");
    els.panel.setAttribute("aria-hidden", "false");
    syncOverlayLock();
  }

  function closeDrawer() {
    var els = getDrawerElements();
    if (!els.panel || !els.backdrop) {
      return;
    }
    els.backdrop.classList.remove("is-open");
    els.panel.classList.remove("is-open");
    els.panel.setAttribute("aria-hidden", "true");
    syncOverlayLock();
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
    syncOverlayLock();
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
    syncOverlayLock();
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
      var duration = 560;
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

  function focusSearchOrNavigate(triggerEl) {
    var searchInput = document.querySelector(
      '[data-search-input], input[name="name"], input[name="username"]'
    );
    if (searchInput) {
      searchInput.focus();
      if (typeof searchInput.scrollIntoView === "function") {
        searchInput.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
      }
      return;
    }
    var fallbackUrl = triggerEl && triggerEl.getAttribute("data-search-fallback");
    if (fallbackUrl) {
      window.location.assign(fallbackUrl);
    } else {
      openSidebar();
    }
  }

  function initKineticCursor() {
    if (reducedMotion || typeof window.requestAnimationFrame !== "function") {
      return;
    }
    var finePointer = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    var cursor = document.getElementById("kinetic-cursor");
    if (!finePointer || !cursor) {
      return;
    }

    var targetX = -100;
    var targetY = -100;
    var curX = -100;
    var curY = -100;
    var activeMagnet = null;
    var rafId = null;

    function step() {
      curX += (targetX - curX) * 0.22;
      curY += (targetY - curY) * 0.22;
      cursor.style.transform =
        "translate3d(" + curX.toFixed(1) + "px, " + curY.toFixed(1) + "px, 0) translate(-50%, -50%)";
      if (Math.abs(targetX - curX) > 0.2 || Math.abs(targetY - curY) > 0.2) {
        rafId = window.requestAnimationFrame(step);
      } else {
        rafId = null;
      }
    }

    document.addEventListener("mousemove", function (evt) {
      targetX = evt.clientX;
      targetY = evt.clientY;
      cursor.classList.add("is-visible");

      var interactive = evt.target.closest(
        "a, button, .bento-card, .drink-card, .action-tile, input, select, textarea"
      );
      cursor.classList.toggle("is-hover", Boolean(interactive));

      var magnet = evt.target.closest("[data-magnetic]");
      if (activeMagnet && activeMagnet !== magnet) {
        activeMagnet.style.transform = "";
        activeMagnet = null;
      }
      if (magnet) {
        var rect = magnet.getBoundingClientRect();
        var dx = ((evt.clientX - (rect.left + rect.width / 2)) / (rect.width / 2 || 1)) * 4;
        var dy = ((evt.clientY - (rect.top + rect.height / 2)) / (rect.height / 2 || 1)) * 4;
        magnet.style.transform = "translate3d(" + dx.toFixed(2) + "px, " + dy.toFixed(2) + "px, 0)";
        activeMagnet = magnet;
      }

      if (!rafId) {
        rafId = window.requestAnimationFrame(step);
      }
    });

    document.addEventListener("mouseleave", function () {
      cursor.classList.remove("is-visible");
      if (activeMagnet) {
        activeMagnet.style.transform = "";
        activeMagnet = null;
      }
    });
  }

  function initKineticFieldCanvas() {
    var canvas = document.querySelector("[data-kinetic-canvas]");
    if (!canvas || !canvas.getContext) {
      return;
    }
    var ctx = canvas.getContext("2d");
    var width = 0;
    var height = 0;
    var dpr = 1;
    var mouseX = -9999;
    var mouseY = -9999;
    var scrollVel = 0;
    var lastScrollY = window.scrollY || 0;
    var rafId = null;
    var t = 0;

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reducedMotion) {
        drawFrame();
      }
    }

    function drawFrame() {
      ctx.clearRect(0, 0, width, height);
      var spacing = 68;
      var cols = Math.ceil(width / spacing) + 1;
      var rows = Math.ceil(height / spacing) + 1;
      ctx.lineWidth = 1;

      for (var r = 0; r < rows; r++) {
        var py = r * spacing;
        for (var c = 0; c < cols; c++) {
          var px = c * spacing;
          var dx = mouseX - px;
          var dy = mouseY - py;
          var dist = Math.sqrt(dx * dx + dy * dy);
          var influence = mouseX > -5000 ? Math.max(0, 1 - dist / 280) : 0;
          var baseAngle = Math.sin(c * 0.25 + r * 0.18 + t) * 0.32 + scrollVel * 0.04;
          var targetAngle = influence > 0 ? Math.atan2(dy, dx) : baseAngle;
          var angle = baseAngle + (targetAngle - baseAngle) * influence;
          var halfLen = 5 + influence * 7 + Math.min(Math.abs(scrollVel) * 0.35, 5);
          var alpha = 0.08 + influence * 0.22;

          ctx.strokeStyle = "rgba(244, 242, 236, " + alpha.toFixed(3) + ")";
          ctx.beginPath();
          ctx.moveTo(px - Math.cos(angle) * halfLen, py - Math.sin(angle) * halfLen);
          ctx.lineTo(px + Math.cos(angle) * halfLen, py + Math.sin(angle) * halfLen);
          ctx.stroke();
        }
      }
    }

    function loop() {
      if (document.hidden || reducedMotion) {
        rafId = null;
        return;
      }
      t += 0.012;
      scrollVel *= 0.9;
      drawFrame();
      rafId = window.requestAnimationFrame(loop);
    }

    resize();
    window.addEventListener("resize", resize);

    if (!reducedMotion) {
      window.addEventListener(
        "mousemove",
        function (evt) {
          mouseX = evt.clientX;
          mouseY = evt.clientY;
        },
        { passive: true }
      );
      window.addEventListener(
        "scroll",
        function () {
          var currentY = window.scrollY || 0;
          scrollVel = Math.max(-24, Math.min(24, currentY - lastScrollY));
          lastScrollY = currentY;
        },
        { passive: true }
      );
      document.addEventListener("visibilitychange", function () {
        if (!document.hidden && !rafId) {
          rafId = window.requestAnimationFrame(loop);
        }
      });
      rafId = window.requestAnimationFrame(loop);
    }
  }

  function initLoginKineticPortal() {
    var canvas = document.querySelector("[data-login-canvas]");
    if (!canvas || !canvas.getContext) {
      return;
    }
    var ctx = canvas.getContext("2d");
    var stage = canvas.closest(".auth-kinetic-stage");
    var telemetryEl = document.querySelector("[data-login-telemetry]");
    var usernameInput = document.getElementById("id_username");
    var passwordInput = document.getElementById("id_password");
    var loginForm = document.querySelector("[data-login-form]");

    var width = 0;
    var height = 0;
    var dpr = 1;
    var targetTiltX = 0.35;
    var targetTiltY = -0.25;
    var tiltX = 0.35;
    var tiltY = -0.25;
    var spin = 0;
    var impulse = 0;
    var targetAperture = 1;
    var aperture = 1;
    var warpMode = false;
    var rafId = null;

    function updateTelemetry(statusLabel) {
      if (!telemetryEl) {
        return;
      }
      var spans = telemetryEl.querySelectorAll("span");
      if (spans.length >= 2) {
        spans[0].textContent =
          "AXIS " + tiltX.toFixed(2) + " / " + tiltY.toFixed(2);
        spans[1].textContent = statusLabel;
      }
    }

    function resize() {
      if (!stage) {
        return;
      }
      var rect = stage.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(240, rect.width);
      height = Math.max(240, rect.height);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reducedMotion) {
        drawOrbital();
      }
    }

    function projectPoint(x, y, z, rx, ry, fov) {
      var cosY = Math.cos(ry);
      var sinY = Math.sin(ry);
      var x1 = x * cosY - z * sinY;
      var z1 = z * cosY + x * sinY;

      var cosX = Math.cos(rx);
      var sinX = Math.sin(rx);
      var y2 = y * cosX - z1 * sinX;
      var z2 = z1 * cosX + y * sinX;

      var scale = fov / (fov + z2 + 240);
      return {
        x: width * 0.5 + x1 * scale,
        y: height * 0.52 + y2 * scale,
        scale: scale,
      };
    }

    function drawRing(radius, segments, rx, ry, alpha, dashed) {
      ctx.save();
      ctx.strokeStyle = "rgba(244, 242, 236, " + alpha.toFixed(3) + ")";
      ctx.lineWidth = 1.15;
      if (dashed) {
        ctx.setLineDash([4, 6]);
      }
      ctx.beginPath();
      for (var i = 0; i <= segments; i++) {
        var theta = (i / segments) * Math.PI * 2;
        var pt = projectPoint(
          Math.cos(theta) * radius,
          Math.sin(theta) * radius,
          0,
          rx,
          ry,
          460
        );
        if (i === 0) {
          ctx.moveTo(pt.x, pt.y);
        } else {
          ctx.lineTo(pt.x, pt.y);
        }
      }
      ctx.stroke();
      ctx.restore();
    }

    function drawOrbital() {
      ctx.clearRect(0, 0, width, height);
      var baseR = Math.min(width, height) * 0.34 * aperture;
      var r1 = baseR;
      var r2 = baseR * 0.78;
      var r3 = baseR * 0.54;

      // Crosshair axes
      ctx.strokeStyle = "rgba(244, 242, 236, 0.08)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(width * 0.5, 16);
      ctx.lineTo(width * 0.5, height - 16);
      ctx.moveTo(16, height * 0.52);
      ctx.lineTo(width - 16, height * 0.52);
      ctx.stroke();

      drawRing(r1, 72, tiltX + spin * 0.35, tiltY + spin * 0.5, 0.45, false);
      drawRing(r2, 64, -tiltX * 0.8 - spin * 0.55, tiltY * 1.1 + 0.8, 0.3, true);
      drawRing(r3, 56, tiltX * 1.2 + 0.9, -tiltY + spin * 0.85, 0.65, false);

      // Orbiting telemetry nodes
      for (var k = 0; k < 6; k++) {
        var angle = spin * 1.1 + (k * Math.PI) / 3;
        var node = projectPoint(
          Math.cos(angle) * r1,
          Math.sin(angle) * r1,
          0,
          tiltX + spin * 0.35,
          tiltY + spin * 0.5,
          460
        );
        ctx.fillStyle = k % 2 === 0 ? "#f4f2ec" : "rgba(244, 242, 236, 0.45)";
        ctx.beginPath();
        ctx.arc(node.x, node.y, k % 2 === 0 ? 3 : 2, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function tick() {
      if (document.hidden || reducedMotion) {
        rafId = null;
        return;
      }
      tiltX += (targetTiltX - tiltX) * 0.08;
      tiltY += (targetTiltY - tiltY) * 0.08;
      aperture += (targetAperture - aperture) * 0.1;
      var speed = warpMode ? 0.085 : 0.008 + impulse * 0.035;
      spin += speed;
      impulse *= 0.92;

      drawOrbital();
      rafId = window.requestAnimationFrame(tick);
    }

    resize();
    window.addEventListener("resize", resize);

    if (!reducedMotion) {
      window.addEventListener(
        "mousemove",
        function (evt) {
          var nx = (evt.clientX / (window.innerWidth || 1) - 0.5) * 1.1;
          var ny = (evt.clientY / (window.innerHeight || 1) - 0.5) * 1.1;
          targetTiltY = nx;
          targetTiltX = -ny;
          updateTelemetry(targetAperture < 0.9 ? "VAULT APERTURE // LOCKED" : "ORBITAL SYNC // LIVE");
        },
        { passive: true }
      );

      [usernameInput, passwordInput].forEach(function (inputEl) {
        if (!inputEl) {
          return;
        }
        inputEl.addEventListener("input", function () {
          impulse = Math.min(impulse + 0.35, 2.2);
          updateTelemetry("KEYSTROKE PULSE // VERIFYING");
        });
      });

      if (passwordInput) {
        passwordInput.addEventListener("focus", function () {
          targetAperture = 0.72;
          updateTelemetry("VAULT APERTURE // LOCKED");
        });
        passwordInput.addEventListener("blur", function () {
          targetAperture = 1;
          updateTelemetry("ORBITAL SYNC // READY");
        });
      }

      if (loginForm) {
        loginForm.addEventListener("submit", function () {
          warpMode = true;
          targetAperture = 0.58;
          updateTelemetry("SHIFT AUTH // ENGAGED");
        });
      }

      document.addEventListener("visibilitychange", function () {
        if (!document.hidden && !rafId) {
          rafId = window.requestAnimationFrame(tick);
        }
      });
      rafId = window.requestAnimationFrame(tick);
    }
  }

  function initVelocityMarquee() {
    if (reducedMotion) {
      return;
    }
    var tracks = document.querySelectorAll("[data-marquee] .marquee-track");
    if (!tracks.length) {
      return;
    }
    var lastY = window.scrollY || 0;
    var boost = 0;

    function decay() {
      boost *= 0.9;
      tracks.forEach(function (track) {
        if (typeof track.getAnimations === "function") {
          track.getAnimations().forEach(function (anim) {
            anim.playbackRate = 1 + boost;
          });
        }
      });
      if (boost > 0.02) {
        window.requestAnimationFrame(decay);
      }
    }

    window.addEventListener(
      "scroll",
      function () {
        var currentY = window.scrollY || 0;
        var delta = Math.abs(currentY - lastY);
        lastY = currentY;
        var prevBoost = boost;
        boost = Math.min(3.2, Math.max(boost, delta * 0.07));
        if (prevBoost <= 0.02 && boost > 0.02) {
          window.requestAnimationFrame(decay);
        }
      },
      { passive: true }
    );
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
    if (evt.target.closest("#app-sidebar-wrap .nav-link")) {
      closeSidebar();
    }
    var searchTrigger = evt.target.closest("[data-search-trigger]");
    if (searchTrigger) {
      evt.preventDefault();
      focusSearchOrNavigate(searchTrigger);
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

  // Initialize Kinetic Systems, Clock & Flash Alerts
  window.addEventListener("DOMContentLoaded", function () {
    animateCountUp(document);
    initLiveClock();
    initKineticCursor();
    initKineticFieldCanvas();
    initLoginKineticPortal();
    initVelocityMarquee();
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
