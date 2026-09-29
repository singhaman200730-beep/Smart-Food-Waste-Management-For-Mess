"""Turns a diner prediction into a recommended number of servings.

This is a separate, simple, explainable rule layer — NOT part of the ML model,
and NOT ingredient quantities. It stops at "how many servings".
"""

MIN_BUFFER = 15
BUFFER_RATE = 0.06  # 6% safety margin on top of the prediction


def compute_buffer(predicted_diners):
    return max(MIN_BUFFER, round(predicted_diners * BUFFER_RATE))


def recommend_servings(predicted_diners):
    buffer = compute_buffer(predicted_diners)
    return {
        "predicted_diners": predicted_diners,
        "safety_buffer": buffer,
        "recommended_servings": predicted_diners + buffer,
    }
