let ME = null;
let STATE = { date: todayISO(), mealType: "lunch" };

async function boot() {
  try {
    ME = await API.get("/api/auth/me");
    if (ME.role !== "staff") { window.location.href = "/student"; return; }
    document.getElementById("userLine").textContent = `${ME.name} · Mess staff`;
  } catch (e) {
    window.location.href = "/";
    return;
  }

  const dateInput = document.getElementById("dateInput");
  dateInput.value = STATE.date;
  dateInput.addEventListener("change", () => { STATE.date = dateInput.value; loadMeal(); });

  renderMealTypeTabs();
  document.getElementById("analyticsFilter").addEventListener("change", loadAnalytics);

  await loadMeal();
  await loadAnalytics();
}

async function logout() {
  try { await API.post("/api/auth/logout"); } catch (e) {}
  window.location.href = "/";
}

function renderMealTypeTabs() {
  const el = document.getElementById("mealTypeTabs");
  el.innerHTML = MEAL_TYPES.map(t =>
    `<button class="tab-btn ${t === STATE.mealType ? "active" : ""}" data-type="${t}">${mealIcon(t)} ${capitalize(t)}</button>`
  ).join("");
  el.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      STATE.mealType = btn.dataset.type;
      renderMealTypeTabs();
      loadMeal();
    });
  });
}

function mealIcon(type) {
  return { breakfast: "🌅", lunch: "🍛", dinner: "🌙" }[type] || "🍽️";
}

function dayTypePill(dayType) {
  const map = {
    normal: ["pill-gray", "Normal weekday"],
    weekend: ["pill-amber", "Weekend"],
    holiday: ["pill-red", "Holiday"],
    festival: ["pill-red", "Festival"],
  };
  const entry = map[dayType] || ["pill-gray", dayType];
  return `<span class="pill ${entry[0]}">${entry[1]}</span>`;
}

function methodPill(method) {
  const map = {
    ml_model: ["pill-green", "ML model prediction"],
    historical_average: ["pill-amber", "Historical average (limited data)"],
    fallback_default: ["pill-red", "Generic default (no data yet)"],
  };
  const entry = map[method] || ["pill-gray", method];
  return `<span class="pill ${entry[0]}">${entry[1]}</span>`;
}

let currentMealId = null;

async function loadMeal() {
  const section = document.getElementById("mealSection");
  section.innerHTML = `<div class="card p-6"><div class="skeleton h-40"></div></div>`;

  let d;
  try {
    d = await API.post("/api/meals", { date: STATE.date, meal_type: STATE.mealType });
  } catch (e) {
    section.innerHTML = `<div class="card p-6 text-red-600 text-sm">Could not load meal: ${e.message}</div>`;
    return;
  }
  currentMealId = d.meal.id;
  section.innerHTML = renderMealSection(d);
  attachMealHandlers(d);
  loadAiInsight(d.meal.id);
}

