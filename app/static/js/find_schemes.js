/* Full-screen Guided Find Schemes wizard, searchable States/UTs, live match counter & My List */
(function () {
  var lang = window.APP_LANG || "en";
  var i18n = window.APP_I18N || {};
  var wText = i18n.wizard || {};
  var allStates = (window.WIZARD_INITIAL && window.WIZARD_INITIAL.allStates) || ["Uttar Pradesh", "Delhi", "Bihar", "Maharashtra"];

  var state = {
    answers: Object.assign({}, (window.WIZARD_INITIAL && window.WIZARD_INITIAL.answers) || {}),
    checkedDocs: Object.assign({}, (window.WIZARD_INITIAL && window.WIZARD_INITIAL.checkedDocs) || {}),
    myList: JSON.parse(localStorage.getItem("citizen_my_list") || "[]"),
    stepIdx: 0,
    matches: []
  };

  function saveMyList() {
    localStorage.setItem("citizen_my_list", JSON.stringify(state.myList));
    var cnt = document.getElementById("myListCount");
    if (cnt) cnt.textContent = String(state.myList.length);
  }

  async function updateLiveCount() {
    var pill = document.getElementById("liveMatchPill");
    if (!pill) return;
    try {
      var res = await window.apiFetch("/api/scheme-preview-count", {
        method: "POST",
        body: JSON.stringify({ answers: state.answers })
      });
      var data = await res.json();
      if (res.ok && typeof data.matching_count === "number") {
        pill.textContent = lang === "hi"
          ? data.matching_count + " योजनाएँ मिल सकती हैं"
          : data.matching_count + " schemes may match so far";
      }
    } catch (_e) {}
  }

  function getSteps() {
    var isHi = lang === "hi";
    var steps = [
      {
        key: "state",
        title: wText.q_state || "Which state or Union Territory do you live in?",
        why: wText.why_state || "",
        type: "state_search",
        options: []
      },
      {
        key: "age",
        title: wText.q_age || "How old are you?",
        why: wText.why_age || "",
        type: "age",
        options: [
          { value: 16, label: isHi ? "18 वर्ष से कम (स्कूल)" : "Under 18 (School)" },
          { value: 21, label: isHi ? "18 से 25 वर्ष" : "18 to 25 years" },
          { value: 32, label: isHi ? "26 से 40 वर्ष" : "26 to 40 years" },
          { value: 50, label: isHi ? "41 से 59 वर्ष" : "41 to 59 years" },
          { value: 65, label: isHi ? "60 वर्ष या अधिक" : "60+ years (Senior)" }
        ]
      },
      {
        key: "occupation",
        title: wText.q_role || "Which best describes you?",
        why: wText.why_role || "",
        options: [
          { value: "student", label: isHi ? "छात्र / छात्रा (स्कूल या कॉलेज)" : "Student (School or College)" },
          { value: "farmer", label: isHi ? "किसान / खेतीहर" : "Farmer / Cultivator" },
          { value: "artisan", label: isHi ? "कारीगर / शिल्पकार" : "Artisan / Craftsperson" },
          { value: "worker", label: isHi ? "मज़दूर / असंगठित कामगार" : "Worker / Unorganised Labour" },
          { value: "entrepreneur", label: isHi ? "छोटा व्यापार / रेहड़ी-पटरी" : "Small Business / Street Vendor" },
          { value: "job_seeker", label: isHi ? "कौशल प्रशिक्षण / रोज़गार" : "Job Seeker / Skill Trainee" },
          { value: "homemaker", label: isHi ? "गृहिणी / महिला" : "Woman / Homemaker" },
          { value: "senior", label: isHi ? "वरिष्ठ नागरिक / सेवानिवृत्त" : "Senior Citizen / Retired" }
        ]
      },
      {
        key: "category",
        title: wText.q_category || "What is your social category?",
        why: wText.why_category || "",
        options: [
          { value: "General", label: isHi ? "सामान्य (General)" : "General" },
          { value: "OBC", label: "OBC" },
          { value: "SC", label: "SC" },
          { value: "ST", label: "ST" },
          { value: "EWS", label: "EWS" },
          { value: "Minority", label: isHi ? "अल्पसंख्यक (Minority)" : "Minority" }
        ]
      },
      {
        key: "gender",
        title: wText.q_gender || "Gender",
        why: wText.why_gender || "",
        options: [
          { value: "female", label: isHi ? "महिला" : "Female" },
          { value: "male", label: isHi ? "पुरुष" : "Male" },
          { value: "other", label: isHi ? "अन्य" : "Other" }
        ]
      },
      {
        key: "annual_income_inr",
        title: wText.q_income || "Approximate yearly family income",
        why: wText.why_income || "",
        options: [
          { value: 80000, label: isHi ? "₹1,00,000 तक" : "Up to ₹1,00,000" },
          { value: 200000, label: isHi ? "₹1,00,001 से ₹2,50,000" : "₹1,00,001 to ₹2,50,000" },
          { value: 400000, label: isHi ? "₹2,50,001 से ₹4,50,000" : "₹2,50,001 to ₹4,50,000" },
          { value: 750000, label: isHi ? "₹4,50,001 से ₹8,00,000" : "₹4,50,001 to ₹8,00,000" },
          { value: 1200000, label: isHi ? "₹8,00,000 से अधिक" : "Above ₹8,00,000" }
        ]
      }
    ];

    if (state.answers.occupation === "student") {
      steps.push({
        key: "education_level",
        title: wText.q_education || "Current education level",
        why: wText.why_education || "",
        options: [
          { value: "class_9_10", label: isHi ? "कक्षा 9–10 (प्री-मैट्रिक)" : "Class 9–10 (Pre-Matric)" },
          { value: "class_11_12", label: isHi ? "कक्षा 11–12 / डिप्लोमा" : "Class 11–12 / Diploma" },
          { value: "undergraduate", label: isHi ? "स्नातक / तकनीकी डिग्री (UG)" : "College / Degree (UG)" },
          { value: "postgraduate", label: isHi ? "स्नातकोत्तर (PG)" : "Postgraduate (PG)" }
        ]
      });
      steps.push({
        key: "marks_percent",
        title: wText.q_marks || "Latest exam marks percentage",
        why: wText.why_marks || "",
        options: [
          { value: 85, label: isHi ? "80% या अधिक" : "80% or above" },
          { value: 65, label: isHi ? "60% से 79%" : "60% to 79%" },
          { value: 52, label: isHi ? "50% से 59%" : "50% to 59%" },
          { value: 40, label: isHi ? "50% से कम" : "Below 50%" }
        ]
      });
    }

    steps.push({
      key: "has_disability",
      title: wText.q_disability || "Do you have a benchmark disability (UDID)?",
      why: wText.why_disability || "",
      options: [
        { value: false, label: isHi ? "नहीं" : "No" },
        { value: true, label: isHi ? "हाँ (40% या अधिक)" : "Yes (40% or above)" }
      ]
    });
    return steps;
  }

  function advanceOrFinish() {
    window.apiFetch("/api/wizard/save", {
      method: "POST",
      body: JSON.stringify({ answers: state.answers })
    });
    updateLiveCount();
    if (state.stepIdx < getSteps().length - 1) {
      state.stepIdx += 1;
      renderStep();
    } else {
      runMatch();
    }
  }

  function renderStep() {
    var steps = getSteps();
    if (state.stepIdx >= steps.length) state.stepIdx = steps.length - 1;
    if (state.stepIdx < 0) state.stepIdx = 0;
    var step = steps[state.stepIdx];

    document.getElementById("wizardStepLabel").textContent =
      (wText.step_of || "Step") + " " + (state.stepIdx + 1) + " / " + steps.length;
    document.getElementById("wizardProgressFill").style.width =
      Math.round(((state.stepIdx + 1) / steps.length) * 100) + "%";
    document.getElementById("wizardQuestionTitle").textContent = step.title;
    document.getElementById("wizardWhyAsk").textContent = step.why || "";

    var body = document.getElementById("wizardQuestionBody");
    body.innerHTML = "";

    if (step.type === "state_search") {
      var note = document.createElement("p");
      note.className = "alert-info";
      note.style.marginBottom = "12px";
      note.textContent = wText.state_note || "State schemes are currently covered for Uttar Pradesh; Central schemes apply to all states and UTs.";
      body.appendChild(note);

      var search = document.createElement("input");
      search.type = "search";
      search.id = "stateSearchInput";
      search.placeholder = lang === "hi" ? "अपना राज्य या केंद्र शासित प्रदेश खोजें..." : "Type to search your state or UT...";
      search.style.marginBottom = "12px";
      body.appendChild(search);

      var listWrap = document.createElement("div");
      listWrap.className = "option-grid cols-2";
      listWrap.style.maxHeight = "290px";
      listWrap.style.overflowY = "auto";
      body.appendChild(listWrap);

      var renderStates = function (filterText) {
        listWrap.innerHTML = "";
        var q = (filterText || "").trim().toLowerCase();
        var sorted = ["Uttar Pradesh"].concat(allStates.filter(function (s) { return s !== "Uttar Pradesh"; }));
        sorted.filter(function (s) { return !q || s.toLowerCase().includes(q); }).forEach(function (stName) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "option-pill" + (state.answers.state === stName ? " selected" : "");
          btn.innerHTML = "<span>" + stName + (stName === "Uttar Pradesh" ? " ★" : "") + "</span><span>" + (state.answers.state === stName ? "✓" : "") + "</span>";
          btn.addEventListener("click", function () {
            state.answers.state = stName;
            advanceOrFinish();
          });
          listWrap.appendChild(btn);
        });
      };
      renderStates("");
      search.addEventListener("input", function () { renderStates(search.value); });
    } else {
      var grid = document.createElement("div");
      grid.className = "option-grid" + (step.options.length > 3 ? " cols-2" : "");
      step.options.forEach(function (opt) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "option-pill" + (state.answers[step.key] === opt.value ? " selected" : "");
        btn.innerHTML = "<span>" + opt.label + "</span><span>" + (state.answers[step.key] === opt.value ? "✓" : "") + "</span>";
        btn.addEventListener("click", function () {
          state.answers[step.key] = opt.value;
          advanceOrFinish();
        });
        grid.appendChild(btn);
      });
      body.appendChild(grid);

      if (step.type === "age") {
        var stepper = document.createElement("div");
        stepper.style.display = "flex";
        stepper.style.alignItems = "center";
        stepper.style.gap = "10px";
        stepper.style.marginTop = "16px";
        stepper.innerHTML =
          '<button type="button" id="ageDecBtn" class="btn btn-secondary btn-sm" aria-label="Decrease age">−</button>' +
          '<input id="ageExactInput" type="number" min="1" max="110" style="max-width:160px;text-align:center;" placeholder="' + (lang === "hi" ? "सही उम्र" : "Exact age") + '">' +
          '<button type="button" id="ageIncBtn" class="btn btn-secondary btn-sm" aria-label="Increase age">+</button>';
        body.appendChild(stepper);
        var ageInp = stepper.querySelector("#ageExactInput");
        if (state.answers.age) ageInp.value = state.answers.age;
        stepper.querySelector("#ageDecBtn").addEventListener("click", function () {
          var v = Math.max(1, (parseInt(ageInp.value || "20", 10) || 20) - 1);
          ageInp.value = v;
          state.answers.age = v;
          updateLiveCount();
        });
        stepper.querySelector("#ageIncBtn").addEventListener("click", function () {
          var v = Math.min(110, (parseInt(ageInp.value || "20", 10) || 20) + 1);
          ageInp.value = v;
          state.answers.age = v;
          updateLiveCount();
        });
        ageInp.addEventListener("change", function () {
          var v = parseInt(ageInp.value, 10);
          if (v > 0 && v < 120) { state.answers.age = v; updateLiveCount(); }
        });
      }
    }

    document.getElementById("wizardBackBtn").disabled = state.stepIdx === 0;
    document.getElementById("wizardNextBtn").textContent =
      state.stepIdx === steps.length - 1 ? (wText.see_results || "See matching schemes") : (wText.next || "Next");
    updateLiveCount();
  }

  function renderMyListDrawer() {
    var drawer = document.getElementById("myListDrawer");
    if (!drawer) return;
    if (!state.myList.length) {
      drawer.innerHTML = '<p class="muted" style="margin:0;">' + (lang === "hi" ? "आपकी सूची खाली है। किसी भी योजना कार्ड पर 'मेरी सूची में जोड़ें' दबाएँ।" : "Your list is empty. Tap 'Save to my list' on any scheme card.") + "</p>";
      return;
    }
    var items = state.matches.filter(function (m) { return state.myList.indexOf(m.id) !== -1; });
    drawer.innerHTML = "<h3>" + (lang === "hi" ? "मेरी सहेजी गई योजनाएँ" : "My saved schemes") + " (" + items.length + ")</h3>" +
      items.map(function (m) {
        var totalDocs = (m.required_documents || []).length;
        var readyDocs = (state.checkedDocs[m.id] || []).length;
        var name = lang === "hi" ? (m.name_hi || m.name) : m.name;
        return '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);gap:10px;">' +
          '<div><strong>' + name + '</strong><div class="muted" style="font-size:0.86rem;">' + readyDocs + " / " + totalDocs + (lang === "hi" ? " दस्तावेज़ तैयार" : " documents ready") + "</div></div>" +
          '<a href="' + m.official_url + '" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">' + (wText.official_site || "Official site") + "</a></div>";
      }).join("");
  }

  function renderSchemeCard(m) {
    var isHi = lang === "hi";
    var name = isHi ? (m.name_hi || m.name) : m.name;
    var benefit = isHi ? (m.benefit_hi || m.benefit) : m.benefit;
    var who = isHi ? (m.who_hi || m.who) : m.who;
    var card = document.createElement("article");
    card.className = "card";

    var badgeClass = m.group === "qualify" ? "badge-qualify" : (m.group === "check" ? "badge-check" : "badge-not");
    var badgeLabel = m.group === "qualify" ? (wText.group_qualify || "Top match") : (m.group === "check" ? (wText.group_check || "Check these too") : (wText.group_not || "Not for you right now"));

    var checkedSet = new Set(state.checkedDocs[m.id] || []);
    var availSet = new Set((m.available_documents || []).map(function (d) { return d.document; }));
    var totalDocs = (m.required_documents || []).length;
    var readyCount = (m.required_documents || []).filter(function (d) { return checkedSet.has(d) || availSet.has(d); }).length;

    var checklistHtml = (m.required_documents || []).map(function (docName) {
      var isChecked = checkedSet.has(docName) || availSet.has(docName);
      return (
        '<label class="check-item">' +
        '<input type="checkbox" data-scheme="' + m.id + '" value="' + docName.replace(/"/g, "&quot;") + '" ' + (isChecked ? "checked" : "") + ">" +
        "<span>" + docName + (availSet.has(docName) ? " ✓" : "") + "</span></label>"
      );
    }).join("");

    var stepsHtml = (m.how_to_apply_steps || []).map(function (st) { return "<li>" + st + "</li>"; }).join("");
    var whyFits = (m.reasons_pass && m.reasons_pass.length) ? ("✓ " + m.reasons_pass[0]) : (who || "");
    var blocker = (m.reasons_fail && m.reasons_fail.length) ? ("✕ " + m.reasons_fail[0]) : ((m.reasons_unknown && m.reasons_unknown.length) ? ("• " + m.reasons_unknown[0]) : "");
    var isSaved = state.myList.indexOf(m.id) !== -1;
    var waText = encodeURIComponent(name + " — " + benefit + "\n" + (m.official_url || ""));

    card.innerHTML =
      '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">' +
      '<span class="badge ' + badgeClass + '">' + badgeLabel + "</span>" +
      '<span class="badge cat-bg-' + (m.category || "scholarships") + '">' + (m.category || "") + "</span>" +
      "</div>" +
      '<h3 style="margin-bottom:4px;"><a href="/schemes/' + encodeURIComponent(m.slug || m.id) + '">' + name + "</a></h3>" +
      '<div class="benefit-figure">' + benefit + "</div>" +
      '<p style="font-size:0.92rem;margin-bottom:4px;">' + whyFits + "</p>" +
      (blocker ? '<p class="muted" style="font-size:0.9rem;margin-bottom:8px;">' + blocker + "</p>" : "") +
      '<div class="chip-row">' +
      '<span class="elig-chip doc-progress-chip">' + readyCount + " / " + totalDocs + (isHi ? " दस्तावेज़ तैयार" : " docs ready") + "</span>" +
      '<span class="elig-chip">' + (wText.last_verified || "Last verified") + ": " + (m.last_verified || "") + "</span>" +
      "</div>" +
      '<details style="margin-top:8px;"><summary style="font-weight:600;cursor:pointer;">' + (wText.doc_checklist || "Document checklist") + "</summary>" +
      '<div style="margin-top:8px;">' + checklistHtml + "</div></details>" +
      '<details style="margin-top:8px;"><summary style="font-weight:600;cursor:pointer;">' + (wText.how_to_apply || "How to apply") + "</summary>" +
      '<ol style="margin:8px 0 0;padding-left:20px;">' + stepsHtml + "</ol></details>" +
      '<div class="btn-row" style="margin-top:14px;">' +
      '<a href="' + m.official_url + '" target="_blank" rel="noopener noreferrer" class="btn btn-cta btn-sm">' + (wText.official_site || "Official website") + "</a>" +
      '<button type="button" class="btn btn-secondary btn-sm save-list-btn">' + (isSaved ? (isHi ? "सहेजा गया ✓" : "Saved ✓") : (isHi ? "मेरी सूची में जोड़ें" : "Save to my list")) + "</button>" +
      '<button type="button" class="btn btn-secondary btn-sm pdf-checklist-btn">' + (wText.download_pdf || "Print / PDF") + "</button>" +
      '<a href="/ask?scheme=' + encodeURIComponent(m.slug || m.id) + '" class="btn btn-secondary btn-sm">' + (wText.ask_sahayak || "Ask Sahayak") + "</a>" +
      '<a href="https://wa.me/?text=' + waText + '" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">' + (wText.share_whatsapp || "WhatsApp") + "</a>" +
      "</div>";

    card.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
      cb.addEventListener("change", function () {
        var list = [];
        card.querySelectorAll('input[type="checkbox"]:checked').forEach(function (c) { list.push(c.value); });
        state.checkedDocs[m.id] = list;
        var chip = card.querySelector(".doc-progress-chip");
        if (chip) chip.textContent = list.length + " / " + totalDocs + (isHi ? " दस्तावेज़ तैयार" : " docs ready");
        window.apiFetch("/api/wizard/checklist", {
          method: "POST",
          body: JSON.stringify({ scheme_id: m.id, checked: list })
        });
        renderMyListDrawer();
      });
    });

    card.querySelector(".save-list-btn").addEventListener("click", function () {
      var idx = state.myList.indexOf(m.id);
      if (idx === -1) {
        state.myList.push(m.id);
        this.textContent = isHi ? "सहेजा गया ✓" : "Saved ✓";
      } else {
        state.myList.splice(idx, 1);
        this.textContent = isHi ? "मेरी सूची में जोड़ें" : "Save to my list";
      }
      saveMyList();
      renderMyListDrawer();
    });

    card.querySelector(".pdf-checklist-btn").addEventListener("click", async function () {
      var resp = await window.apiFetch("/api/export/checklist", {
        method: "POST",
        body: JSON.stringify({
          name: name, benefit: benefit, official_url: m.official_url,
          required_documents: m.required_documents || [],
          checked: state.checkedDocs[m.id] || [],
          how_to_apply_steps: m.how_to_apply_steps || []
        })
      });
      if (!resp.ok) return;
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = (m.slug || m.id) + "_checklist.pdf";
      a.click();
      URL.revokeObjectURL(url);
    });

    return card;
  }

  async function runMatch() {
    var resp = await window.apiFetch("/api/scheme-match", {
      method: "POST",
      body: JSON.stringify({ answers: state.answers, lang: lang })
    });
    var data = await resp.json();
    if (!resp.ok) {
      window.showToast(data.error || "Could not match schemes.");
      return;
    }
    state.matches = data.matches || [];
    if (data.checked_docs) state.checkedDocs = data.checked_docs;

    document.getElementById("wizardFullscreen").classList.remove("wizard-fullscreen");
    document.getElementById("wizardContainer").style.display = "none";
    document.getElementById("wizardResults").style.display = "block";
    document.getElementById("stateScopeNote").style.display =
      state.answers.state && state.answers.state !== "Uttar Pradesh" ? "block" : "none";

    var qList = document.getElementById("groupQualifyList");
    var cList = document.getElementById("groupCheckList");
    var nList = document.getElementById("groupNotList");
    qList.innerHTML = ""; cList.innerHTML = ""; nList.innerHTML = "";

    var qualifyCount = 0, checkCount = 0, notCount = 0;
    state.matches.forEach(function (m) {
      var el = renderSchemeCard(m);
      if (m.group === "qualify") { qList.appendChild(el); qualifyCount += 1; }
      else if (m.group === "check") { cList.appendChild(el); checkCount += 1; }
      else { nList.appendChild(el); notCount += 1; }
    });

    var fitTotal = qualifyCount + checkCount;
    document.getElementById("resultsHeadline").textContent = lang === "hi"
      ? fitTotal + " योजनाएँ आपके लिए उपयुक्त हो सकती हैं। इन 3 से शुरू करें:"
      : fitTotal + " schemes may fit you. Start with these 3:";

    document.getElementById("resultsSummaryBadges").innerHTML =
      '<span class="badge badge-qualify">' + (wText.group_qualify || "Top matches") + ": " + qualifyCount + "</span>" +
      '<span class="badge badge-check">' + (wText.group_check || "Check these too") + ": " + checkCount + "</span>" +
      '<span class="badge badge-not">' + (wText.group_not || "Not for you") + ": " + notCount + "</span>";

    var missingPrompt = document.getElementById("missingFieldPrompt");
    if (!state.answers.annual_income_inr && checkCount > 0) {
      missingPrompt.style.display = "block";
      missingPrompt.textContent = lang === "hi"
        ? "आय की जानकारी जोड़ें ताकि हम " + checkCount + " और योजनाओं की पक्की जाँच कर सकें।"
        : "Tell us your yearly family income to confirm " + checkCount + " more schemes.";
    } else {
      missingPrompt.style.display = "none";
    }
    saveMyList();
    renderMyListDrawer();
  }

  document.addEventListener("DOMContentLoaded", function () {
    saveMyList();
    document.getElementById("wizardBackBtn").addEventListener("click", function () {
      if (state.stepIdx > 0) { state.stepIdx -= 1; renderStep(); }
    });
    document.getElementById("wizardSkipBtn").addEventListener("click", function () {
      var steps = getSteps();
      delete state.answers[steps[state.stepIdx].key];
      advanceOrFinish();
    });
    document.getElementById("wizardNextBtn").addEventListener("click", function () {
      advanceOrFinish();
    });
    document.getElementById("wizardStartOverBtn").addEventListener("click", function () {
      state.answers = {};
      state.stepIdx = 0;
      document.getElementById("wizardResults").style.display = "none";
      document.getElementById("wizardContainer").style.display = "block";
      document.getElementById("wizardFullscreen").classList.add("wizard-fullscreen");
      renderStep();
    });
    document.getElementById("toggleNotEligibleBtn").addEventListener("click", function () {
      var list = document.getElementById("groupNotList");
      var showing = list.style.display !== "none";
      list.style.display = showing ? "none" : "grid";
      this.textContent = showing ? (wText.show_not || "Show schemes that don't match") : (wText.hide_not || "Hide schemes that don't match");
    });
    document.getElementById("myListToggleBtn").addEventListener("click", function () {
      var d = document.getElementById("myListDrawer");
      d.style.display = d.style.display === "none" ? "block" : "none";
    });

    if (window.WIZARD_INITIAL && window.WIZARD_INITIAL.autoResults) {
      runMatch();
    } else {
      renderStep();
    }
  });
})();
