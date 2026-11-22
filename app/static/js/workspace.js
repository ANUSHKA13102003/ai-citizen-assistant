/** Workspace interactions: deduplicated upload, editable Detected Details, Scheme Finder, Smart Chat (SSE, stop, regenerate, retry, PDF page viewer), and Summary export */

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
  const findSchemesTopBtn = document.getElementById("find-schemes-top-btn");
  const runFinderSideBtn = document.getElementById("run-finder-side-btn");

  const tabChatBtn = document.getElementById("tab-chat-btn");
  const tabFinderBtn = document.getElementById("tab-finder-btn");
  const tabSummaryBtn = document.getElementById("tab-summary-btn");
  const panelChat = document.getElementById("panel-chat");
  const panelFinder = document.getElementById("panel-finder");
  const panelSummary = document.getElementById("panel-summary");

  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const typingIndicator = document.getElementById("typing-indicator");
  const chatStopBtn = document.getElementById("chat-stop-btn");
  const suggestedPromptsBar = document.getElementById("suggested-prompts-bar");

  const runFinderBtn = document.getElementById("run-finder-btn");
  const finderCounts = document.getElementById("finder-counts");
  const finderResults = document.getElementById("finder-results");

  const runAnalyzeBtn = document.getElementById("run-analyze-btn");
  const summarySkeleton = document.getElementById("summary-skeleton");
  const summaryCards = document.getElementById("summary-cards");
  const summarySources = document.getElementById("summary-sources");
  const exportMdBtn = document.getElementById("export-summary-md");
  const exportPdfBtn = document.getElementById("export-summary-pdf");

  const profileForm = document.getElementById("profile-override-form");
  const pdfModal = document.getElementById("pdf-page-modal");
  const pdfModalTitle = document.getElementById("pdf-modal-title");
  const pdfModalSubtitle = document.getElementById("pdf-modal-subtitle");
  const pdfModalBody = document.getElementById("pdf-modal-body");
  const pdfModalClose = document.getElementById("pdf-modal-close");

  let consentGiven = Boolean(window.__INITIAL_CONSENT__);
  let latestSummary = window.__INITIAL_SUMMARY__ || null;
  let activeStreamController = null;
  let lastUserQuestion = "";

  if (window.__INITIAL_PROFILE__) {
    populateProfileForm(window.__INITIAL_PROFILE__);
  }
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
    const map = {
      chat: [panelChat, tabChatBtn],
      finder: [panelFinder, tabFinderBtn],
      summary: [panelSummary, tabSummaryBtn],
    };
    Object.entries(map).forEach(([key, [panel, btn]]) => {
      const active = key === tab;
      panel.classList.toggle("hidden", !active);
      panel.classList.toggle("flex", active);
      btn.classList.toggle("border-civic-saffron", active);
      btn.classList.toggle("text-civic-navy", active);
      btn.classList.toggle("dark:text-white", active);
      btn.classList.toggle("border-transparent", !active);
      btn.classList.toggle("text-slate-500", !active);
      btn.setAttribute("aria-selected", String(active));
    });
  }
  tabChatBtn.addEventListener("click", () => switchTab("chat"));
  tabFinderBtn.addEventListener("click", () => switchTab("finder"));
  tabSummaryBtn.addEventListener("click", () => switchTab("summary"));

  // Populate Detected Details form & dynamic suggested prompts
  function populateProfileForm(profile) {
    const fields = (profile && profile.fields) || {};
    const setField = (inputId, srcId, fObj) => {
      const inp = document.getElementById(inputId);
      const src = document.getElementById(srcId);
      if (!inp) return;
      inp.value = fObj && fObj.value != null ? fObj.value : "";
      if (src) {
        src.textContent = fObj && fObj.filename ? `(${fObj.filename}, p.${fObj.page})` : "";
      }
    };
    setField("prof-name", "src-name", fields.name);
    setField("prof-marks", "src-marks", fields.marks_percent);
    setField("prof-age", "src-age", fields.age);
    setField("prof-income", "src-income", fields.annual_income_inr);
    setField("prof-category", null, fields.category);
    setField("prof-state", null, fields.state);

    updateSuggestedPrompts((profile && profile.doc_types) || []);
  }

  function updateSuggestedPrompts(docTypes) {
    const prompts = [];
    if (docTypes.includes("marksheet")) {
      prompts.push("What are my subject-wise marks, CGPA, and percentage?");
    }
    if (docTypes.includes("income_certificate")) {
      prompts.push("What is my annual family income and certificate validity?");
    }
    if (docTypes.includes("resume")) {
      prompts.push("Summarize my technical skills, projects, and certifications.");
    }
    prompts.push("Which government schemes do I qualify for right now?");
    if (prompts.length < 3) {
      prompts.push("Which documents am I missing for scholarship applications?");
    }
    suggestedPromptsBar.innerHTML =
      '<span class="text-xs text-slate-500 self-center">Suggested:</span>' +
      prompts
        .slice(0, 4)
        .map(
          (p) =>
            `<button type="button" class="suggested-prompt text-xs px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 hover:bg-orange-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition">${escapeHtml(p)}</button>`
        )
        .join("");
    bindSuggestedPrompts();
  }

  function bindSuggestedPrompts() {
    document.querySelectorAll(".suggested-prompt").forEach((btn) => {
      btn.addEventListener("click", () => {
        chatInput.value = btn.textContent.trim();
        chatInput.focus();
      });
    });
  }
  bindSuggestedPrompts();

  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const overrides = {
      name: document.getElementById("prof-name").value.trim(),
      marks_percent: document.getElementById("prof-marks").value.trim(),
      age: document.getElementById("prof-age").value.trim(),
      annual_income_inr: document.getElementById("prof-income").value.trim(),
      category: document.getElementById("prof-category").value,
      state: document.getElementById("prof-state").value.trim(),
    };
    const resp = await apiFetch("/api/profile/override", {
      method: "POST",
      body: JSON.stringify({ overrides }),
    });
    if (resp.ok) {
      const data = await resp.json();
      populateProfileForm(data.profile);
      showToast("Detected details updated.", "success");
    }
  });

  // Render uploaded citizen files
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
        const badges = [
          `<span class="px-1.5 py-0.5 rounded bg-orange-100 dark:bg-orange-950/50 text-orange-800 dark:text-orange-300 text-[10px]">${escapeHtml(d.doc_type_label || "Document")}</span>`,
        ];
        if (d.table_pages > 0)
          badges.push('<span class="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-[10px]">Tables</span>');
        if (d.ocr_pages > 0)
          badges.push('<span class="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 text-[10px]">OCR</span>');
        return `
          <li class="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="font-medium truncate" title="${escapeHtml(d.filename)}">${escapeHtml(d.filename)}</p>
              <div class="flex flex-wrap gap-1 mt-0.5">${badges.join("")}</div>
            </div>
            <span class="shrink-0 text-[11px] text-slate-500">${d.extracted_pages}/${d.total_pages} pg</span>
          </li>`;
      })
      .join("");
  }

  async function uploadFiles(fileList) {
    if (!consentGiven) {
      showToast("Please accept the privacy notice before uploading.", "warning");
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
      if (data.profile) populateProfileForm(data.profile);

      if (data.duplicates && data.duplicates.length > 0) {
        data.duplicates.forEach((fn) => showToast(`${fn} already uploaded`, "warning"));
      }
      if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach((w) => showToast(w, "warning"));
      }
      if (data.rebuilt) {
        showToast(`Indexed ${data.documents.length} PDF(s) (${data.total_chunks} chunks).`, "success");
      }
    } catch (_err) {
      showToast("Network error while uploading PDFs.", "error");
    } finally {
      fileInput.value = "";
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

  // Load Sample Documents
  loadDemoBtn.addEventListener("click", async () => {
    const resp = await apiFetch("/api/load-demo-docs", {
      method: "POST",
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Could not load sample documents.", "error");
      return;
    }
    consentGiven = true;
    consentBanner.classList.add("hidden");
    renderFiles(data.documents, data.total_chunks);
    if (data.profile) populateProfileForm(data.profile);
    showToast(`Loaded ${data.documents.length} sample citizen PDFs (${data.total_chunks} chunks).`, "success");
  });

  // Delete My Data Now
  clearDataBtn.addEventListener("click", async () => {
    const resp = await apiFetch("/api/session/clear", { method: "POST", body: "{}" });
    if (resp.ok) {
      renderFiles([], 0);
      populateProfileForm({ fields: {}, doc_types: [] });
      latestSummary = null;
      exportMdBtn.disabled = true;
      exportPdfBtn.disabled = true;
      summaryCards.innerHTML = '<div class="sm:col-span-2 text-sm text-slate-500 italic py-8 text-center">Session cleared. Upload new PDFs to begin.</div>';
      summarySources.classList.add("hidden");
      finderCounts.classList.add("hidden");
      finderResults.innerHTML = '<div class="text-sm text-slate-500 italic py-10 text-center">Session cleared. Upload your documents to find schemes.</div>';
      chatMessages.innerHTML = '<div class="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 text-xs text-emerald-800 dark:text-emerald-200">All session vectors, documents, and chat history have been permanently deleted.</div>';
      consentGiven = false;
      consentBanner.classList.remove("hidden");
      if (consentCheckbox) consentCheckbox.checked = false;
      if (consentAcceptBtn) consentAcceptBtn.disabled = true;
      showToast("Session data deleted.", "success");
    }
  });

  // In-app PDF Page Viewer modal
  async function openPageViewer(filename, page, snippet) {
    const resp = await fetch(`/api/document-page?filename=${encodeURIComponent(filename)}&page=${encodeURIComponent(page)}`);
    if (!resp.ok) {
      showToast("Could not load page preview.", "error");
      return;
    }
    const data = await resp.json();
    pdfModalTitle.textContent = `${data.filename} — Page ${data.page} of ${data.total_pages}`;
    pdfModalSubtitle.textContent = snippet ? `Highlighted match: "${snippet.slice(0, 80)}..."` : "Extracted page text";
    let safeText = escapeHtml(data.text || "");
    if (snippet) {
      const cleanSnip = escapeHtml(snippet.slice(0, 48).trim());
      if (cleanSnip.length > 6 && safeText.includes(cleanSnip)) {
        safeText = safeText.replace(
          cleanSnip,
          `<mark class="bg-amber-200 dark:bg-amber-600/60 text-slate-900 dark:text-white px-1 rounded">${cleanSnip}</mark>`
        );
      }
    }
    pdfModalBody.innerHTML = safeText;
    pdfModal.classList.remove("hidden");
  }
  pdfModalClose.addEventListener("click", () => pdfModal.classList.add("hidden"));
  pdfModal.addEventListener("click", (e) => {
    if (e.target === pdfModal) pdfModal.classList.add("hidden");
  });

  // Simple safe Markdown renderer for assistant answers
  function renderMarkdown(raw) {
    let html = escapeHtml(raw || "");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="underline text-civic-saffron font-medium">$1 &nearr;</a>');
    return html;
  }

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
      <div class="max-w-[90%] w-full sm:w-auto rounded-2xl rounded-bl-sm bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 px-4 py-3 text-sm space-y-2.5 shadow-sm">
        <div class="answer-text whitespace-pre-wrap text-slate-800 dark:text-slate-100 leading-relaxed"></div>
        <div class="retry-wrap hidden pt-1">
          <button type="button" class="retry-btn px-3 py-1.5 rounded-lg bg-civic-saffron text-white text-xs font-semibold">Retry</button>
        </div>
        <div class="sources-wrap hidden border-t border-slate-200 dark:border-slate-700 pt-2">
          <p class="text-[11px] font-semibold text-civic-navy dark:text-orange-400 mb-1">Sources (click to view page):</p>
          <div class="sources-chips flex flex-wrap gap-1.5"></div>
        </div>
        <div class="followups-wrap hidden border-t border-slate-200 dark:border-slate-700 pt-2">
          <p class="text-[11px] font-semibold text-slate-500 mb-1">Follow-up questions:</p>
          <div class="followups-chips flex flex-wrap gap-1.5"></div>
        </div>
        <div class="actions-bar hidden flex items-center justify-between gap-3 pt-1 text-xs text-slate-500">
          <span class="meta-latency"></span>
          <div class="flex items-center gap-1.5">
            <button type="button" class="regen-btn px-2 py-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700">Regenerate</button>
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

  function showFriendlyError(bubble, message, questionToRetry) {
    const textEl = bubble.querySelector(".answer-text");
    const retryWrap = bubble.querySelector(".retry-wrap");
    textEl.textContent = message || "The AI service is temporarily unavailable. Your documents are safe — please try again.";
    retryWrap.classList.remove("hidden");
    const retryBtn = bubble.querySelector(".retry-btn");
    retryBtn.onclick = () => {
      bubble.remove();
      sendChatQuestion(questionToRetry, false);
    };
  }

  function finalizeAssistantBubble(wrapper, meta, questionText) {
    const textEl = wrapper.querySelector(".answer-text");
    const sourcesWrap = wrapper.querySelector(".sources-wrap");
    const chips = wrapper.querySelector(".sources-chips");
    const followupsWrap = wrapper.querySelector(".followups-wrap");
    const followupsChips = wrapper.querySelector(".followups-chips");
    const actionsBar = wrapper.querySelector(".actions-bar");
    const latencyEl = wrapper.querySelector(".meta-latency");

    if (meta.answer) {
      textEl.innerHTML = renderMarkdown(meta.answer);
    }

    const srcs = meta.sources || [];
    if (srcs.length > 0) {
      sourcesWrap.classList.remove("hidden");
      chips.innerHTML = srcs
        .map(
          (s, idx) =>
            `<button type="button" data-idx="${idx}" class="citation-chip px-2.5 py-0.5 rounded-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-600 hover:border-civic-saffron text-[11px] font-medium transition">${escapeHtml(s.filename)} • p.${s.page}</button>`
        )
        .join("");
      chips.querySelectorAll(".citation-chip").forEach((btn) => {
        const s = srcs[Number(btn.getAttribute("data-idx"))];
        btn.addEventListener("click", () => openPageViewer(s.filename, s.page, s.snippet || ""));
      });
    }

    const fups = meta.followups || [];
    if (fups.length > 0) {
      followupsWrap.classList.remove("hidden");
      followupsChips.innerHTML = fups
        .map(
          (q) =>
            `<button type="button" class="followup-chip text-left text-[11px] px-2.5 py-1 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 hover:border-civic-saffron transition">${escapeHtml(q)}</button>`
        )
        .join("");
      followupsChips.querySelectorAll(".followup-chip").forEach((btn) => {
        btn.addEventListener("click", () => sendChatQuestion(btn.textContent.trim(), true));
      });
    }

    actionsBar.classList.remove("hidden");
    latencyEl.textContent = `${meta.retrieval_mode || "hybrid"} • ${meta.total_latency_ms || 0} ms`;

    wrapper.querySelector(".copy-btn").addEventListener("click", () => {
      navigator.clipboard.writeText(meta.answer || textEl.textContent);
      showToast("Copied response to clipboard.", "info");
    });

    wrapper.querySelector(".regen-btn").addEventListener("click", () => {
      wrapper.remove();
      sendChatQuestion(questionText, false);
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

  async function sendChatQuestion(question, showUserBubble = true) {
    if (!question) return;
    lastUserQuestion = question;
    if (showUserBubble) appendUserBubble(question);

    typingIndicator.classList.remove("hidden");
    typingIndicator.classList.add("flex");

    const bubble = createAssistantBubble();
    const answerEl = bubble.querySelector(".answer-text");
    activeStreamController = new AbortController();

    try {
      const resp = await apiFetch("/api/chat/stream", {
        method: "POST",
        signal: activeStreamController.signal,
        body: JSON.stringify({
          question,
          retrieval_mode: retrievalSelect.value,
          language: getLanguage(),
        }),
      });

      const contentType = resp.headers.get("content-type") || "";
      if (!resp.ok || !contentType.includes("text/event-stream")) {
        const errData = await resp.json().catch(() => ({}));
        showFriendlyError(bubble, errData.error, question);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let rawText = "";

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
            rawText += parsed.text || "";
            answerEl.innerHTML = renderMarkdown(rawText);
            chatMessages.scrollTop = chatMessages.scrollHeight;
          } else if (evtType === "done") {
            finalizeAssistantBubble(bubble, parsed, question);
          } else if (evtType === "error") {
            showFriendlyError(bubble, parsed.message, question);
          }
        }
      }
    } catch (err) {
      if (err && err.name === "AbortError") {
        answerEl.textContent += " [Stopped]";
      } else {
        showFriendlyError(bubble, "Connection interrupted. Please try again.", question);
      }
    } finally {
      activeStreamController = null;
      typingIndicator.classList.add("hidden");
      typingIndicator.classList.remove("flex");
    }
  }

  chatStopBtn.addEventListener("click", () => {
    if (activeStreamController) activeStreamController.abort();
  });

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = chatInput.value.trim();
    if (!q) return;
    chatInput.value = "";
    sendChatQuestion(q, true);
  });

  // One-Click Scheme Finder
  async function runSchemeFinder() {
    switchTab("finder");
    finderResults.innerHTML = '<div class="h-28 rounded-xl skeleton"></div><div class="h-28 rounded-xl skeleton"></div>';
    const resp = await apiFetch("/api/scheme-finder", {
      method: "POST",
      body: JSON.stringify({ use_sample_citizen: true }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      finderResults.innerHTML = `<div class="p-6 text-center text-sm text-rose-600">${escapeHtml(data.error || "Could not run Scheme Finder.")}</div>`;
      return;
    }
    const c = data.counts || {};
    finderCounts.classList.remove("hidden");
    finderCounts.innerHTML = `
      <div class="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800"><p class="text-xs text-emerald-700 dark:text-emerald-300">Eligible</p><p class="text-xl font-extrabold text-emerald-800 dark:text-emerald-200">${c.eligible || 0}</p></div>
      <div class="p-3 rounded-xl bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800"><p class="text-xs text-blue-700 dark:text-blue-300">Likely Eligible</p><p class="text-xl font-extrabold text-blue-800 dark:text-blue-200">${c.likely || 0}</p></div>
      <div class="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800"><p class="text-xs text-amber-700 dark:text-amber-300">Needs More Info</p><p class="text-xl font-extrabold text-amber-800 dark:text-amber-200">${c.needs_info || 0}</p></div>
      <div class="p-3 rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"><p class="text-xs text-slate-600 dark:text-slate-400">Not Eligible</p><p class="text-xl font-extrabold text-slate-700 dark:text-slate-300">${c.not_eligible || 0}</p></div>
    `;

    const badgeColor = (tier) => {
      if (tier === "Eligible") return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300";
      if (tier === "Likely eligible") return "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300";
      if (tier === "Needs more info") return "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300";
      return "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-300";
    };

    finderResults.innerHTML = (data.matches || [])
      .map((m) => {
        const reasons = []
          .concat(m.reasons_pass.map((r) => `<li class="text-emerald-700 dark:text-emerald-300">&#10003; ${escapeHtml(r)}</li>`))
          .concat(m.reasons_fail.map((r) => `<li class="text-rose-600 dark:text-rose-400">&#10007; ${escapeHtml(r)}</li>`))
          .concat(m.reasons_unknown.map((r) => `<li class="text-amber-700 dark:text-amber-300">? ${escapeHtml(r)}</li>`));
        const missing =
          m.missing_documents && m.missing_documents.length
            ? `<p class="text-xs text-amber-700 dark:text-amber-300 mt-1"><strong>Missing documents:</strong> ${escapeHtml(m.missing_documents.join(", "))}</p>`
            : `<p class="text-xs text-emerald-700 dark:text-emerald-300 mt-1"><strong>All required documents available</strong></p>`;
        return `
          <div class="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40 space-y-2">
            <div class="flex items-start justify-between gap-2">
              <div>
                <h3 class="font-bold text-sm text-slate-900 dark:text-white">${escapeHtml(m.name)}</h3>
                <p class="text-xs text-slate-500">${escapeHtml(m.ministry)} • ${escapeHtml(m.category)}</p>
              </div>
              <span class="px-2.5 py-0.5 rounded-full text-xs font-bold shrink-0 ${badgeColor(m.tier)}">${escapeHtml(m.tier)}</span>
            </div>
            <p class="text-xs text-slate-700 dark:text-slate-300">${escapeHtml(m.benefit)}</p>
            ${reasons.length ? `<ul class="text-xs space-y-0.5">${reasons.join("")}</ul>` : ""}
            ${missing}
            <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200 dark:border-slate-700 text-xs">
              ${m.official_url ? `<a href="${escapeHtml(m.official_url)}" target="_blank" rel="noopener noreferrer" class="underline text-civic-navy dark:text-orange-400 font-semibold">Official Portal &nearr;</a>` : "<span></span>"}
              <button type="button" data-scheme="${escapeHtml(m.name)}" class="ask-scheme-btn px-3 py-1 rounded-lg bg-civic-navy text-white font-semibold hover:bg-civic-navyLight">
                Ask about this scheme
              </button>
            </div>
          </div>`;
      })
      .join("");

    finderResults.querySelectorAll(".ask-scheme-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sName = btn.getAttribute("data-scheme");
        switchTab("chat");
        sendChatQuestion(`Explain my eligibility, benefits, and required documents for ${sName}.`, true);
      });
    });
  }

  findSchemesTopBtn.addEventListener("click", runSchemeFinder);
  runFinderSideBtn.addEventListener("click", runSchemeFinder);
  runFinderBtn.addEventListener("click", runSchemeFinder);

  // If navigated with ?ask_scheme=...
  if (window.__ASK_SCHEME__ && window.__ASK_SCHEME__.name) {
    const sName = window.__ASK_SCHEME__.name;
    chatInput.value = `What are the eligibility rules, benefits, and required documents for ${sName}?`;
  }

  // Document Summary
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
      summarySources.innerHTML =
        '<span class="text-xs font-semibold text-slate-500 mr-1">Sources:</span>' +
        data.sources
          .map(
            (s) =>
              `<button type="button" data-fn="${escapeHtml(s.filename)}" data-pg="${s.page}" class="sum-src-chip text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:border-civic-saffron">${escapeHtml(s.filename)} • p.${s.page}</button>`
          )
          .join("");
      summarySources.querySelectorAll(".sum-src-chip").forEach((btn) => {
        btn.addEventListener("click", () =>
          openPageViewer(btn.getAttribute("data-fn"), Number(btn.getAttribute("data-pg")), "")
        );
      });
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
      body: JSON.stringify({
        format,
        sections: latestSummary.sections,
        sources: latestSummary.sources,
      }),
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