function renderMealSection(d) {
  const m = d.meal, ctx = d.calendar_context;
  const sg = d.suggestion;
  const prep = d.preparation;
  const surplus = (prep && prep.actual_prepared != null && prep.actual_served != null)
    ? prep.actual_prepared - prep.actual_served : null;

  return `
  <div class="space-y-4">
    <div class="card p-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div class="font-bold text-lg text-gray-900">${mealIcon(m.meal_type)} ${capitalize(m.meal_type)} — ${m.date}</div>
          <div class="flex gap-2 mt-1">${dayTypePill(ctx.day_type)}<span class="pill pill-gray">${ctx.weekday_name}</span></div>
        </div>
      </div>
      <div class="mt-3">
        <label class="text-xs font-semibold text-gray-600">Menu (shown to students)</label>
        <div class="flex gap-2 mt-1">
          <input id="menuNote" value="${(m.menu_note || "").replace(/"/g, "&quot;")}" placeholder="e.g. Rice, sambar, poriyal, curd">
          <button id="saveMenu" class="btn-secondary text-sm whitespace-nowrap">Save</button>
        </div>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">Attendance</div>
        <p class="text-xs text-gray-500 mb-3">Official count from the college/mess attendance system — the primary demand signal.</p>
        <div class="flex gap-2">
          <input id="attendanceInput" type="number" min="0" step="1" value="${d.attendance ? d.attendance.official_count : ""}" placeholder="e.g. 470">
          <button id="saveAttendance" class="btn-primary text-sm whitespace-nowrap">Save</button>
        </div>
        <div class="text-xs text-gray-500 mt-2">${d.opt_out_count} student(s) marked "not eating" (additional signal only).</div>
      </div>

      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">ML attendance prediction</div>
        <div class="text-3xl font-extrabold text-gray-900">${d.prediction.predicted_diners}</div>
        <div class="mt-2">${methodPill(d.prediction.method)}</div>
        <p class="text-xs text-gray-500 mt-2">${d.prediction.confidence_note}</p>
      </div>
    </div>

    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-2">Preparation (servings)</div>

      <div class="rounded-lg p-3 mb-3" style="background:#f0fdf4;border:1px solid #bbf7d0">
        <div class="text-xs font-semibold text-emerald-800 mb-1">Current suggestion</div>
        <div class="text-sm text-emerald-900">${sg.note}</div>
        <div class="grid gap-4 sm:grid-cols-3 text-sm mt-2">
          <div><div class="text-gray-500">${sg.basis === "attendance" ? "Attendance" : "Predicted diners"}</div><div class="font-bold text-lg">${sg.base_count}</div></div>
          <div><div class="text-gray-500">Safety buffer</div><div class="font-bold text-lg">+${sg.safety_buffer}</div></div>
          <div><div class="text-gray-500">Recommended</div><div class="font-bold text-lg">${sg.recommended_servings}</div></div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 mb-3 text-xs">
        <span class="text-gray-500 font-semibold">Confirm using:</span>
        <label class="flex items-center gap-1"><input type="radio" name="basisChoice" value="attendance" ${sg.basis === "attendance" ? "checked" : ""} ${!d.attendance ? "disabled" : ""}> Attendance (${d.attendance ? d.attendance.official_count : "not recorded yet"})</label>
        <label class="flex items-center gap-1"><input type="radio" name="basisChoice" value="prediction" ${sg.basis === "prediction" ? "checked" : ""}> ML prediction (${d.prediction.predicted_diners})</label>
      </div>

      ${prep ? `<div class="text-xs text-gray-500 mb-3">Last confirmed using <strong>${prep.basis}</strong> (${prep.base_count}) → ${prep.recommended_servings} servings recommended at that time.${prep.basis !== sg.basis || prep.base_count !== sg.base_count ? ' <span class="text-amber-600 font-semibold">A newer figure is available — reconfirm to update.</span>' : ''}</div>` : ""}

      <div class="flex gap-2 mb-4">
        <input id="confirmedInput" type="number" min="0" step="1" value="${prep && prep.confirmed_servings != null ? prep.confirmed_servings : sg.recommended_servings}" placeholder="Confirm/adjust servings">
        <button id="confirmPrep" class="btn-primary text-sm whitespace-nowrap">Confirm</button>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 border-t border-gray-100 pt-4">
        <div>
          <label class="text-xs font-semibold text-gray-600">Actual prepared</label>
          <input id="actualPrepared" type="number" min="0" step="1" value="${prep && prep.actual_prepared != null ? prep.actual_prepared : ""}" placeholder="after cooking">
        </div>
        <div>
          <label class="text-xs font-semibold text-gray-600">Actual served</label>
          <input id="actualServed" type="number" min="0" step="1" value="${prep && prep.actual_served != null ? prep.actual_served : ""}" placeholder="after service">
        </div>
      </div>
      <button id="saveActuals" class="btn-secondary text-sm mt-3">Save actuals</button>

      ${surplus != null ? `<div class="text-sm mt-3"><span class="pill pill-amber">Unserved surplus: ${surplus} servings</span></div>` : ""}
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">Plate waste (weighed)</div>
        <p class="text-xs text-gray-500 mb-3">Enter the reading from the weighing scale after collection.</p>
        <div class="flex gap-2">
          <input id="plateWasteInput" type="number" min="0" step="0.1" value="${d.plate_waste ? d.plate_waste.weight_kg : ""}" placeholder="kg">
          <button id="savePlateWaste" class="btn-primary text-sm whitespace-nowrap">Save</button>
        </div>
      </div>

      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">Feedback coverage</div>
        <div class="text-sm space-y-1">
          <div>Waste-reason responses: <strong>${d.waste_reasons_summary.total_responses}</strong>
            ${d.coverage.waste_reason_coverage_pct != null ? `<span class="text-gray-400">(${d.coverage.waste_reason_coverage_pct}% of attendance)</span>` : ""}</div>
          <div>Rating responses: <strong>${d.ratings_summary.count}</strong>
            ${d.coverage.rating_coverage_pct != null ? `<span class="text-gray-400">(${d.coverage.rating_coverage_pct}% of attendance)</span>` : ""}</div>
          <div class="text-xs text-gray-400 pt-1">Response counts are never treated as the full attendance figure.</div>
        </div>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">Meal ratings</div>
        ${d.ratings_summary.count ? `
          <div class="text-2xl font-extrabold text-gray-900 mb-2">${d.ratings_summary.avg_rating.toFixed(1)} / 5</div>
          ${[5, 4, 3, 2, 1].map(r => ratingBar(r, d.ratings_summary.distribution[r] || 0, d.ratings_summary.count)).join("")}
        ` : `<div class="text-sm text-gray-400">No ratings submitted yet.</div>`}
      </div>
      <div class="card p-5">
        <div class="font-bold text-gray-900 mb-2">Waste reasons</div>
        ${d.waste_reasons_summary.breakdown.length ? d.waste_reasons_summary.breakdown.map(r => `
          <div class="flex justify-between text-sm py-1 border-b border-gray-50 last:border-0">
            <span>${REASON_LABELS[r.reason] || r.reason}</span><span class="font-semibold">${r.count}</span>
          </div>
        `).join("") : `<div class="text-sm text-gray-400">No waste reasons submitted yet.</div>`}
      </div>
    </div>

    <div class="card p-5" id="aiCard">
      <div class="font-bold text-gray-900 mb-2">🤖 AI explanation & recommendation</div>
      <div class="skeleton h-16"></div>
    </div>
  </div>
  `;
}

