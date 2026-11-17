/** Workspace interactions: consent gate, drag-drop upload, SSE streaming chat, feedback, summary export */

document.addEventListener("DOMContentLoaded", () => {
  const { apiFetch, showToast, getLanguage, escapeHtml } = window.CitizenApp;

  const consentBanner = document.getElementById("consent-banner");
  const consentCheckbox = document.getElementById("consent-checkbox");
  const consentAcceptBtn = document.getElementById("consent-accept-btn");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("pdf-file-input");
  const uploadProgressWrap = document.getElementById("upload-progress-wrap");
  const uploadProgressBar = document.getElementById("upload-progress-bar");
  const uploadProgressPct = document.getElementById("upload-progress-pct");
  const filesList = document.getElementById("uploaded-files-list");
  const chunkBadge = document.getElementById("chunk-count-badge");
  const loadDemoBtn = document.getElementById("load-demo-btn");
  const clearDataBtn = document.getElementById("clear-data-btn");
  const retrievalSelect = document.getElementById("retrieval-mode-select");

  const tabChatBtn = document.getElementById("tab-chat-btn");
  const tabSummaryBtn = document.getElementById("tab-summary-btn");
  const panelChat = document.getElementById("panel-chat");
  const panelSummary = document.getElementById("panel-summary");

  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const typingIndicator = document.getElementById("typing-indicator");

  const runAnalyzeBtn = document.getElementById("run-analyze-btn");
  const summarySkeleton = document.getElementById("summary-skeleton");
  const summaryCards = document.getElementById("summary-cards");
  const summarySources = document.getElementById("summary-sources");
  const exportMdBtn = document.getElementById("export-summary-md");
  const exportPdfBtn = document.getElementById("export-summary-pdf");

  let consentGiven = Boolean(window.__INITIAL_CONSENT__);
  let latestSummary = window.__INITIAL_SUMMARY__ || null;

  if (latestSummary) {
    renderSummary(latestSummary);
  }

  // Consent handling
  if (consentCheckbox && consentAcceptBtn) {
    consentCheckbox.addEventListener("change", () => {
      consentAcceptBtn.disabled = !consentCheckbox.checked;
    });
    consentAcceptBtn.addEventListener("click", async () => {
      const resp = await apiFetch("/api/consent", {
        method: "POST",
        body: JSON.stringify({ accepted: true }),
      });
      if (resp.ok) {
        consentGiven = true;
        consentBanner.classList.add("hidden");
        showToast("Privacy consent recorded for this session.", "success");
      }
    });
  }

  // Tabs
  function switchTab(tab) {
    const isChat = tab === "chat";
    panelChat.classList.toggle("hidden", !isChat);
    panelChat.classList.toggle("flex", isChat);
    panelSummary.classList.toggle("hidden", isChat);
    panelSummary.classList.toggle("flex", !isChat);

    tabChatBtn.classList.toggle("border-civic-saffron", isChat);
    tabChatBtn.classList.toggle("border-transparent", !isChat);
    tabSummaryBtn.classList.toggle("border-civic-saffron", !isChat);
    tabSummaryBtn.classList.toggle("border-transparent", isChat);
  }
  tabChatBtn.addEventListener("click", () => switchTab("chat"));
  tabSummaryBtn.addEventListener("click", () => switchTab("summary"));

  // File upload
  function renderFiles(docs, totalChunks) {
    if (chunkBadge) {
      chunkBadge.textContent = `${totalChunks || 0} chunks`;
    }
    if (!docs || docs.length === 0) {
      filesList.innerHTML = '<li class="text-slate-400 italic py-2">No documents uploaded yet.</li>';
      return;
    }
    filesList.innerHTML = docs
      .map((d) => {
        const badges = [];
        if (d.table_pages > 0) badges.push('<span class="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-[10px]">Tables</span>');
        if (d.ocr_pages > 0) badges.push('<span class="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 text-[10px]">OCR</span>');
        return `
          <li class="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="font-medium truncate" title="${escapeHtml(d.filename)}">${escapeHtml(d.filename)}</p>
              <div class="flex gap-1 mt-0.5">${badges.join("")}</div>
            </div>
            <span class="shrink-0 text-[11px] text-slate-500">${d.extracted_pages}/${d.total_pages} pg</span>
          </li>`;
      })
      .join("");
  }

  async function uploadFiles(fileList) {
    if (!consentGiven) {
      showToast("Please accept the privacy consent box before uploading.", "warning");
      consentBanner.classList.remove("hidden");
      return;
    }
    if (!fileList || fileList.length === 0) return;

    const formData = new FormData();
    for (const f of fileList) {
      formData.append("files", f);
    }

    uploadProgressWrap.classList.remove("hidden");
    uploadProgressBar.style.width = "45%";
    uploadProgressPct.textContent = "45%";

    try {
      const resp = await apiFetch("/api/upload", { method: "POST", body: formData });
      uploadProgressBar.style.width = "90%";
      uploadProgressPct.textContent = "90%";
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || "Upload failed.", "error");
        return;
      }
      uploadProgressBar.style.width = "100%";
      uploadProgressPct.textContent = "100%";
      renderFiles(data.documents, data.total_chunks);
      if (data.chat_cleared) {
        chatMessages.innerHTML =
          '<div class="p-3 rounded-xl bg-blue-50 dark:bg-slate-800 text-xs text-slate-600 dark:text-slate-300">Document set updated — ChromaDB index rebuilt and chat history cleared for isolation.</div>';
      }
      if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach((w) => showToast(w, "warning"));
      } else {
        showToast(`Indexed ${data.documents.length} PDF(s) (${data.total_chunks} chunks).`, "success");
      }
    } catch (err) {
      showToast("Network error while uploading PDFs.", "error");
    } finally {
      setTimeout(() => uploadProgressWrap.classList.add("hidden"), 700);
    }
  }

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("border-civic-saffron", "bg-orange-50/40");
  });
  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-civic-saffron", "bg-orange-50/40");
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-civic-saffron", "bg-orange-50/40");
    uploadFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));

  // Load Demo Docs
  loadDemoBtn.addEventListener("click", async () => {
    const resp = await apiFetch("/api/load-demo-docs", {
      method: "POST",
      body: JSON.stringify({ scheme_id: "nsp_post_matric" }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Could not load sample docs.", "error");
      return;
    }
    consentGiven = true;
    consentBanner.classList.add("hidden");
    renderFiles(data.documents, data.total_chunks);
    showToast(`Loaded ${data.documents.length} sample PDFs (${data.total_chunks} chunks).`, "success");
  });

  // Delete My Data Now
  clearDataBtn.addEventListener("click", async () => {
    const resp = await apiFetch("/api/session/clear", { method: "POST", body: "{}" });
    if (resp.ok) {
      renderFiles([], 0);
      latestSummary = null;
      exportMdBtn.disabled = true;
      exportPdfBtn.disabled = true;
      summaryCards.innerHTML = '<div class="sm:col-span-2 text-sm text-slate-500 italic py-8 text-center">Session cleared. Upload new PDFs to begin.</div>';
      summarySources.classList.add("hidden");
      chatMessages.innerHTML = '<div class="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 text-xs text-emerald-800 dark:text-emerald-200">All session vectors, documents, and chat history have been permanently deleted.</div>';
      consentGiven = false;
      consentBanner.classList.remove("hidden");
      if (consentCheckbox) consentCheckbox.checked = false;
      if (consentAcceptBtn) consentAcceptBtn.disabled = true;
      showToast("Session data deleted.", "success");
    }
  });

  // Suggested prompts
  document.querySelectorAll(".suggested-prompt").forEach((btn) => {
    btn.addEventListener("click", () => {
      chatInput.value = btn.textContent.trim();
      chatInput.focus();
    });
  });

  function appendUserBubble(text) {
    const div = document.createElement("div");
    div.className = "flex justify-end";
    div.innerHTML = `<div class="max-w-[82%] rounded-2xl rounded-br-sm bg-civic-navy text-white px-4 py-2.5 text-sm shadow-sm">${escapeHtml(text)}</div>`;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function createAssistantBubble() {
    const wrapper = document.createElement("div");
    wrapper.className = "flex justify-start";
    wrapper.innerHTML = `
      <div class="max-w-[88%] rounded-2xl rounded-bl-sm bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 px-4 py-3 text-sm space-y-2.5 shadow-sm">
        <div class="answer-text whitespace-pre-wrap text-slate-800 dark:text-slate-100 leading-relaxed"></div>
        <div class="sources-wrap hidden border-t border-slate-200 dark:border-slate-700 pt-2">
          <details class="text-xs">
            <summary class="cursor-pointer font-semibold text-civic-navy dark:text-orange-400">Sources (<span class="src-count">0</span>)</summary>
            <div class="sources-chips flex flex-wrap gap-1.5 mt-1.5"></div>
          </details>
        </div>
        <div class="actions-bar hidden flex items-center justify-between gap-3 pt-1 text-xs text-slate-500">
          <span class="meta-latency"></span>
          <div class="flex items-center gap-1.5">
            <button type="button" class="copy-btn px-2 py-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700">Copy</button>
            <button type="button" class="fb-up px-2 py-0.5 rounded hover:bg-emerald-100 dark:hover:bg-emerald-900/40" title="Helpful">&#128077;</button>
            <button type="button" class="fb-down px-2 py-0.5 rounded hover:bg-rose-100 dark:hover:bg-rose-900/40" title="Not helpful">&#128078;</button>
          </div>
        </div>
      </div>`;
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return wrapper;
  }

  function finalizeAssistantBubble(wrapper, meta) {
    const textEl = wrapper.querySelector(".answer-text");
    const sourcesWrap = wrapper.querySelector(".sources-wrap");
    const srcCount = wrapper.querySelector(".src-count");
    const chips = wrapper.querySelector(".sources-chips");
    const actionsBar = wrapper.querySelector(".actions-bar");
    const latencyEl = wrapper.querySelector(".meta-latency");

    if (meta.answer) {
      textEl.textContent = meta.answer;
    }

    const srcs = meta.sources || [];
    if (srcs.length > 0) {
      sourcesWrap.classList.remove("hidden");
      srcCount.textContent = srcs.length;
      chips.innerHTML = srcs
        .map((s) => `<span class="px-2 py-0.5 rounded-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-600 text-[11px]">${escapeHtml(s.filename)} • p.${s.page}</span>`)
        .join("");
    }

    actionsBar.classList.remove("hidden");
    latencyEl.textContent = `${meta.retrieval_mode || "hybrid"} • ${meta.total_latency_ms || 0} ms`;

    wrapper.querySelector(".copy-btn").addEventListener("click", () => {
      navigator.clipboard.writeText(textEl.textContent);
      showToast("Copied response to clipboard.", "info");
    });

    const sendFeedback = async (rating, btn) => {
      const r = await apiFetch("/api/feedback", {
        method: "POST",
        body: JSON.stringify({ rating, query_log_id: meta.query_log_id || null }),
      });
      if (r.ok) {
        btn.classList.add("ring-2", "ring-civic-saffron");
        showToast("Thanks for your feedback!", "success");
      }
    };
    wrapper.querySelector(".fb-up").addEventListener("click", (e) => sendFeedback(1, e.currentTarget));
    wrapper.querySelector(".fb-down").addEventListener("click", (e) => sendFeedback(-1, e.currentTarget));
  }

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = chatInput.value.trim();
    if (!question) return;
    chatInput.value = "";
    appendUserBubble(question);

    typingIndicator.classList.remove("hidden");
    typingIndicator.classList.add("flex");

    const bubble = createAssistantBubble();
    const answerEl = bubble.querySelector(".answer-text");

    try {
      const resp = await apiFetch("/api/chat/stream", {
        method: "POST",
        body: JSON.stringify({
          question,
          retrieval_mode: retrievalSelect.value,
          language: getLanguage(),
        }),
      });

      const contentType = resp.headers.get("content-type") || "";
      if (!resp.ok || !contentType.includes("text/event-stream")) {
        const errData = await resp.json().catch(() => ({}));
        answerEl.textContent = errData.error || "Failed to generate answer.";
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const rawEvt of events) {
          const lines = rawEvt.split("\n");
          let evtType = "message";
          let dataLine = "";
          for (const line of lines) {
            if (line.startsWith("event:")) evtType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }
          if (!dataLine) continue;
          const parsed = JSON.parse(dataLine);
          if (evtType === "token") {
            answerEl.textContent += parsed.text || "";
            chatMessages.scrollTop = chatMessages.scrollHeight;
          } else if (evtType === "done") {
            finalizeAssistantBubble(bubble, parsed);
          } else if (evtType === "error") {
            answerEl.textContent = parsed.message || "Generation error.";
          }
        }
      }
    } catch (err) {
      answerEl.textContent = "Connection interrupted while streaming answer.";
    } finally {
      typingIndicator.classList.add("hidden");
      typingIndicator.classList.remove("flex");
    }
  });

  // Document Summary (Mode 1)
  function renderSummary(data) {
    latestSummary = data;
    summaryCards.innerHTML = (data.sections || [])
      .map((sec) => {
        const missing = sec.content === "Not found in uploaded documents";
        return `
          <div class="p-4 rounded-xl border ${missing ? "border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40" : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50"}">
            <h3 class="text-xs font-bold uppercase tracking-wider text-civic-navy dark:text-orange-400 mb-2">${escapeHtml(sec.label)}</h3>
            <p class="text-sm whitespace-pre-wrap ${missing ? "text-slate-400 italic" : "text-slate-700 dark:text-slate-200"}">${escapeHtml(sec.content)}</p>
          </div>`;
      })
      .join("");

    if (data.sources && data.sources.length > 0) {
      summarySources.classList.remove("hidden");
      summarySources.innerHTML = '<span class="text-xs font-semibold text-slate-500 mr-1">Sources:</span>' +
        data.sources.map((s) => `<span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">${escapeHtml(s.filename)} • p.${s.page}</span>`).join("");
    }
    exportMdBtn.disabled = false;
    exportPdfBtn.disabled = false;
  }

  runAnalyzeBtn.addEventListener("click", async () => {
    summarySkeleton.classList.remove("hidden");
    summaryCards.classList.add("hidden");
    try {
      const resp = await apiFetch("/api/analyze", {
        method: "POST",
        body: JSON.stringify({ language: getLanguage() === "hi" ? "hi" : "en" }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || "Analysis failed.", "error");
        return;
      }
      renderSummary(data);
      showToast("7-section document summary generated.", "success");
    } finally {
      summarySkeleton.classList.add("hidden");
      summaryCards.classList.remove("hidden");
    }
  });

  async function downloadSummary(format) {
    if (!latestSummary) return;
    const resp = await apiFetch("/api/export/summary", {
      method: "POST",
      body: JSON.stringify({ format, sections: latestSummary.sections, sources: latestSummary.sources }),
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = format === "pdf" ? "citizen_document_summary.pdf" : "citizen_document_summary.md";
    a.click();
    URL.revokeObjectURL(url);
  }
  exportMdBtn.addEventListener("click", () => downloadSummary("md"));
  exportPdfBtn.addEventListener("click", () => downloadSummary("pdf"));
});
