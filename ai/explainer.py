"""AI's role, strictly: EXPLANATION + RECOMMENDATION.

It never predicts attendance, never computes ingredient quantities, and never
overrides the preparation figure or makes the final call — staff does that.

This module is a deterministic, evidence-based explainer so the system always
works out of the box (no external API key required). It is written so a real
LLM call could be dropped in behind the same evidence bundle later without
changing anything else in the app — see README "Extending the AI layer".
"""

RECENT_WINDOW = 5

# A waste reason is only treated as representative evidence — strong enough to drive a
# recommendation — once it clears BOTH a minimum absolute response count and a minimum
# share of actual attendance. Below that, it's shown as a data point but never used to
# justify an action: a handful of responses out of hundreds of diners isn't a pattern.
MIN_REASON_RESPONSES = 10
MIN_REASON_COVERAGE_PCT = 5.0


def _recent_same_meal_type(db, meal_type, before_date, limit=RECENT_WINDOW):
    return db.execute(
        """
        SELECT m.id, m.date, pw.weight_kg, p.actual_prepared, p.actual_served
        FROM meals m
        LEFT JOIN plate_waste pw ON pw.meal_id = m.id
        LEFT JOIN preparation p ON p.meal_id = m.id
        WHERE m.meal_type = ? AND m.date < ? AND pw.weight_kg IS NOT NULL
        ORDER BY m.date DESC
        LIMIT ?
        """,
        (meal_type, before_date, limit),
    ).fetchall()


def _recent_ratings_avg(db, meal_type, before_date, limit=RECENT_WINDOW):
    rows = db.execute(
        """
        SELECT AVG(r.rating) AS avg_rating, COUNT(*) AS n
        FROM meal_ratings r
        JOIN meals m ON m.id = r.meal_id
        WHERE m.meal_type = ? AND m.date < ?
        AND m.id IN (SELECT id FROM meals WHERE meal_type = ? AND date < ? ORDER BY date DESC LIMIT ?)
        """,
        (meal_type, before_date, meal_type, before_date, limit),
    ).fetchone()
    return rows["avg_rating"], rows["n"]


def _top_waste_reason(db, meal_id):
    row = db.execute(
        """
        SELECT reason, COUNT(*) AS c FROM waste_reasons
        WHERE meal_id = ? GROUP BY reason ORDER BY c DESC LIMIT 1
        """,
        (meal_id,),
    ).fetchone()
    return row["reason"] if row else None


def build_evidence(db, meal, prediction, preparation_row, plate_waste_row, ratings_summary, coverage):
    meal_type = meal["meal_type"]
    date_str = meal["date"]

    recent_waste_rows = _recent_same_meal_type(db, meal_type, date_str)
    recent_avg_waste = None
    if recent_waste_rows:
        weights = [r["weight_kg"] for r in recent_waste_rows if r["weight_kg"] is not None]
        if weights:
            recent_avg_waste = sum(weights) / len(weights)

    recent_avg_rating, recent_rating_n = _recent_ratings_avg(db, meal_type, date_str)
    top_reason = _top_waste_reason(db, meal["id"])

    return {
        "predicted_diners": prediction["predicted_diners"] if prediction else None,
        "prediction_confidence_note": prediction["confidence_note"] if prediction else None,
        "recommended_servings": preparation_row["recommended_servings"] if preparation_row else None,
        "actual_prepared": preparation_row["actual_prepared"] if preparation_row else None,
        "actual_served": preparation_row["actual_served"] if preparation_row else None,
        "unserved_surplus": (
            preparation_row["actual_prepared"] - preparation_row["actual_served"]
            if preparation_row and preparation_row["actual_prepared"] is not None
            and preparation_row["actual_served"] is not None else None
        ),
        "plate_waste_kg": plate_waste_row["weight_kg"] if plate_waste_row else None,
        "recent_avg_plate_waste_kg": recent_avg_waste,
        "avg_rating": ratings_summary["avg_rating"] if ratings_summary else None,
        "rating_responses": ratings_summary["n"] if ratings_summary else 0,
        "recent_avg_rating": recent_avg_rating,
        "top_waste_reason": top_reason,
        "waste_reason_responses": coverage.get("waste_reason_responses", 0),
        "attendance": coverage.get("attendance"),
        "waste_reason_coverage_pct": (
            round(100 * coverage.get("waste_reason_responses", 0) / coverage["attendance"], 1)
            if coverage.get("attendance") else None
        ),
    }


REASON_LABELS = {
    "portion_too_large": "portions being too large",
    "disliked_taste": "disliking the taste",
    "too_spicy": "food being too spicy",
    "food_quality": "food quality",
    "food_cold": "food being served cold",
    "not_hungry": "students not being hungry",
    "other": "other reasons",
}