function ratingBar(star, count, total) {
  const pct = total ? Math.round((count / total) * 100) : 0;
  return `
    <div class="flex items-center gap-2 text-xs mb-1">
      <span class="w-8 text-gray-500">${star}★</span>
      <div class="flex-1 bg-gray-100 rounded-full h-2"><div class="bg-emerald-600 h-2 rounded-full" style="width:${pct}%"></div></div>
      <span class="w-6 text-right text-gray-500">${count}</span>
    </div>
  `;
}

function attachMealHandlers(d) {
  const mealId = d.meal.id;

  document.getElementById("saveMenu").addEventListener("click", async () => {
    try {
      await API.post(`/api/meals/${mealId}/menu`, { menu_note: document.getElementById("menuNote").value });
      toast("Menu saved");
    } catch (e) { toast(e.message, true); }
  });

  document.getElementById("saveAttendance").addEventListener("click", async () => {
    const val = parseInt(document.getElementById("attendanceInput").value, 10);
    if (isNaN(val) || val < 0) { toast("Enter a valid attendance count", true); return; }
    try {
      await API.post(`/api/meals/${mealId}/attendance`, { official_count: val });
      toast("Attendance saved");
      await loadMeal();
    } catch (e) { toast(e.message, true); }
  });

  document.querySelectorAll('input[name="basisChoice"]').forEach(radio => {
    radio.addEventListener("change", () => {
      const count = radio.value === "attendance" ? d.attendance.official_count : d.prediction.predicted_diners;
      const buffer = Math.max(15, Math.round(count * 0.06));
      document.getElementById("confirmedInput").value = count + buffer;
    });
  });

  document.getElementById("confirmPrep").addEventListener("click", async () => {
    const raw = document.getElementById("confirmedInput").value;
    const basisChoice = document.querySelector('input[name="basisChoice"]:checked');
    const body = raw === "" ? {} : { confirmed_servings: parseInt(raw, 10) };
    if (basisChoice) body.basis = basisChoice.value;
    try {
      await API.post(`/api/meals/${mealId}/preparation/confirm`, body);
      toast("Preparation quantity confirmed");
      await loadMeal();
    } catch (e) { toast(e.message, true); }
  });

  document.getElementById("saveActuals").addEventListener("click", async () => {
    const prepVal = document.getElementById("actualPrepared").value;
    const servedVal = document.getElementById("actualServed").value;
    const body = {};
    if (prepVal !== "") body.actual_prepared = parseInt(prepVal, 10);
    if (servedVal !== "") body.actual_served = parseInt(servedVal, 10);
    try {
      await API.patch(`/api/meals/${mealId}/preparation`, body);
      toast("Actuals saved");
      await loadMeal();
    } catch (e) { toast(e.message, true); }
  });

  document.getElementById("savePlateWaste").addEventListener("click", async () => {
    const val = parseFloat(document.getElementById("plateWasteInput").value);
    if (isNaN(val) || val < 0) { toast("Enter a valid weight in kg", true); return; }
    try {
      await API.post(`/api/meals/${mealId}/plate-waste`, { weight_kg: val });
      toast("Plate waste recorded");
      await loadMeal();
    } catch (e) { toast(e.message, true); }
  });
}

