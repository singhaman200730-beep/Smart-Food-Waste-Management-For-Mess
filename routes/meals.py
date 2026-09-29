from datetime import date as date_cls
from flask import Blueprint, request, jsonify, session
from db import get_db, get_or_create_meal, row_to_dict, rows_to_list
from auth import login_required, role_required, current_user
from calendar_context import context_for
from ml.predictor import predict_attendance
from ml.preparation import recommend_servings
from ai.explainer import build_evidence, explain

bp = Blueprint("meals", __name__, url_prefix="/api/meals")

VALID_MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _ensure_prediction(db, meal):
    """Predictions are generated once per meal and then kept (for accuracy analytics)."""
    row = db.execute("SELECT * FROM predictions WHERE meal_id = ?", (meal["id"],)).fetchone()
    if row:
        return row
    result = predict_attendance(db, meal["date"], meal["meal_type"])
    db.execute(
        """INSERT INTO predictions (meal_id, predicted_diners, method, confidence_note, historical_samples)
           VALUES (?, ?, ?, ?, ?)""",
        (meal["id"], result["predicted_diners"], result["method"],
         result["confidence_note"], result["historical_samples"]),
    )
    db.commit()
    return db.execute("SELECT * FROM predictions WHERE meal_id = ?", (meal["id"],)).fetchone()


def _current_suggestion(db, meal, prediction, attendance):
    """What the system would currently recommend, computed fresh every time.

    Prefers today's actual recorded attendance (ground truth for this specific meal)
    over the ML prediction (a statistical estimate, only needed while attendance isn't
    known yet). This is what keeps the recommendation reacting immediately when staff
    update attendance — instead of staying frozen at whatever the prediction said.
    """
    if attendance is not None:
        basis = "attendance"
        base_count = attendance["official_count"]
        note = f"Based on today's recorded attendance ({base_count})."
    else:
        basis = "prediction"
        base_count = prediction["predicted_diners"]
        note = f"Based on the ML prediction ({base_count}) — no attendance recorded for this meal yet."
    calc = recommend_servings(base_count)
    return {"basis": basis, "base_count": base_count, "note": note, **calc}


def build_meal_detail(db, meal):
    meal_id = meal["id"]
    ctx = context_for(db, meal["date"])
    attendance = db.execute("SELECT * FROM attendance WHERE meal_id = ?", (meal_id,)).fetchone()
    opt_out_count = db.execute(
        "SELECT COUNT(*) AS c FROM opt_outs WHERE meal_id = ?", (meal_id,)
    ).fetchone()["c"]

    prediction = _ensure_prediction(db, meal)
    suggestion = _current_suggestion(db, meal, prediction, attendance)
    preparation = db.execute("SELECT * FROM preparation WHERE meal_id = ?", (meal_id,)).fetchone()
    plate_waste = db.execute("SELECT * FROM plate_waste WHERE meal_id = ?", (meal_id,)).fetchone()

    ratings_row = db.execute(
        "SELECT AVG(rating) AS avg_rating, COUNT(*) AS n FROM meal_ratings WHERE meal_id = ?",
        (meal_id,),
    ).fetchone()
    rating_dist = db.execute(
        "SELECT rating, COUNT(*) AS c FROM meal_ratings WHERE meal_id = ? GROUP BY rating",
        (meal_id,),
    ).fetchall()

    reason_rows = db.execute(
        "SELECT reason, COUNT(*) AS c FROM waste_reasons WHERE meal_id = ? GROUP BY reason ORDER BY c DESC",
        (meal_id,),
    ).fetchall()
    waste_reason_responses = sum(r["c"] for r in reason_rows)

    attendance_count = attendance["official_count"] if attendance else None
    coverage = {
        "attendance": attendance_count,
        "waste_reason_responses": waste_reason_responses,
        "rating_responses": ratings_row["n"] or 0,
        "waste_reason_coverage_pct": (
            round(100 * waste_reason_responses / attendance_count, 1)
            if attendance_count else None
        ),
        "rating_coverage_pct": (
            round(100 * (ratings_row["n"] or 0) / attendance_count, 1)
            if attendance_count else None
        ),
    }

    detail = {
        "meal": row_to_dict(meal),
        "calendar_context": ctx,
        "attendance": row_to_dict(attendance),
        "opt_out_count": opt_out_count,
        "prediction": row_to_dict(prediction),
        "suggestion": suggestion,
        "preparation": row_to_dict(preparation),
        "plate_waste": row_to_dict(plate_waste),
        "ratings_summary": {
            "avg_rating": ratings_row["avg_rating"],
            "count": ratings_row["n"] or 0,
            "distribution": {r["rating"]: r["c"] for r in rating_dist},
        },
        "waste_reasons_summary": {
            "total_responses": waste_reason_responses,
            "breakdown": [{"reason": r["reason"], "count": r["c"]} for r in reason_rows],
        },
        "coverage": coverage,
    }

    user = current_user(db)
    if user and user["role"] == "student":
        opted_out = db.execute(
            "SELECT 1 FROM opt_outs WHERE meal_id = ? AND student_id = ?", (meal_id, user["id"])
        ).fetchone()
        my_reason = db.execute(
            "SELECT reason FROM waste_reasons WHERE meal_id = ? AND student_id = ?", (meal_id, user["id"])
        ).fetchone()
        my_rating = db.execute(
            "SELECT rating FROM meal_ratings WHERE meal_id = ? AND student_id = ?", (meal_id, user["id"])
        ).fetchone()
        detail["you"] = {
            "opted_out": bool(opted_out),
            "waste_reason": my_reason["reason"] if my_reason else None,
            "rating": my_rating["rating"] if my_rating else None,
        }

    return detail