def explain(evidence):
    """Produces (explanation, recommendation) strings from the evidence bundle only."""
    parts = []

    if evidence["predicted_diners"] is not None:
        parts.append(f"Predicted attendance is {evidence['predicted_diners']} diners.")
    if evidence["attendance"] is not None:
        parts.append(f"Actual recorded attendance was {evidence['attendance']}.")

    if evidence["plate_waste_kg"] is not None:
        if evidence["recent_avg_plate_waste_kg"]:
            diff = evidence["plate_waste_kg"] - evidence["recent_avg_plate_waste_kg"]
            pct = (diff / evidence["recent_avg_plate_waste_kg"]) * 100 if evidence["recent_avg_plate_waste_kg"] else 0
            if pct > 20:
                parts.append(
                    f"Measured plate waste ({evidence['plate_waste_kg']:.1f} kg) is notably higher than "
                    f"the recent average of {evidence['recent_avg_plate_waste_kg']:.1f} kg."
                )
            elif pct < -20:
                parts.append(
                    f"Measured plate waste ({evidence['plate_waste_kg']:.1f} kg) is notably lower than "
                    f"the recent average of {evidence['recent_avg_plate_waste_kg']:.1f} kg."
                )
            else:
                parts.append(
                    f"Measured plate waste ({evidence['plate_waste_kg']:.1f} kg) is close to the recent "
                    f"average of {evidence['recent_avg_plate_waste_kg']:.1f} kg."
                )
        else:
            parts.append(f"Measured plate waste is {evidence['plate_waste_kg']:.1f} kg (no recent baseline yet).")

    if evidence["unserved_surplus"] is not None:
        parts.append(f"Unserved surplus was {evidence['unserved_surplus']} servings.")

    if evidence["avg_rating"] is not None:
        rating_txt = f"Average meal rating is {evidence['avg_rating']:.1f}/5 from {evidence['rating_responses']} response(s)."
        if evidence["recent_avg_rating"]:
            if evidence["avg_rating"] < evidence["recent_avg_rating"] - 0.5:
                rating_txt += " This is lower than the recent average."
            elif evidence["avg_rating"] > evidence["recent_avg_rating"] + 0.5:
                rating_txt += " This is higher than the recent average."
        parts.append(rating_txt)

    if evidence["top_waste_reason"]:
        label = REASON_LABELS.get(evidence["top_waste_reason"], evidence["top_waste_reason"])
        reason_evidence_sufficient = (
            evidence["waste_reason_responses"] >= MIN_REASON_RESPONSES
            and evidence["waste_reason_coverage_pct"] is not None
            and evidence["waste_reason_coverage_pct"] >= MIN_REASON_COVERAGE_PCT
        )
        coverage_txt = (
            f" ({evidence['waste_reason_coverage_pct']}% of attendance)"
            if evidence["waste_reason_coverage_pct"] is not None else ""
        )
        if reason_evidence_sufficient:
            parts.append(
                f"Among {evidence['waste_reason_responses']} student response(s){coverage_txt}, the most "
                f"common reason cited for leftover food is {label}."
            )
        else:
            parts.append(
                f"Only {evidence['waste_reason_responses']} student(s){coverage_txt} gave a waste reason "
                f"(most commonly {label}) — too few responses to treat as representative of why food was left."
            )
    else:
        reason_evidence_sufficient = False

    explanation = " ".join(parts) if parts else "Not enough evidence is recorded for this meal yet."

    # Recommendation
    rec_bits = []
    high_waste = (
        evidence["plate_waste_kg"] is not None
        and evidence["recent_avg_plate_waste_kg"]
        and evidence["plate_waste_kg"] > evidence["recent_avg_plate_waste_kg"] * 1.2
    )
    high_surplus = evidence["unserved_surplus"] is not None and evidence["recommended_servings"] and \
        evidence["unserved_surplus"] > 0.15 * evidence["recommended_servings"]
    low_rating = evidence["avg_rating"] is not None and evidence["avg_rating"] < 3.0

    if high_waste and reason_evidence_sufficient and evidence["top_waste_reason"] == "portion_too_large":
        rec_bits.append("Consider reviewing portion sizes for this meal.")
    elif high_waste and reason_evidence_sufficient:
        rec_bits.append("Consider reviewing recipe/preparation for this meal given the elevated plate waste.")
    elif high_waste:
        rec_bits.append(
            "Plate waste is elevated, but student feedback coverage is too low to confidently attribute "
            "a cause — worth investigating directly (e.g. a quick check with kitchen/serving staff) rather "
            "than acting on the small number of responses alone."
        )

    if high_surplus:
        rec_bits.append("Unserved surplus is high relative to servings prepared — consider a smaller buffer next time.")

    if low_rating:
        rec_bits.append("Meal ratings are on the lower side — worth checking feedback details before the next repeat of this meal.")

    if not rec_bits:
        if evidence["predicted_diners"] is not None:
            rec_bits.append(
                f"No major adjustment appears necessary; proceed with the recommended "
                f"{evidence['recommended_servings']} servings." if evidence["recommended_servings"] else
                "No major adjustment appears necessary based on the available evidence."
            )
        else:
            rec_bits.append("Record attendance, plate waste, and feedback for this meal to enable a recommendation.")

    recommendation = " ".join(rec_bits)
    return explanation, recommendation
