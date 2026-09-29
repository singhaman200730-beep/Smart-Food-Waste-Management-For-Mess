-- Smart Food Management System — schema
-- Every operational fact connects to a meal/service event (meals.id).
-- Data types are kept in separate tables on purpose — see PRODUCT LOGIC in README.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student', 'staff')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per academic holiday / festival / special day.
-- Ordinary weekdays and weekends need no row here; they are derived from the date.
CREATE TABLE IF NOT EXISTS calendar_events (
    date      TEXT PRIMARY KEY,           -- YYYY-MM-DD
    name      TEXT NOT NULL,
    day_type  TEXT NOT NULL CHECK (day_type IN ('holiday', 'festival'))
);

-- The central record: one specific meal service (e.g. Lunch, 2026-09-16).
CREATE TABLE IF NOT EXISTS meals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,             -- YYYY-MM-DD
    meal_type  TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner')),
    menu_note  TEXT,                      -- optional free-text menu shown to students
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (date, meal_type)
);

-- Official attendance figure for a meal (from the college/mess attendance system).
-- Exactly one authoritative row per meal; staff enters/updates it.
CREATE TABLE IF NOT EXISTS attendance (
    meal_id      INTEGER PRIMARY KEY REFERENCES meals(id) ON DELETE CASCADE,
    official_count INTEGER NOT NULL CHECK (official_count >= 0),
    source       TEXT NOT NULL DEFAULT 'college_system',
    recorded_by  INTEGER REFERENCES users(id),
    recorded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Optional additional signal: a student saying "I'm not eating this meal".
-- This NEVER substitutes for attendance — it is only ever read as a side signal.
CREATE TABLE IF NOT EXISTS opt_outs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id    INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (meal_id, student_id)
);

-- ML prediction snapshot for a meal (kept even after the meal happens, for accuracy analytics).
CREATE TABLE IF NOT EXISTS predictions (
    meal_id          INTEGER PRIMARY KEY REFERENCES meals(id) ON DELETE CASCADE,
    predicted_diners INTEGER NOT NULL,
    method           TEXT NOT NULL CHECK (method IN ('ml_model', 'historical_average', 'fallback_default')),
    confidence_note  TEXT NOT NULL,
    historical_samples INTEGER NOT NULL DEFAULT 0,
    generated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Preparation: recommendation in servings, plus what actually happened.
-- The system stops at servings — it never computes ingredient kilograms.
-- Preparation: recommendation in servings, plus what actually happened.
-- The system stops at servings — it never computes ingredient kilograms.
--
-- basis/base_count record WHICH demand figure the recommendation was built from:
-- 'attendance' (today's actual recorded headcount — preferred once it's known, since it's
-- ground truth rather than a guess) or 'prediction' (the ML estimate — used only when
-- attendance for this specific meal isn't recorded yet).
CREATE TABLE IF NOT EXISTS preparation (
    meal_id              INTEGER PRIMARY KEY REFERENCES meals(id) ON DELETE CASCADE,
    basis                TEXT NOT NULL CHECK (basis IN ('prediction', 'attendance')),
    base_count           INTEGER NOT NULL,
    safety_buffer        INTEGER NOT NULL,
    recommended_servings INTEGER NOT NULL,
    confirmed_servings   INTEGER,          -- staff's final confirmed/adjusted figure
    actual_prepared      INTEGER,          -- entered after cooking
    actual_served        INTEGER,          -- entered after service
    confirmed_by         INTEGER REFERENCES users(id),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Plate waste: physically weighed, staff-entered. This IS the measured waste quantity.
CREATE TABLE IF NOT EXISTS plate_waste (
    meal_id     INTEGER PRIMARY KEY REFERENCES meals(id) ON DELETE CASCADE,
    weight_kg   REAL NOT NULL CHECK (weight_kg >= 0),
    entered_by  INTEGER REFERENCES users(id),
    entered_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Student-reported reason for leaving food. Behavioural signal only — never a quantity.
CREATE TABLE IF NOT EXISTS waste_reasons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id    INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL CHECK (reason IN (
                 'portion_too_large', 'disliked_taste', 'too_spicy',
                 'food_quality', 'food_cold', 'not_hungry', 'other')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (meal_id, student_id)
);

-- Meal rating, separate from waste reason. Never used to drive attendance prediction.
CREATE TABLE IF NOT EXISTS meal_ratings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id    INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (meal_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(date);
CREATE INDEX IF NOT EXISTS idx_waste_reasons_meal ON waste_reasons(meal_id);
CREATE INDEX IF NOT EXISTS idx_ratings_meal ON meal_ratings(meal_id);
