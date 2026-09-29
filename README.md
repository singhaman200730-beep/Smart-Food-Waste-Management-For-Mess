# Smart Food Management System

A college mess/hostel food management system built around one real-world workflow:

**Attendance → ML prediction → Preparation recommendation → Meal service →
Unserved surplus + measured plate waste → Student reasons + ratings →
Analytics → AI explanation/recommendation → Staff final decision**

This is a complete rebuild (not phased): database, backend/API, ML, AI
explanation layer, student UI, and staff UI, all reconnected around a single
**meal/service event**.

## Product logic (read this before touching the code)

- **Attendance**: the official college/mess attendance system is the primary
  signal. A student's optional "I'm not eating this meal" is an *additional*
  signal only — it never replaces official attendance.
- **ML** predicts *diners*, not kilograms, using historical attendance +
  calendar context only (day of week, weekday/weekend, holiday, festival). It
  never trains on feedback counts, waste-report counts, or ratings. When
  there isn't enough history to train a model, the system says so and falls
  back to an honest average instead of faking confidence.
- **Preparation** is a *servings* recommendation (predicted diners + a safety
  buffer). The system never computes ingredient kilograms — the kitchen
  handles that from its own recipes. It prefers **today's actual recorded
  attendance** as the basis once it's known (it's ground truth for that
  specific meal), and only falls back to the ML prediction while attendance
  isn't recorded yet — staff can explicitly override which basis to use.
- **Waste** is two separate, measured things:
  - **Unserved surplus** = actual prepared − actual served (servings).
  - **Plate waste** = physically weighed kg, staff-entered from a scale
    reading (architecture is ready for a digital scale to post this
    automatically later — see `plate_waste` table).
- **Student waste reasons** are optional, behavioural, and never a substitute
  for the weighed kg. **Meal ratings** are separate again, and never
  directly move the attendance prediction.
- **Coverage** (how many students responded) is always shown separately from
  attendance — the system never implies that response count = attendance,
  and never assumes a non-responder had zero waste.
- **AI** only explains and recommends, from already-computed evidence (see
  `ai/explainer.py`). It never predicts attendance, never computes
  ingredient quantities, and never overrides the preparation figure — staff
  makes the final call.
- Out of scope by design: ingredient-level kg, preparation waste (peels,
  trimming, spoilage, cooking losses), and any manual festival-management UI
  beyond a simple `calendar_events` table.

## Architecture

- **Backend**: Flask + raw SQLite (no ORM) — deliberately simple so the
  whole data flow is easy to trace and explain in a viva.
- **ML**: scikit-learn `RandomForestRegressor`, trained fresh on each
  prediction from historical attendance + day-of-week/day-type features.
  Falls back to a historical average, then a generic default, when data is
  thin — and always says which one it used.
- **AI**: a deterministic, evidence-based explainer (`ai/explainer.py`) —
  works out of the box, no API key needed. It's structured so a real LLM
  call could be dropped in behind the same evidence bundle later (see
  "Extending the AI layer" below) without touching anything else.
- **Frontend**: server-rendered HTML + vanilla JS (Tailwind via CDN) — two
  dashboards (`/student`, `/staff`), no build step.
- **Auth**: Flask session cookies, `student`/`staff` roles, password hashing
  via Werkzeug.

### Data model

Everything hangs off `meals` (one row per date + meal_type). Attendance,
predictions, preparation, plate waste, waste reasons, and ratings are all
separate tables referencing `meal_id` — kept apart on purpose so they can
never be silently conflated. See `schema.sql` for the full model and the
comments explaining each table's role.

## Running it

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python seed.py --reset          # creates the DB + demo accounts + 70 days of history
                                 # (takes ~20-30s — it's genuinely hashing 120+ demo
                                 # passwords and training the ML model chronologically,
                                 # not a stalled process)
python app.py                   # http://localhost:5000
```

**Demo accounts** (created by `seed.py`):
- Staff: `staff1@mess.edu` / `staff123` (or `staff2@mess.edu`)
- Students: `student1@vit.edu` through `student120@vit.edu`, all with password `student123`
  (a pool this size is needed so feedback coverage percentages look like a real canteen's,
  rather than being capped at a handful of accounts)

You can also register new accounts from the login page.

### Try the acceptance scenario

1. Log in as staff, go to **Lunch** for today.
2. Note the ML-predicted diners and the recommended servings.
3. Enter today's official attendance, confirm the preparation quantity.
4. After the meal: enter actual prepared / actual served (unserved surplus
   appears automatically), and enter the weighed plate waste in kg.
5. Log in as a student (a different browser/incognito tab) and optionally
   submit a waste reason and a 1–5 rating for the same meal.
6. Back in staff view, refresh — the **AI explanation & recommendation**
   card updates using exactly that evidence.
7. Check the **Analytics** section for prediction accuracy, attendance
   trends, waste averages, and feedback coverage.

## Extending the AI layer

`ai/explainer.py` builds an `evidence` dict (prediction, preparation,
measured waste, ratings, coverage) and passes it to `explain(evidence)`,
which currently returns a templated explanation/recommendation. To use a
real LLM instead: keep `build_evidence()` exactly as is, and replace the
body of `explain()` with a call to your model of choice, prompting it with
the evidence dict and asking for the same two strings back. Keep the
current templated version as a fallback if the API call fails — the product
requirement is that the system must still work if the AI is unavailable.

## What's deliberately not built

- Ingredient-level (kg) calculations of any kind.
- Preparation-side waste (peels, trimming, spoilage, cooking losses).
- A manual festival/holiday management UI — `calendar_events` is a simple
  table staff can seed or extend directly; the seed script pre-populates a
  few examples.
- Hardware integration for the weighing scale — `plate_waste.weight_kg` is
  staff-entered today; the schema doesn't need to change for a scale to post
  to the same endpoint later.