async function loadAiInsight(mealId) {
  try {
    const insight = await API.get(`/api/meals/${mealId}/ai-insight`);
    const card = document.getElementById("aiCard");
    if (!card) return;
    card.innerHTML = `
      <div class="font-bold text-gray-900 mb-2">🤖 AI explanation & recommendation</div>
      <p class="text-sm text-gray-700 mb-3">${insight.explanation}</p>
      <div class="bg-emerald-50 border border-emerald-100 rounded-lg p-3 text-sm text-emerald-900">
        <strong>Recommendation:</strong> ${insight.recommendation}
      </div>
      <p class="text-xs text-gray-400 mt-2">Based only on recorded evidence for this meal. Staff makes the final call.</p>
    `;
  } catch (e) {
    const card = document.getElementById("aiCard");
    if (card) card.innerHTML = `<div class="font-bold text-gray-900 mb-2">🤖 AI explanation & recommendation</div><div class="text-sm text-red-500">Could not load AI insight.</div>`;
  }
}

async function loadAnalytics() {
  const grid = document.getElementById("analyticsGrid");
  grid.innerHTML = Array.from({ length: 6 }).map(() => `<div class="card p-5"><div class="skeleton h-20"></div></div>`).join("");

  const filter = document.getElementById("analyticsFilter").value;
  let a;
  try {
    a = await API.get(`/api/analytics/overview${filter ? "?meal_type=" + filter : ""}`);
  } catch (e) {
    grid.innerHTML = `<div class="card p-5 text-red-500 text-sm">Could not load analytics: ${e.message}</div>`;
    return;
  }

  const weekdayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const weekdayRows = Object.entries(a.attendance_by_weekday)
    .sort((x, y) => x[0] - y[0])
    .map(([dow, v]) => `<div class="flex justify-between text-sm py-0.5"><span>${weekdayNames[dow]}</span><span class="font-semibold">${v}</span></div>`)
    .join("") || `<div class="text-sm text-gray-400">No data yet.</div>`;

  const reasonRows = a.waste_reason_distribution.map(r =>
    `<div class="flex justify-between text-sm py-0.5"><span>${REASON_LABELS[r.reason] || r.reason}</span><span class="font-semibold">${r.count}</span></div>`
  ).join("") || `<div class="text-sm text-gray-400">No data yet.</div>`;

  const ratingRows = a.rating_distribution.map(r =>
    `<div class="flex justify-between text-sm py-0.5"><span>${r.rating}★</span><span class="font-semibold">${r.count}</span></div>`
  ).join("") || `<div class="text-sm text-gray-400">No data yet.</div>`;

  grid.innerHTML = `
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-1">Prediction accuracy</div>
      <div class="text-2xl font-extrabold">${a.prediction_accuracy.mean_absolute_error ?? "—"}</div>
      <div class="text-xs text-gray-500">avg. diners off per meal (MAE)${a.prediction_accuracy.mean_absolute_percentage_error != null ? `, ${a.prediction_accuracy.mean_absolute_percentage_error}% avg error` : ""}</div>
      <div class="text-xs text-gray-400 mt-1">${a.prediction_accuracy.sample_size} meal(s) compared</div>
    </div>
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-2">Attendance by weekday</div>
      ${weekdayRows}
    </div>
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-1">Unserved surplus</div>
      <div class="text-2xl font-extrabold">${a.unserved_surplus.average_servings ?? "—"}</div>
      <div class="text-xs text-gray-500">avg. servings prepared but not served (${a.unserved_surplus.sample_size} meals)</div>
    </div>
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-1">Plate waste</div>
      <div class="text-2xl font-extrabold">${a.plate_waste.average_kg ?? "—"} kg</div>
      <div class="text-xs text-gray-500">average measured plate waste (${a.plate_waste.sample_size} meals)</div>
    </div>
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-2">Waste reasons (overall)</div>
      ${reasonRows}
    </div>
    <div class="card p-5">
      <div class="font-bold text-gray-900 mb-2">Ratings (overall)</div>
      ${ratingRows}
      <div class="text-xs text-gray-400 mt-2 pt-2 border-t border-gray-50">
        Coverage — reasons: ${a.feedback_coverage.avg_waste_reason_coverage_pct ?? "—"}%,
        ratings: ${a.feedback_coverage.avg_rating_coverage_pct ?? "—"}% of attendance
      </div>
    </div>
  `;
}

boot();
