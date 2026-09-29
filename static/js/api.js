const API = {
  async _req(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const message = (data && data.error) || `Request failed (${res.status})`;
      throw new Error(message);
    }
    return data;
  },
  get(path) { return this._req("GET", path); },
  post(path, body) { return this._req("POST", path, body || {}); },
  patch(path, body) { return this._req("PATCH", path, body || {}); },
  del(path) { return this._req("DELETE", path); },
};

const MEAL_TYPES = ["breakfast", "lunch", "dinner"];

const REASON_LABELS = {
  portion_too_large: "Portion too large",
  disliked_taste: "Didn't like the taste",
  too_spicy: "Too spicy",
  food_quality: "Food quality",
  food_cold: "Food was cold",
  not_hungry: "Not hungry",
  other: "Other",
};

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function toast(msg, isError) {
  const el = document.getElementById("toast");
  if (!el) { console.log(msg); return; }
  el.textContent = msg;
  el.className = "fixed bottom-5 right-5 px-4 py-3 rounded-xl shadow-lg text-sm font-medium z-50 " +
    (isError ? "bg-red-600 text-white" : "bg-emerald-700 text-white");
  el.classList.remove("hidden");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
