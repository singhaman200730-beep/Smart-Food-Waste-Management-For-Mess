"""ML's one job: predict how many students will eat a future meal.

Trains only on historical ACTUAL attendance + calendar/day context.
Never trained on feedback counts, waste counts, waste amounts, or ratings.

Falls back honestly (and says so) when there isn't enough history yet,
instead of pretending a model is confident when it isn't.
"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor

MIN_SAMPLES_FOR_ML = 10
DEFAULT_FALLBACK_DINERS = {"breakfast": 250, "lunch": 400, "dinner": 350}

DAY_TYPE_CODE = {"normal": 0, "weekend": 1, "holiday": 2, "festival": 3}


def _historical_rows(db, meal_type, before_date):
    """Actual attendance history for this meal type, strictly before the target date."""
    return db.execute(
        """
        SELECT m.date, m.meal_type, a.official_count
        FROM attendance a
        JOIN meals m ON m.id = a.meal_id
        WHERE m.meal_type = ? AND m.date < ?
        ORDER BY m.date
        """,
        (meal_type, before_date),
    ).fetchall()


def _features(db, date_str, meal_type):
    from calendar_context import context_for
    ctx = context_for(db, date_str)
    return [ctx["day_of_week"], DAY_TYPE_CODE.get(ctx["day_type"], 0)], ctx


def predict_attendance(db, date_str, meal_type):
    """Returns dict: predicted_diners, method, confidence_note, historical_samples."""
    from calendar_context import context_for

    history = _historical_rows(db, meal_type, date_str)
    n = len(history)
    target_ctx = context_for(db, date_str)

    if n >= MIN_SAMPLES_FOR_ML:
        X, y = [], []
        for row in history:
            ctx = context_for(db, row["date"])
            X.append([ctx["day_of_week"], DAY_TYPE_CODE.get(ctx["day_type"], 0)])
            y.append(row["official_count"])
        X = np.array(X)
        y = np.array(y)

        model = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=6)
        model.fit(X, y)

        x_target = np.array([[target_ctx["day_of_week"], DAY_TYPE_CODE.get(target_ctx["day_type"], 0)]])
        pred = float(model.predict(x_target)[0])
        pred = max(0, round(pred))

        return {
            "predicted_diners": pred,
            "method": "ml_model",
            "confidence_note": f"Model trained on {n} historical {meal_type} records.",
            "historical_samples": n,
        }

    # Not enough data for a trained model — fall back to an honest average.
    same_day_rows = [r for r in history if context_for(db, r["date"])["day_of_week"] == target_ctx["day_of_week"]]
    if same_day_rows:
        avg = round(sum(r["official_count"] for r in same_day_rows) / len(same_day_rows))
        return {
            "predicted_diners": avg,
            "method": "historical_average",
            "confidence_note": (
                f"Only {n} historical {meal_type} records available (below the {MIN_SAMPLES_FOR_ML} "
                f"needed to train a model) — using the average of {len(same_day_rows)} past "
                f"{target_ctx['weekday_name']} {meal_type}(s) instead. Treat this as a rough estimate."
            ),
            "historical_samples": n,
        }

    if history:
        avg = round(sum(r["official_count"] for r in history) / len(history))
        return {
            "predicted_diners": avg,
            "method": "historical_average",
            "confidence_note": (
                f"Only {n} historical {meal_type} records available, none on a "
                f"{target_ctx['weekday_name']} — using the overall {meal_type} average instead. "
                f"Treat this as a rough estimate."
            ),
            "historical_samples": n,
        }

    default = DEFAULT_FALLBACK_DINERS.get(meal_type, 300)
    return {
        "predicted_diners": default,
        "method": "fallback_default",
        "confidence_note": (
            f"No historical {meal_type} attendance data exists yet — using a generic default. "
            f"This will improve automatically as real attendance is recorded."
        ),
        "historical_samples": 0,
    }
