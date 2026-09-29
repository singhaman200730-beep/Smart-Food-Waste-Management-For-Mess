from flask import Blueprint, request, jsonify
from db import get_db
from auth import role_required

bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@bp.get("/overview")
@role_required("staff")
def overview():
    meal_type = request.args.get("meal_type")  # optional filter
    db = get_db()

    type_clause = " AND m.meal_type = ?" if meal_type else ""
    type_params = [meal_type] if meal_type else []

    # 1. Prediction accuracy — only where both a prediction AND actual attendance exist.
    acc_rows = db.execute(
        f"""
        SELECT p.predicted_diners, a.official_count
        FROM predictions p
        JOIN meals m ON m.id = p.meal_id
        JOIN attendance a ON a.meal_id = p.meal_id
        WHERE 1=1 {type_clause}
        ORDER BY m.date DESC LIMIT 60
        """,
        type_params,
    ).fetchall()
    if acc_rows:
        errors = [abs(r["predicted_diners"] - r["official_count"]) for r in acc_rows]
        mae = sum(errors) / len(errors)
        mape_vals = [
            abs(r["predicted_diners"] - r["official_count"]) / r["official_count"]
            for r in acc_rows if r["official_count"]
        ]
        mape = (sum(mape_vals) / len(mape_vals) * 100) if mape_vals else None
    else:
        mae, mape = None, None

    # 2. Attendance trend by day of week (from actual attendance).
    trend_rows = db.execute(
        f"""
        SELECT m.date, m.meal_type, a.official_count
        FROM attendance a JOIN meals m ON m.id = a.meal_id
        WHERE 1=1 {type_clause}
        ORDER BY m.date
        """,
        type_params,
    ).fetchall()
    from calendar_context import day_of_week
    by_dow = {}
    for r in trend_rows:
        dow = day_of_week(r["date"])
        by_dow.setdefault(dow, []).append(r["official_count"])
    attendance_by_weekday = {
        dow: round(sum(vals) / len(vals)) for dow, vals in by_dow.items()
    }

    # 3. Unserved surplus & plate waste averages.
    waste_rows = db.execute(
        f"""
        SELECT p.actual_prepared, p.actual_served, pw.weight_kg
        FROM meals m
        LEFT JOIN preparation p ON p.meal_id = m.id
        LEFT JOIN plate_waste pw ON pw.meal_id = m.id
        WHERE 1=1 {type_clause}
        """,
        type_params,
    ).fetchall()
    surplus_vals = [
        r["actual_prepared"] - r["actual_served"] for r in waste_rows
        if r["actual_prepared"] is not None and r["actual_served"] is not None
    ]
    waste_vals = [r["weight_kg"] for r in waste_rows if r["weight_kg"] is not None]

    # 4. Waste reason distribution.
    reason_rows = db.execute(
        f"""
        SELECT wr.reason, COUNT(*) AS c
        FROM waste_reasons wr JOIN meals m ON m.id = wr.meal_id
        WHERE 1=1 {type_clause}
        GROUP BY wr.reason ORDER BY c DESC
        """,
        type_params,
    ).fetchall()

    # 5. Rating distribution.
    rating_rows = db.execute(
        f"""
        SELECT mr.rating, COUNT(*) AS c
        FROM meal_ratings mr JOIN meals m ON m.id = mr.meal_id
        WHERE 1=1 {type_clause}
        GROUP BY mr.rating ORDER BY mr.rating
        """,
        type_params,
    ).fetchall()

    # 6. Feedback coverage — response counts vs attendance, averaged over meals that have attendance.
    coverage_rows = db.execute(
        f"""
        SELECT a.official_count,
               (SELECT COUNT(*) FROM waste_reasons wr WHERE wr.meal_id = a.meal_id) AS reason_n,
               (SELECT COUNT(*) FROM meal_ratings mr WHERE mr.meal_id = a.meal_id) AS rating_n
        FROM attendance a JOIN meals m ON m.id = a.meal_id
        WHERE a.official_count > 0 {type_clause}
        """,
        type_params,
    ).fetchall()
    if coverage_rows:
        reason_cov = round(
            100 * sum(r["reason_n"] / r["official_count"] for r in coverage_rows) / len(coverage_rows), 1
        )
        rating_cov = round(
            100 * sum(r["rating_n"] / r["official_count"] for r in coverage_rows) / len(coverage_rows), 1
        )
    else:
        reason_cov, rating_cov = None, None

    return jsonify({
        "prediction_accuracy": {
            "mean_absolute_error": round(mae, 1) if mae is not None else None,
            "mean_absolute_percentage_error": round(mape, 1) if mape is not None else None,
            "sample_size": len(acc_rows),
        },
        "attendance_by_weekday": attendance_by_weekday,  # 0=Mon ... 6=Sun
        "unserved_surplus": {
            "average_servings": round(sum(surplus_vals) / len(surplus_vals), 1) if surplus_vals else None,
            "sample_size": len(surplus_vals),
        },
        "plate_waste": {
            "average_kg": round(sum(waste_vals) / len(waste_vals), 1) if waste_vals else None,
            "sample_size": len(waste_vals),
        },
        "waste_reason_distribution": [{"reason": r["reason"], "count": r["c"]} for r in reason_rows],
        "rating_distribution": [{"rating": r["rating"], "count": r["c"]} for r in rating_rows],
        "feedback_coverage": {
            "avg_waste_reason_coverage_pct": reason_cov,
            "avg_rating_coverage_pct": rating_cov,
            "sample_size": len(coverage_rows),
        },
    })
