/** Eligibility Checker UI logic: separate citizen vs scheme stores, override banner, and inline upload prompts */

document.addEventListener("DOMContentLoaded", () => {
  const { apiFetch, showToast, getLanguage, escapeHtml } = window.CitizenApp;

  const form = document.getElementById("eligibility-form");
  const schemeSelect = document.getElementById("scheme-select");
  const schemeFile = document.getElementById("scheme-file-input");
  const useSampleCheck = document.getElementById("use-sample-citizen");
  const clearSchemeFileBtn = document.getElementById("clear-scheme-file-btn");
  const uploadCitizenHereBtn = document.getElementById("upload-citizen-here-btn");
  const inlineCitizenInput = document.getElementById("inline-citizen-upload-input");

  const citizenDocsPills = document.getElementById("citizen-docs-pills");
  const schemeDocsPills = document.getElementById("scheme-docs-pills");
  const checkedBanner = document.getElementById("checked-scheme-banner");

  const resultsWrap = document.getElementById("eligibility-results");
  const verdictBadge = document.getElementById("verdict-badge");
  const resSchemeName = document.getElementById("res-scheme-name");
  const factsPills = document.getElementById("extracted-facts-pills");
  const aiText = document.getElementById("ai-explanation-text");
  const criteriaTbody = document.getElementById("criteria-tbody");
  const checklistTbody = document.getElementById("checklist-tbody");

  const exportMdBtn = document.getElementById("export-checklist-md");
  const exportPdfBtn = document.getElementById("export-checklist-pdf");

  let lastResult = null;

  function badgeClass(verdict) {
    if (verdict === "ELIGIBLE") return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300";
    if (verdict.includes("NOT ELIGIBLE")) return "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-300";
    return "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300";
  }

  schemeFile.addEventListener("change", () => {
    if (schemeFile.files[0]) {
      checkedBanner.classList.remove("hidden");
      checkedBanner.textContent = `Uploaded scheme "${schemeFile.files[0].name}" will override the library dropdown.`;
      clearSchemeFileBtn.classList.remove("hidden");
    }
  });

  clearSchemeFileBtn.addEventListener("click", () => {
    schemeFile.value = "";
    clearSchemeFileBtn.classList.add("hidden");
    checkedBanner.classList.add("hidden");
  });

  uploadCitizenHereBtn.addEventListener("click", () => inlineCitizenInput.click());

  inlineCitizenInput.addEventListener("change", async () => {
    if (!inlineCitizenInput.files.length) return;
    await apiFetch("/api/consent", { method: "POST", body: JSON.stringify({ accepted: true }) });
    const fd = new FormData();
    for (const f of inlineCitizenInput.files) fd.append("files", f);
    const resp = await apiFetch("/api/upload", { method: "POST", body: fd });
    const data = await resp.json();
    inlineCitizenInput.value = "";
    if (!resp.ok) {
      showToast(data.error || "Upload failed.", "error");
      return;
    }
    if (data.duplicates && data.duplicates.length) {
      data.duplicates.forEach((fn) => showToast(`${fn} already uploaded`, "warning"));
    } else {
      showToast("Citizen document uploaded. Re-checking eligibility...", "success");
    }
    updateDocPills(data.documents, data.scheme_documents);
    form.requestSubmit();
  });

  function updateDocPills(cDocs, sDocs) {
    if (cDocs && cDocs.length) {
      citizenDocsPills.innerHTML = cDocs
        .map((d) => `<span class="inline-block px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 mr-1">${escapeHtml(d.filename)}</span>`)
        .join("");
    }
    if (sDocs && sDocs.length) {
      schemeDocsPills.innerHTML = sDocs
        .map((s) => `<span class="inline-block px-2 py-0.5 rounded bg-orange-100 dark:bg-orange-950/50 text-orange-800 dark:text-orange-300 mr-1">${escapeHtml(s.filename)}</span>`)
        .join("");
    }
  }

  function renderResult(data) {
    lastResult = data;
    resultsWrap.classList.remove("hidden");
    resSchemeName.textContent = data.scheme_name;
    verdictBadge.textContent = data.rule_based_verdict;
    verdictBadge.className = `px-3 py-1 rounded-full text-xs font-bold ${badgeClass(data.rule_based_verdict)}`;
    aiText.textContent = data.ai_explanation || "";

    if (data.checked_scheme_label) {
      checkedBanner.classList.remove("hidden");
      checkedBanner.textContent = `Currently checking — ${data.checked_scheme_label}`;
    }
    if (data.duplicate_scheme) {
      showToast(`${data.scheme_name} already uploaded`, "warning");
    }
    updateDocPills(data.citizen_documents, data.scheme_documents);

    const facts = data.extracted_citizen_facts || {};
    const pills = [];
    if (facts.marks_percentage != null) pills.push(`Marks: ${facts.marks_percentage}%`);
    if (facts.cgpa != null) pills.push(`CGPA: ${facts.cgpa}`);
    if (facts.annual_income_inr != null) pills.push(`Income: ₹${Number(facts.annual_income_inr).toLocaleString("en-IN")}`);
    if (facts.age_years != null) pills.push(`Age: ${facts.age_years}`);
    if (facts.category) pills.push(`Category: ${facts.category}`);
    if (facts.state) pills.push(`State: ${facts.state}`);
    factsPills.innerHTML = pills.map((p) => `<span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800">${escapeHtml(p)}</span>`).join("");

    // Criteria rows (with upload prompt button when missing)
    if (!data.criteria_checks || data.criteria_checks.length === 0) {
      criteriaTbody.innerHTML = '<tr><td colspan="4" class="py-3 text-slate-400 italic">No numeric thresholds specified for this scheme.</td></tr>';
    } else {
      criteriaTbody.innerHTML = data.criteria_checks
        .map((c) => {
          const stCls =
            c.status === "PASS"
              ? "bg-emerald-100 text-emerald-800"
              : c.status === "FAIL"
                ? "bg-rose-100 text-rose-800"
                : "bg-amber-100 text-amber-800";
          const valHtml =
            c.status === "UNKNOWN"
              ? `<div class="flex flex-wrap items-center gap-2"><span class="text-amber-700 dark:text-amber-300 font-medium">${escapeHtml(c.citizen_value)}</span><button type="button" class="inline-upload-trigger px-2.5 py-1 rounded-lg bg-civic-navy text-white text-xs font-semibold hover:bg-civic-navyLight">Upload PDF</button></div>`
              : escapeHtml(c.citizen_value);
          return `
            <tr>
              <td class="py-2.5 pr-4 font-medium">${escapeHtml(c.criterion)}</td>
              <td class="py-2.5 pr-4">${escapeHtml(c.required)}</td>
              <td class="py-2.5 pr-4">${valHtml}</td>
              <td class="py-2.5"><span class="px-2 py-0.5 rounded-full text-xs font-semibold ${stCls}">${escapeHtml(c.status)}</span></td>
            </tr>`;
        })
        .join("");

      criteriaTbody.querySelectorAll(".inline-upload-trigger").forEach((btn) => {
        btn.addEventListener("click", () => inlineCitizenInput.click());
      });
    }

    // Available & Missing rows
    const rows = [];
    (data.available_documents || []).forEach((item) => {
      rows.push(`
        <tr>
          <td class="py-2.5 pr-4 font-medium">${escapeHtml(item.document)}</td>
          <td class="py-2.5 pr-4"><span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">Available</span></td>
          <td class="py-2.5 font-mono text-xs text-slate-600 dark:text-slate-300">${escapeHtml(item.supporting_filename)}</td>
        </tr>`);
    });
    (data.missing_documents || []).forEach((doc) => {
      rows.push(`
        <tr>
          <td class="py-2.5 pr-4 font-medium">${escapeHtml(doc)}</td>
          <td class="py-2.5 pr-4"><span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800">Missing</span></td>
          <td class="py-2.5 text-xs"><button type="button" class="inline-upload-trigger text-civic-saffron underline font-semibold">Upload ${escapeHtml(doc)}</button></td>
        </tr>`);
    });
    checklistTbody.innerHTML = rows.length
      ? rows.join("")
      : '<tr><td colspan="3" class="py-3 text-slate-400 italic">No explicit document checklist specified.</td></tr>';
    checklistTbody.querySelectorAll(".inline-upload-trigger").forEach((btn) => {
      btn.addEventListener("click", () => inlineCitizenInput.click());
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("scheme_id", schemeSelect.value);
    formData.append("language", getLanguage() === "hi" ? "hi" : "en");
    formData.append("use_sample_citizen", useSampleCheck.checked ? "true" : "false");
    if (schemeFile.files[0]) {
      formData.append("scheme_file", schemeFile.files[0]);
    } else {
      formData.append("clear_uploaded_scheme", "true");
    }

    const resp = await apiFetch("/api/eligibility", { method: "POST", body: formData });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Eligibility check failed.", "error");
      return;
    }
    renderResult(data);
    showToast("Eligibility evaluation complete.", "success");
  });

  async function downloadChecklist(format) {
    if (!lastResult) return;
    const resp = await apiFetch("/api/export/checklist", {
      method: "POST",
      body: JSON.stringify({ ...lastResult, format }),
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = format === "pdf" ? "scheme_eligibility_checklist.pdf" : "scheme_eligibility_checklist.md";
    a.click();
    URL.revokeObjectURL(url);
  }
  exportMdBtn.addEventListener("click", () => downloadChecklist("md"));
  exportPdfBtn.addEventListener("click", () => downloadChecklist("pdf"));
});
