let ME = null;

async function boot() {
  try {
    ME = await API.get("/api/auth/me");
    if (ME.role !== "student") { window.location.href = "/staff"; return; }
    document.getElementById("userLine").textContent = `${ME.name} · Student`;
  } catch (e) {
    window.location.href = "/";
    return;
  }
  await loadTodayMeals();
  await loadHistory();
}

async function logout() {
  try { await API.post("/api/auth/logout"); } catch (e) {}
  window.location.href = "/";
}

function mealIcon(type) {
  return { breakfast: "🌅", lunch: "🍛", dinner: "🌙" }[type] || "🍽️";
}

async function loadTodayMeals() {
  const container = document.getElementById("mealCards");
  container.innerHTML = MEAL_TYPES.map(() =>
    `<div class="card p-5"><div class="skeleton h-24"></div></div>`
  ).join("");

  const details = {};
  for (const type of MEAL_TYPES) {
    try {
      details[type] = await API.get(`/api/meals/today?meal_type=${type}`);
    } catch (e) {
      details[type] = null;
    }
  }

  container.innerHTML = MEAL_TYPES.map(type => renderMealCard(type, details[type])).join("");

  MEAL_TYPES.forEach(type => {
    const d = details[type];
    if (!d) return;
    const optBtn = document.getElementById(`optout-${type}`);
    if (optBtn) optBtn.addEventListener("click", () => toggleOptOut(type, d.meal.id, !d.you.opted_out));

    const reasonSelect = document.getElementById(`reason-${type}`);
    if (reasonSelect) reasonSelect.addEventListener("change", (e) => submitReason(type, d.meal.id, e.target.value));

    document.querySelectorAll(`.star-${type}`).forEach(star => {
      star.addEventListener("click", () => submitRating(type, d.meal.id, parseInt(star.dataset.value, 10)));
    });
  });
}

function renderMealCard(type, d) {
  if (!d) {
    return `<div class="card p-5 text-sm text-gray-400">${capitalize(type)} unavailable right now.</div>`;
  }
  const menu = d.meal.menu_note ? `<p class="text-sm text-gray-600 mt-1">${escapeHtml(d.meal.menu_note)}</p>`
    : `<p class="text-sm text-gray-400 mt-1 italic">Menu not posted yet</p>`;

  const optedOut = d.you.opted_out;
  const optBtnLabel = optedOut ? "✓ You're skipping this meal" : "I'm not eating this meal";
  const optBtnClass = optedOut ? "btn-primary w-full text-sm" : "btn-secondary w-full text-sm";

  const reasonOptions = Object.entries(REASON_LABELS).map(([val, label]) =>
    `<option value="${val}" ${d.you.waste_reason === val ? "selected" : ""}>${label}</option>`
  ).join("");

  const rating = d.you.rating || 0;
  const stars = [1, 2, 3, 4, 5].map(n =>
    `<button class="star-${type} text-2xl leading-none" data-value="${n}">${n <= rating ? "★" : "☆"}</button>`
  ).join("");

  return `
    <div class="card p-5 flex flex-col gap-4">
      <div>
        <div class="flex items-center justify-between">
          <div class="font-bold text-gray-900">${mealIcon(type)} ${capitalize(type)}</div>
          <span class="pill pill-gray">${d.meal.date}</span>
        </div>
        ${menu}
      </div>

      <button id="optout-${type}" class="${optBtnClass}">${optBtnLabel}</button>

      <div>
        <label class="text-xs font-semibold text-gray-600">Why did you leave food? (optional)</label>
        <select id="reason-${type}">
          <option value="">— Not applicable / skip —</option>
          ${reasonOptions}
        </select>
      </div>

      <div>
        <label class="text-xs font-semibold text-gray-600 block mb-1">Rate this meal (optional)</label>
        <div class="flex gap-1">${stars}</div>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

async function toggleOptOut(type, mealId, wantOptOut) {
  try {
    if (wantOptOut) await API.post(`/api/meals/${mealId}/opt-out`);
    else await API.del(`/api/meals/${mealId}/opt-out`);
    toast(wantOptOut ? "Marked as skipping this meal" : "Opt-out removed");
    await loadTodayMeals();
  } catch (e) { toast(e.message, true); }
}

async function submitReason(type, mealId, reason) {
  if (!reason) return;
  try {
    await API.post(`/api/meals/${mealId}/waste-reason`, { reason });
    toast("Thanks — feedback recorded");
  } catch (e) { toast(e.message, true); }
}

async function submitRating(type, mealId, rating) {
  try {
    await API.post(`/api/meals/${mealId}/rating`, { rating });
    toast("Thanks for rating this meal");
    await loadTodayMeals();
  } catch (e) { toast(e.message, true); }
}

async function loadHistory() {
  const tbody = document.getElementById("historyBody");
  try {
    const to = todayISO();
    const from = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const meals = await API.get(`/api/meals?from=${from}&to=${to}`);
    if (!meals.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-6 text-center text-gray-400">No recent meals recorded yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = meals.map(m => `
      <tr class="border-b border-gray-50">
        <td class="px-4 py-2">${m.date}</td>
        <td class="px-4 py-2">${mealIcon(m.meal_type)} ${capitalize(m.meal_type)}</td>
        <td class="px-4 py-2">${m.official_count ?? "—"}</td>
        <td class="px-4 py-2">${m.plate_waste_kg != null ? m.plate_waste_kg + " kg" : "—"}</td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-6 text-center text-red-500">Could not load history.</td></tr>`;
  }
}

boot();