def _validate_meal_type(meal_type):
    return meal_type in VALID_MEAL_TYPES


@bp.get("/today")
@login_required
def today():
    meal_type = request.args.get("meal_type", "lunch")
    if not _validate_meal_type(meal_type):
        return jsonify({"error": "invalid meal_type"}), 400
    db = get_db()
    meal = get_or_create_meal(db, date_cls.today().isoformat(), meal_type)
    return jsonify(build_meal_detail(db, meal))


@bp.post("")
@role_required("staff")
def create_meal():
    data = request.get_json(force=True) or {}
    date_str, meal_type = data.get("date"), data.get("meal_type")
    if not date_str or not _validate_meal_type(meal_type):
        return jsonify({"error": "date and a valid meal_type are required"}), 400
    db = get_db()
    meal = get_or_create_meal(db, date_str, meal_type)
    return jsonify(build_meal_detail(db, meal)), 201


@bp.get("")
@login_required
def list_meals():
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    meal_type = request.args.get("meal_type")

    query = "SELECT * FROM meals WHERE 1=1"
    params = []
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    if meal_type:
        query += " AND meal_type = ?"
        params.append(meal_type)
    query += " ORDER BY date DESC, meal_type LIMIT 200"

    db = get_db()
    meals = db.execute(query, params).fetchall()
    out = []
    for m in meals:
        attendance = db.execute("SELECT official_count FROM attendance WHERE meal_id = ?", (m["id"],)).fetchone()
        prep = db.execute("SELECT recommended_servings, actual_prepared, actual_served FROM preparation WHERE meal_id = ?", (m["id"],)).fetchone()
        waste = db.execute("SELECT weight_kg FROM plate_waste WHERE meal_id = ?", (m["id"],)).fetchone()
        out.append({
            **row_to_dict(m),
            "official_count": attendance["official_count"] if attendance else None,
            "recommended_servings": prep["recommended_servings"] if prep else None,
            "actual_prepared": prep["actual_prepared"] if prep else None,
            "actual_served": prep["actual_served"] if prep else None,
            "unserved_surplus": (
                prep["actual_prepared"] - prep["actual_served"]
                if prep and prep["actual_prepared"] is not None and prep["actual_served"] is not None else None
            ),
            "plate_waste_kg": waste["weight_kg"] if waste else None,
        })
    return jsonify(out)


