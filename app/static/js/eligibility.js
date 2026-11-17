/** Eligibility Checker UI logic */

document.addEventListener("DOMContentLoaded", () => {
  const { apiFetch, showToast, getLanguage, escapeHtml } = window.CitizenApp;

  const form = document.getElementById("eligibility-form");
  const schemeSelect = document.getElementById("scheme-select");
  const schemeFile = document.getElementById("scheme-file-input");
  const useSampleCheck = document.getElementById("use-sample-citizen");

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

  function renderResult(data) {
    lastResult = data;
    resultsWrap.classList.remove("hidden");
    resSchemeName.textContent = data.scheme_name;
    verdictBadge.textContent = data.rule_based_verdict;
    verdictBadge.className = `px-3 py-1 rounded-full text-xs font-bold ${badgeClass(data.rule_based_verdict)}`;
    aiText.textContent = data.ai_explanation || "";

    const facts = data.extracted_citizen_facts || {};
    const pills = [];
    if (facts.marks_percentage != null) pills.push(`Marks: ${facts.marks_percentage}%`);
    if (facts.cgpa != null) pills.push(`CGPA: ${facts.cgpa}`);
    if (facts.annual_income_inr != null) pills.push(`Income: INR ${Number(facts.annual_income_inr).toLocaleString("en-IN")}`);
    if (facts.age_years != null) pills.push(`Age: ${facts.age_years}`);
    if (facts.category) pills.push(`Category: ${facts.category}`);
    factsPills.innerHTML = pills.map((p) => `<span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800">${escapeHtml(p)}</span>`).join("");

    // Criteria rows
    if (!data.criteria_checks || data.criteria_checks.length === 0) {
      criteriaTbody.innerHTML = '<tr><td colspan="4" class="py-3 text-slate-400 italic">No numeric thresholds detected in scheme text.</td></tr>';
    } else {
      criteriaTbody.innerHTML = data.criteria_checks
        .map((c) => {
          const stCls = c.status === "PASS" ? "bg-emerald-100 text-emerald-800" : c.status === "FAIL" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800";
          return `
            <tr>
              <td class="py-2.5 pr-4 font-medium">${escapeHtml(c.criterion)}</td>
              <td class="py-2.5 pr-4">${escapeHtml(c.required)}</td>
              <td class="py-2.5 pr-4">${escapeHtml(c.citizen_value)}</td>
              <td class="py-2.5"><span class="px-2 py-0.5 rounded-full text-xs font-semibold ${stCls}">${escapeHtml(c.status)}</span></td>
            </tr>`;
        })
        .join("");
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
          <td class="py-2.5 text-xs text-slate-400 italic">Not found in uploaded files</td>
        </tr>`);
    });
    checklistTbody.innerHTML = rows.length ? rows.join("") : '<tr><td colspan="3" class="py-3 text-slate-400 italic">No explicit document checklist detected.</td></tr>';
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("scheme_id", schemeSelect.value);
    formData.append("language", getLanguage() === "hi" ? "hi" : "en");
    formData.append("use_sample_citizen", useSampleCheck.checked ? "true" : "false");
    if (schemeFile.files[0]) {
      formData.append("scheme_file", schemeFile.files[0]);
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
