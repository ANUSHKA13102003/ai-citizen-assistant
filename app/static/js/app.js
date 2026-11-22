/* Shared UI & accessibility helpers for AI Citizen Assistant */
(function () {
  function getCsrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  window.showToast = function (msg, duration) {
    var el = document.getElementById("appToast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(function () {
      el.classList.remove("show");
    }, duration || 3500);
  };

  window.apiFetch = async function (url, options) {
    var opts = Object.assign({}, options || {});
    opts.headers = Object.assign({}, opts.headers || {});
    if (!(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = opts.headers["Content-Type"] || "application/json";
    }
    opts.headers["X-CSRFToken"] = getCsrf();
    var wakeTimer = setTimeout(function () {
      window.showToast(
        window.APP_LANG === "hi"
          ? "सर्वर शुरू हो रहा है, कृपया कुछ सेकंड प्रतीक्षा करें..."
          : "Waking up the server, please wait a moment...",
        5000
      );
    }, 4500);
    try {
      return await fetch(url, opts);
    } finally {
      clearTimeout(wakeTimer);
    }
  };

  window.openPageViewer = async function (filename, page, highlight) {
    var modal = document.getElementById("pageViewerModal");
    var title = document.getElementById("pageViewerTitle");
    var body = document.getElementById("pageViewerText");
    if (!modal || !title || !body) return;
    title.textContent = filename + " — Page " + (page || 1);
    body.textContent = "Loading...";
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    try {
      var res = await fetch("/api/document-page?filename=" + encodeURIComponent(filename) + "&page=" + (page || 1));
      var data = await res.json();
      if (!res.ok) {
        body.textContent = data.error || "Could not load page.";
        return;
      }
      var text = data.text || "";
      if (highlight && text.toLowerCase().includes(String(highlight).toLowerCase())) {
        var idx = text.toLowerCase().indexOf(String(highlight).toLowerCase());
        body.textContent = "";
        body.appendChild(document.createTextNode(text.slice(0, idx)));
        var mark = document.createElement("mark");
        mark.textContent = text.slice(idx, idx + String(highlight).length);
        body.appendChild(mark);
        body.appendChild(document.createTextNode(text.slice(idx + String(highlight).length)));
      } else {
        body.textContent = text;
      }
    } catch (_err) {
      body.textContent = "Could not load page.";
    }
  };

  document.addEventListener("DOMContentLoaded", function () {
    var langBtn = document.getElementById("langToggleBtn");
    if (langBtn) {
      langBtn.addEventListener("click", async function () {
        var nextLang = langBtn.getAttribute("data-next-lang") || "hi";
        await window.apiFetch("/api/language", {
          method: "POST",
          body: JSON.stringify({ lang: nextLang })
        });
        window.location.reload();
      });
    }

    var themeBtn = document.getElementById("themeToggleBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var cur = document.documentElement.getAttribute("data-theme") || "light";
        var next = cur === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("citizen_theme", next);
      });
    }

    var contrastBtn = document.getElementById("contrastToggleBtn");
    if (contrastBtn) {
      contrastBtn.addEventListener("click", function () {
        var cur = document.documentElement.getAttribute("data-contrast") || "normal";
        var next = cur === "high" ? "normal" : "high";
        document.documentElement.setAttribute("data-contrast", next);
        localStorage.setItem("citizen_contrast", next);
      });
    }

    var currentScale = document.documentElement.getAttribute("data-scale") || "md";
    document.querySelectorAll(".scale-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-scale") === currentScale);
      btn.addEventListener("click", function () {
        var sc = btn.getAttribute("data-scale") || "md";
        document.documentElement.setAttribute("data-scale", sc);
        localStorage.setItem("citizen_scale", sc);
        document.querySelectorAll(".scale-btn").forEach(function (b) {
          b.classList.toggle("active", b.getAttribute("data-scale") === sc);
        });
      });
    });

    var clearBtn = document.getElementById("footerClearDataBtn");
    if (clearBtn) {
      clearBtn.addEventListener("click", async function () {
        await window.apiFetch("/api/session/clear", { method: "POST", body: JSON.stringify({}) });
        window.showToast((window.APP_I18N && window.APP_I18N.privacy && window.APP_I18N.privacy.cleared_msg) || "Your data has been cleared.");
        setTimeout(function () { window.location.reload(); }, 700);
      });
    }

    var closeModal = document.getElementById("closePageViewerBtn");
    var modal = document.getElementById("pageViewerModal");
    if (closeModal && modal) {
      closeModal.addEventListener("click", function () {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
      });
      modal.addEventListener("click", function (e) {
        if (e.target === modal) {
          modal.classList.remove("open");
          modal.setAttribute("aria-hidden", "true");
        }
      });
    }
  });
})();
