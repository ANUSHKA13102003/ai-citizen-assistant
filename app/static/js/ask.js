/* Ask Sahayak full-height chat controller */
(function () {
  var i18n = window.APP_I18N || {};
  var aText = i18n.ask || {};
  var activeAbort = null;

  function simpleMarkdown(text) {
    var esc = String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    esc = esc.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    esc = esc.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    esc = esc.replace(/(^|\n)[*-]\s+/g, "$1• ");
    esc = esc.replace(/\n/g, "<br>");
    return esc;
  }

  function appendUserMessage(text) {
    var starters = document.getElementById("starterCardsGrid");
    if (starters) starters.style.display = "none";
    var box = document.getElementById("chatMessages");
    var div = document.createElement("div");
    div.className = "msg msg-user";
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function createBotMessage() {
    var box = document.getElementById("chatMessages");
    var div = document.createElement("div");
    div.className = "msg msg-bot";
    var content = document.createElement("div");
    content.className = "bot-body";
    content.textContent = window.APP_LANG === "hi" ? "सोच रहे हैं..." : "Thinking...";
    var citationsWrap = document.createElement("details");
    citationsWrap.style.display = "none";
    citationsWrap.style.marginTop = "8px";
    var citeSum = document.createElement("summary");
    citeSum.style.fontSize = "0.86rem";
    citeSum.style.cursor = "pointer";
    citeSum.textContent = window.APP_LANG === "hi" ? "स्रोत देखें" : "Sources";
    var citations = document.createElement("div");
    citations.className = "msg-actions";
    citationsWrap.appendChild(citeSum);
    citationsWrap.appendChild(citations);

    var actions = document.createElement("div");
    actions.className = "msg-actions";
    div.appendChild(content);
    div.appendChild(citationsWrap);
    div.appendChild(actions);
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return { div: div, content: content, citationsWrap: citationsWrap, citations: citations, actions: actions };
  }

  function addActionButtons(ui, fullText, queryLogId, questionText) {
    ui.actions.innerHTML = "";
    var copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn btn-secondary btn-sm";
    copyBtn.textContent = aText.copy || "Copy";
    copyBtn.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(fullText);
      copyBtn.textContent = aText.copied || "Copied";
    });

    var waLink = document.createElement("a");
    waLink.className = "btn btn-secondary btn-sm";
    waLink.href = "https://wa.me/?text=" + encodeURIComponent(fullText);
    waLink.target = "_blank";
    waLink.rel = "noopener noreferrer";
    waLink.textContent = aText.whatsapp || "WhatsApp";

    var regenBtn = document.createElement("button");
    regenBtn.type = "button";
    regenBtn.className = "btn btn-secondary btn-sm";
    regenBtn.textContent = aText.regen || "Try again";
    regenBtn.addEventListener("click", function () { sendQuestion(questionText); });

    ui.actions.appendChild(copyBtn);
    ui.actions.appendChild(waLink);
    ui.actions.appendChild(regenBtn);

    if ("speechSynthesis" in window) {
      var speakBtn = document.createElement("button");
      speakBtn.type = "button";
      speakBtn.className = "btn btn-secondary btn-sm";
      speakBtn.textContent = aText.read_aloud || "Listen";
      speakBtn.addEventListener("click", function () {
        if (window.speechSynthesis.speaking) {
          window.speechSynthesis.cancel();
          speakBtn.textContent = aText.read_aloud || "Listen";
          return;
        }
        var utt = new SpeechSynthesisUtterance(fullText);
        utt.lang = (window.APP_LANG === "hi") ? "hi-IN" : "en-IN";
        utt.onend = function () { speakBtn.textContent = aText.read_aloud || "Listen"; };
        speakBtn.textContent = aText.stop_reading || "Stop";
        window.speechSynthesis.speak(utt);
      });
      ui.actions.appendChild(speakBtn);
    }

    var upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "btn btn-secondary btn-sm";
    upBtn.textContent = "👍";
    upBtn.setAttribute("aria-label", aText.helpful || "Helpful");
    upBtn.addEventListener("click", function () {
      window.apiFetch("/api/feedback", {
        method: "POST",
        body: JSON.stringify({ rating: 1, query_log_id: queryLogId || null })
      });
      upBtn.disabled = true;
    });

    var downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "btn btn-secondary btn-sm";
    downBtn.textContent = "👎";
    downBtn.setAttribute("aria-label", aText.not_helpful || "Not helpful");
    downBtn.addEventListener("click", function () {
      window.apiFetch("/api/feedback", {
        method: "POST",
        body: JSON.stringify({ rating: -1, query_log_id: queryLogId || null })
      });
      downBtn.disabled = true;
    });

    ui.actions.appendChild(upBtn);
    ui.actions.appendChild(downBtn);
  }

  function renderFollowups(list) {
    var wrap = document.getElementById("followupChips");
    if (!wrap || !list || !list.length) return;
    wrap.innerHTML = "";
    list.forEach(function (q) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-secondary btn-sm quick-chip";
      b.textContent = q;
      b.addEventListener("click", function () { sendQuestion(q); });
      wrap.appendChild(b);
    });
  }

  async function sendQuestion(questionText) {
    var q = String(questionText || "").trim();
    if (!q) return;
    document.getElementById("askInput").value = "";
    appendUserMessage(q);
    var ui = createBotMessage();

    var sendBtn = document.getElementById("sendChatBtn");
    var stopBtn = document.getElementById("stopChatBtn");
    sendBtn.style.display = "none";
    stopBtn.style.display = "inline-flex";

    activeAbort = new AbortController();
    var accumulated = "";
    var slowTimer = setTimeout(function () {
      if (!accumulated) {
        ui.content.textContent = window.APP_LANG === "hi"
          ? "अभी थोड़ा व्यस्त है, फिर से कोशिश कर रहे हैं..."
          : "Busy right now, trying again...";
      }
    }, 3500);

    try {
      var resp = await window.apiFetch("/api/chat/stream", {
        method: "POST",
        signal: activeAbort.signal,
        body: JSON.stringify({ question: q, language: "auto" })
      });

      if (!resp.ok || !resp.body) {
        var errJson = await resp.json().catch(function () { return {}; });
        throw new Error(errJson.error || "Unable to reach Sahayak right now.");
      }

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      while (true) {
        var part = await reader.read();
        if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true });
        var events = buffer.split("\n\n");
        buffer = events.pop() || "";

        events.forEach(function (block) {
          var lines = block.split("\n");
          var evName = "message";
          var evData = "";
          lines.forEach(function (line) {
            if (line.startsWith("event:")) evName = line.slice(6).trim();
            if (line.startsWith("data:")) evData += line.slice(5).trim();
          });
          if (!evData) return;
          var parsed = {};
          try { parsed = JSON.parse(evData); } catch (_e) { return; }

          if (evName === "token" && parsed.text) {
            clearTimeout(slowTimer);
            accumulated += parsed.text;
            ui.content.innerHTML = simpleMarkdown(accumulated);
          } else if (evName === "error") {
            clearTimeout(slowTimer);
            ui.content.textContent = parsed.message || "Busy right now, please retry.";
            var rBtn = document.createElement("button");
            rBtn.type = "button";
            rBtn.className = "btn btn-cta btn-sm";
            rBtn.textContent = (i18n.errors && i18n.errors.retry) || "Retry";
            rBtn.addEventListener("click", function () { sendQuestion(q); });
            ui.actions.innerHTML = "";
            ui.actions.appendChild(rBtn);
          } else if (evName === "done") {
            clearTimeout(slowTimer);
            var finalTxt = parsed.answer || accumulated;
            ui.content.innerHTML = simpleMarkdown(finalTxt);
            ui.citations.innerHTML = "";
            if (parsed.sources && parsed.sources.length) {
              ui.citationsWrap.style.display = "block";
              parsed.sources.forEach(function (src) {
                var chip = document.createElement("button");
                chip.type = "button";
                chip.className = "cite-chip";
                chip.textContent = src.filename + " (p. " + src.page + ")";
                chip.addEventListener("click", function () {
                  window.openPageViewer(src.filename, src.page, "");
                });
                ui.citations.appendChild(chip);
              });
            }
            addActionButtons(ui, finalTxt, parsed.query_log_id, q);
            renderFollowups(parsed.followups || []);
          }
        });
        var box = document.getElementById("chatMessages");
        box.scrollTop = box.scrollHeight;
      }
    } catch (err) {
      clearTimeout(slowTimer);
      if (err.name === "AbortError") {
        addActionButtons(ui, accumulated || "(Stopped)", null, q);
      } else {
        ui.content.textContent = err.message || "Busy right now, please retry.";
        var retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn btn-cta btn-sm";
        retry.textContent = (i18n.errors && i18n.errors.retry) || "Retry";
        retry.addEventListener("click", function () { sendQuestion(q); });
        ui.actions.innerHTML = "";
        ui.actions.appendChild(retry);
      }
    } finally {
      clearTimeout(slowTimer);
      activeAbort = null;
      sendBtn.style.display = "inline-flex";
      stopBtn.style.display = "none";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("askForm").addEventListener("submit", function (e) {
      e.preventDefault();
      sendQuestion(document.getElementById("askInput").value);
    });

    document.getElementById("stopChatBtn").addEventListener("click", function () {
      if (activeAbort) activeAbort.abort();
    });

    var clearBtn = document.getElementById("clearChatBtn");
    if (clearBtn) {
      clearBtn.addEventListener("click", async function () {
        await window.apiFetch("/api/session/clear", { method: "POST", body: JSON.stringify({}) });
        window.location.reload();
      });
    }

    document.querySelectorAll(".quick-chip").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var span = btn.querySelector("span");
        sendQuestion(span ? span.textContent : btn.textContent);
      });
    });

    var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    var voiceBtn = document.getElementById("voiceInputBtn");
    if (SpeechRec && voiceBtn) {
      voiceBtn.style.display = "inline-flex";
      var rec = new SpeechRec();
      rec.interimResults = false;
      var listening = false;
      voiceBtn.addEventListener("click", function () {
        if (listening) { rec.stop(); return; }
        rec.lang = window.APP_LANG === "hi" ? "hi-IN" : "en-IN";
        listening = true;
        voiceBtn.textContent = aText.voice_stop || "Listening...";
        rec.start();
      });
      rec.onresult = function (ev) {
        var transcript = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : "";
        if (transcript) document.getElementById("askInput").value = transcript;
      };
      rec.onend = function () {
        listening = false;
        voiceBtn.innerHTML = "&#127908; " + (aText.voice_start || "Speak");
      };
    }
  });
})();