@bp.get("/<int:meal_id>")
@login_required
def meal_detail(meal_id):
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/menu")
@role_required("staff")
def set_menu(meal_id):
    data = request.get_json(force=True) or {}
    menu_note = (data.get("menu_note") or "").strip()
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute("UPDATE meals SET menu_note = ? WHERE id = ?", (menu_note, meal_id))
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/attendance")
@role_required("staff")
def set_attendance(meal_id):
    data = request.get_json(force=True) or {}
    count = data.get("official_count")
    if not isinstance(count, int) or count < 0:
        return jsonify({"error": "official_count must be a non-negative integer"}), 400
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute(
        """INSERT INTO attendance (meal_id, official_count, source, recorded_by)
           VALUES (?, ?, 'college_system', ?)
           ON CONFLICT(meal_id) DO UPDATE SET official_count = excluded.official_count,
               recorded_by = excluded.recorded_by, recorded_at = datetime('now')""",
        (meal_id, count, session["user_id"]),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/opt-out")
@role_required("student")
def opt_out(meal_id):
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute(
        "INSERT OR IGNORE INTO opt_outs (meal_id, student_id) VALUES (?, ?)",
        (meal_id, session["user_id"]),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.delete("/<int:meal_id>/opt-out")
@role_required("student")
def undo_opt_out(meal_id):
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute("DELETE FROM opt_outs WHERE meal_id = ? AND student_id = ?", (meal_id, session["user_id"]))
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/preparation/confirm")
@role_required("staff")
def confirm_preparation(meal_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404

    prediction = _ensure_prediction(db, meal)
    attendance = db.execute("SELECT * FROM attendance WHERE meal_id = ?", (meal_id,)).fetchone()

    # Staff can explicitly request a basis ('prediction' or 'attendance'); otherwise use
    # whichever the system would currently suggest (attendance if it's known, else prediction).
    requested_basis = data.get("basis")
    if requested_basis not in (None, "prediction", "attendance"):
        return jsonify({"error": "basis must be 'prediction' or 'attendance'"}), 400
    if requested_basis == "attendance" and attendance is None:
        return jsonify({"error": "no attendance recorded for this meal yet — cannot use it as the basis"}), 400

    if requested_basis:
        base_count = attendance["official_count"] if requested_basis == "attendance" else prediction["predicted_diners"]
        basis = requested_basis
        calc = recommend_servings(base_count)
    else:
        suggestion = _current_suggestion(db, meal, prediction, attendance)
        basis, base_count, calc = suggestion["basis"], suggestion["base_count"], suggestion

    confirmed = data.get("confirmed_servings", calc["recommended_servings"])
    if not isinstance(confirmed, int) or confirmed < 0:
        return jsonify({"error": "confirmed_servings must be a non-negative integer"}), 400

    db.execute(
        """INSERT INTO preparation (meal_id, basis, base_count, safety_buffer, recommended_servings,
               confirmed_servings, confirmed_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(meal_id) DO UPDATE SET basis = excluded.basis, base_count = excluded.base_count,
               safety_buffer = excluded.safety_buffer, recommended_servings = excluded.recommended_servings,
               confirmed_servings = excluded.confirmed_servings,
               confirmed_by = excluded.confirmed_by, updated_at = datetime('now')""",
        (meal_id, basis, base_count, calc["safety_buffer"], calc["recommended_servings"],
         confirmed, session["user_id"]),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.patch("/<int:meal_id>/preparation")
@role_required("staff")
def update_actuals(meal_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    prep = db.execute("SELECT * FROM preparation WHERE meal_id = ?", (meal_id,)).fetchone()
    if not prep:
        return jsonify({"error": "confirm a preparation quantity before recording actuals"}), 400

    actual_prepared = data.get("actual_prepared", prep["actual_prepared"])
    actual_served = data.get("actual_served", prep["actual_served"])

    if actual_prepared is not None and actual_served is not None:
        if actual_served > actual_prepared:
            return jsonify({"error": "actual_served cannot exceed actual_prepared"}), 400
    for val, name in ((actual_prepared, "actual_prepared"), (actual_served, "actual_served")):
        if val is not None and (not isinstance(val, int) or val < 0):
            return jsonify({"error": f"{name} must be a non-negative integer"}), 400

    db.execute(
        "UPDATE preparation SET actual_prepared = ?, actual_served = ?, updated_at = datetime('now') WHERE meal_id = ?",
        (actual_prepared, actual_served, meal_id),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/plate-waste")
@role_required("staff")
def set_plate_waste(meal_id):
    data = request.get_json(force=True) or {}
    weight = data.get("weight_kg")
    if not isinstance(weight, (int, float)) or weight < 0:
        return jsonify({"error": "weight_kg must be a non-negative number"}), 400
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute(
        """INSERT INTO plate_waste (meal_id, weight_kg, entered_by) VALUES (?, ?, ?)
           ON CONFLICT(meal_id) DO UPDATE SET weight_kg = excluded.weight_kg,
               entered_by = excluded.entered_by, entered_at = datetime('now')""",
        (meal_id, float(weight), session["user_id"]),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.get("/<int:meal_id>/ai-insight")
@login_required
def ai_insight(meal_id):
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404

    prediction = _ensure_prediction(db, meal)
    preparation = db.execute("SELECT * FROM preparation WHERE meal_id = ?", (meal_id,)).fetchone()
    plate_waste = db.execute("SELECT * FROM plate_waste WHERE meal_id = ?", (meal_id,)).fetchone()
    attendance = db.execute("SELECT official_count FROM attendance WHERE meal_id = ?", (meal_id,)).fetchone()
    ratings_row = db.execute(
        "SELECT AVG(rating) AS avg_rating, COUNT(*) AS n FROM meal_ratings WHERE meal_id = ?", (meal_id,)
    ).fetchone()
    waste_reason_count = db.execute(
        "SELECT COUNT(*) AS c FROM waste_reasons WHERE meal_id = ?", (meal_id,)
    ).fetchone()["c"]

    evidence = build_evidence(
        db, meal, prediction, preparation, plate_waste,
        {"avg_rating": ratings_row["avg_rating"], "n": ratings_row["n"] or 0},
        {"waste_reason_responses": waste_reason_count,
         "attendance": attendance["official_count"] if attendance else None},
    )
    explanation, recommendation = explain(evidence)
    return jsonify({"evidence": evidence, "explanation": explanation, "recommendation": recommendation})
