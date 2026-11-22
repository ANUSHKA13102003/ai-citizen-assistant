/* My Documents: upload, auto-fill from profile.fields, green Found cards & privacy reassurance */
(function () {
  var lang = window.APP_LANG || "en";
  var i18n = window.APP_I18N || {};
  var dText = i18n.docs || {};
  var state = {
    docs: (window.DOCS_INITIAL && window.DOCS_INITIAL.docs) || [],
    insights: (window.DOCS_INITIAL && window.DOCS_INITIAL.insights) || [],
    profile: (window.DOCS_INITIAL && window.DOCS_INITIAL.profile) || {},
    summary: (window.DOCS_INITIAL && window.DOCS_INITIAL.summary) || null,
    redactedCounts: {}
  };

  function getFieldVal(key) {
    var fields = (state.profile && state.profile.fields) || {};
    return fields[key] ? fields[key].value : "";
  }

  function renderRedactionChip() {
    var chip = document.getElementById("privacyRedactionChip");
    if (!chip) return;
    if (!state.docs.length) {
      chip.style.display = "none";
      return;
    }
    var c = state.redactedCounts || {};
    var idCount = (c.aadhaar || 0) + (c.pan || 0) + (c.bank_account || 0);
    var phoneCount = (c.phone || 0) + (c.email || 0);
    chip.style.display = "inline-flex";
    if (idCount + phoneCount > 0) {
      chip.textContent = lang === "hi"
        ? "पढ़ने से पहले " + idCount + " ID नंबर और " + phoneCount + " फ़ोन/ईमेल छिपाए गए"
        : "We hid " + idCount + " ID number(s) and " + phoneCount + " phone/email(s) before reading";
    } else {
      chip.textContent = lang === "hi"
        ? "गोपनीयता सुरक्षित: कोई ID या फ़ोन नंबर AI को नहीं भेजा गया"
        : "Privacy check passed: personal IDs & phones are hidden automatically before AI reading";
    }
  }

  function renderDocs() {
    var list = document.getElementById("uploadedDocsList");
    list.innerHTML = "";
    state.docs.forEach(function (d) {
      var item = document.createElement("div");
      item.className = "card-soft";
      item.style.display = "flex";
      item.style.justifyContent = "space-between";
      item.style.alignItems = "center";
      item.style.flexWrap = "wrap";
      item.style.gap = "10px";
      item.innerHTML =
        "<div><strong>" + d.filename + "</strong> " +
        '<span class="badge badge-qualify">' + (d.doc_type_label || "Document") + " ✓</span>" +
        '<div class="muted" style="font-size:0.88rem;">' + d.extracted_pages + " / " + d.total_pages + " pages read</div></div>" +
        '<button type="button" class="btn btn-secondary btn-sm view-doc-btn">' + (dText.see_where || "See where") + "</button>";
      item.querySelector(".view-doc-btn").addEventListener("click", function () {
        window.openPageViewer(d.filename, 1, "");
      });
      list.appendChild(item);
    });
    renderRedactionChip();
  }

  function renderProfile() {
    var fields = (state.profile && state.profile.fields) || {};
    var docTypes = (state.profile && state.profile.doc_types) || [];

    var mapInputs = {
      state: "pfState",
      age: "pfAge",
      occupation: "pfOccupation",
      category: "pfCategory",
      gender: "pfGender",
      annual_income_inr: "pfIncome",
      marks_percent: "pfMarks",
      education_level: "pfEdu"
    };
    Object.keys(mapInputs).forEach(function (k) {
      var el = document.getElementById(mapInputs[k]);
      var val = getFieldVal(k);
      if (el && val !== null && val !== undefined && val !== "") {
        el.value = String(val);
      }
    });

    // Green "Found" cards
    var foundGrid = document.getElementById("foundCardsGrid");
    foundGrid.innerHTML = "";
    Object.keys(fields).forEach(function (k) {
      var f = fields[k];
      if (!f || f.value === null || f.value === undefined || f.value === "") return;
      var card = document.createElement("div");
      card.className = "card-found";
      card.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">' +
        '<div><span class="badge badge-qualify">' + (lang === "hi" ? "मिला ✓" : "Found ✓") + "</span>" +
        '<div style="font-weight:700;margin-top:6px;">' + (f.label || k) + ": " + (f.display || f.value) + "</div>" +
        (f.filename ? '<div class="muted" style="font-size:0.84rem;">' + f.filename + " (p. " + (f.page || 1) + ")</div>" : "") +
        "</div>" +
        '<div style="display:flex;gap:6px;">' +
        (f.filename ? '<button type="button" class="btn btn-secondary btn-sm see-where-btn">' + (dText.see_where || "See where") + "</button>" : "") +
        (mapInputs[k] ? '<button type="button" class="btn btn-secondary btn-sm edit-pencil-btn" aria-label="Edit ' + (f.label || k) + '">✎</button>' : "") +
        "</div></div>";
      var sw = card.querySelector(".see-where-btn");
      if (sw) {
        sw.addEventListener("click", function () {
          window.openPageViewer(f.filename, f.page || 1, String(f.value));
        });
      }
      var ep = card.querySelector(".edit-pencil-btn");
      if (ep) {
        ep.addEventListener("click", function () {
          var det = document.getElementById("manualEditDetails");
          if (det) det.open = true;
          var target = document.getElementById(mapInputs[k]);
          if (target) { target.focus(); target.scrollIntoView({ behavior: "smooth", block: "center" }); }
        });
      }
      foundGrid.appendChild(card);
    });

    // Missing document hints ONLY for genuinely missing documents
    var hasMarksheet = docTypes.indexOf("marksheet") !== -1 || Boolean(fields.marks_percent);
    var hasIncome = docTypes.indexOf("income_certificate") !== -1 || Boolean(fields.annual_income_inr);
    var hints = [];
    if (!hasMarksheet) {
      hints.push('<span class="badge badge-check">' + (dText.missing_marks_hint || "Marksheet not uploaded yet — upload one to check marks-based scholarships.") + "</span>");
    }
    if (!hasIncome) {
      hints.push('<span class="badge badge-check">' + (dText.missing_income_hint || "Income certificate not uploaded yet — upload one to check income limits.") + "</span>");
    }
    document.getElementById("missingDocHints").innerHTML = hints.length
      ? '<div style="display:flex;flex-wrap:wrap;gap:8px;">' + hints.join("") + "</div>"
      : "";
  }

  function renderSummary(summary) {
    var box = document.getElementById("summaryOutput");
    if (!summary || !summary.sections) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    var html = '<div class="grid-2">';
    summary.sections.forEach(function (sec) {
      html += '<div class="card-soft"><h3>' + sec.label + '</h3><p style="white-space:pre-line;margin:0;">' + sec.content + "</p></div>";
    });
    html += "</div>";
    html += '<div class="btn-row" style="margin-top:14px;">' +
      '<button type="button" id="exportMdBtn" class="btn btn-secondary btn-sm">Download Markdown</button>' +
      '<button type="button" id="exportPdfBtn" class="btn btn-secondary btn-sm">Download PDF</button>' +
      "</div>";
    box.innerHTML = html;
    document.getElementById("exportMdBtn").addEventListener("click", function () { exportSummary("md", summary); });
    document.getElementById("exportPdfBtn").addEventListener("click", function () { exportSummary("pdf", summary); });
  }

  async function exportSummary(fmt, summary) {
    var resp = await window.apiFetch("/api/export/summary", {
      method: "POST",
      body: JSON.stringify({ format: fmt, sections: summary.sections, sources: summary.sources || [] })
    });
    if (!resp.ok) return;
    var blob = await resp.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "citizen_document_summary." + fmt;
    a.click();
    URL.revokeObjectURL(url);
  }

  function advanceToStep2() {
    var s2 = document.getElementById("step2Section");
    if (s2) s2.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    var status = document.getElementById("uploadStatusText");
    status.textContent = lang === "hi" ? "फ़ाइलें पढ़ी जा रही हैं..." : "Scanning files...";
    var fd = new FormData();
    for (var i = 0; i < fileList.length; i++) fd.append("files", fileList[i]);
    var resp = await window.apiFetch("/api/upload", { method: "POST", body: fd });
    var data = await resp.json();
    status.textContent = "";
    if (!resp.ok) {
      window.showToast(data.error || "Upload failed.");
      return;
    }
    if (data.duplicates && data.duplicates.length) {
      window.showToast("Already uploaded: " + data.duplicates.join(", "));
    } else {
      window.showToast(lang === "hi" ? "दस्तावेज़ पढ़े गए!" : "Documents read successfully.");
    }
    state.docs = data.documents || [];
    state.insights = data.insights || [];
    state.profile = data.profile || {};
    state.redactedCounts = data.redacted_counts || {};
    renderDocs();
    renderProfile();
    advanceToStep2();
  }

  function collectOverrides() {
    var form = document.getElementById("profileDetailsForm");
    var fd = new FormData(form);
    var out = {};
    fd.forEach(function (val, key) {
      out[key] = val ? String(val).trim() : "";
    });
    return out;
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderDocs();
    renderProfile();
    if (state.summary) renderSummary(state.summary);

    var docInput = document.getElementById("docFileInput");
    var camInput = document.getElementById("cameraFileInput");
    var dropzone = document.getElementById("docDropzone");

    docInput.addEventListener("change", function () { uploadFiles(docInput.files); docInput.value = ""; });
    camInput.addEventListener("change", function () { uploadFiles(camInput.files); camInput.value = ""; });

    dropzone.addEventListener("dragover", function (e) { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", function () { dropzone.classList.remove("dragover"); });
    dropzone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      uploadFiles(e.dataTransfer.files);
    });

    document.getElementById("loadDemoDocsBtn").addEventListener("click", async function () {
      var resp = await window.apiFetch("/api/load-demo-docs", { method: "POST", body: JSON.stringify({}) });
      var data = await resp.json();
      if (!resp.ok) {
        window.showToast(data.error || "Could not load sample documents.");
        return;
      }
      state.docs = data.documents || [];
      state.insights = data.insights || [];
      state.profile = data.profile || {};
      state.redactedCounts = data.redacted_counts || {};
      renderDocs();
      renderProfile();
      advanceToStep2();
      window.showToast(lang === "hi" ? "नमूना दस्तावेज़ लोड हो गए।" : "Sample documents loaded.");
    });

    document.getElementById("saveAndFindBtn").addEventListener("click", async function () {
      var overrides = collectOverrides();
      await window.apiFetch("/api/profile/override", {
        method: "POST",
        body: JSON.stringify({ overrides: overrides })
      });
      await window.apiFetch("/api/wizard/save", {
        method: "POST",
        body: JSON.stringify({ answers: overrides })
      });
      window.location.href = "/find-schemes?results=1";
    });

    document.getElementById("summarizeDocsBtn").addEventListener("click", async function () {
      var btn = this;
      btn.disabled = true;
      var resp = await window.apiFetch("/api/summarize", {
        method: "POST",
        body: JSON.stringify({ language: lang })
      });
      btn.disabled = false;
      var data = await resp.json();
      if (!resp.ok) {
        window.showToast(data.error || "Please upload documents first.");
        return;
      }
      state.summary = data;
      renderSummary(data);
    });
  });
})();
