from flask import Blueprint, request, jsonify, session
from db import get_db
from auth import role_required
from routes.meals import build_meal_detail

bp = Blueprint("feedback", __name__, url_prefix="/api/meals")

VALID_REASONS = (
    "portion_too_large", "disliked_taste", "too_spicy",
    "food_quality", "food_cold", "not_hungry", "other",
)


@bp.post("/<int:meal_id>/waste-reason")
@role_required("student")
def submit_waste_reason(meal_id):
    data = request.get_json(force=True) or {}
    reason = data.get("reason")
    if reason not in VALID_REASONS:
        return jsonify({"error": f"reason must be one of {VALID_REASONS}"}), 400
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute(
        """INSERT INTO waste_reasons (meal_id, student_id, reason) VALUES (?, ?, ?)
           ON CONFLICT(meal_id, student_id) DO UPDATE SET reason = excluded.reason, created_at = datetime('now')""",
        (meal_id, session["user_id"], reason),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))


@bp.post("/<int:meal_id>/rating")
@role_required("student")
def submit_rating(meal_id):
    data = request.get_json(force=True) or {}
    rating = data.get("rating")
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400
    db = get_db()
    meal = db.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        return jsonify({"error": "meal not found"}), 404
    db.execute(
        """INSERT INTO meal_ratings (meal_id, student_id, rating) VALUES (?, ?, ?)
           ON CONFLICT(meal_id, student_id) DO UPDATE SET rating = excluded.rating, created_at = datetime('now')""",
        (meal_id, session["user_id"], rating),
    )
    db.commit()
    return jsonify(build_meal_detail(db, meal))
