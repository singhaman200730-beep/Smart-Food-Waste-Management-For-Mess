"""Simple, automatic calendar context — no manual festival-management workflow.

day_type is one of: 'normal', 'weekend', 'holiday', 'festival'.
holiday/festival (from calendar_events) always take priority over weekend/normal.
"""
from datetime import date as date_cls


def day_type_for(db, date_str):
    row = db.execute(
        "SELECT day_type FROM calendar_events WHERE date = ?", (date_str,)
    ).fetchone()
    if row:
        return row["day_type"]
    d = date_cls.fromisoformat(date_str)
    return "weekend" if d.weekday() >= 5 else "normal"


def day_of_week(date_str):
    return date_cls.fromisoformat(date_str).weekday()  # 0=Mon ... 6=Sun


def context_for(db, date_str):
    d = date_cls.fromisoformat(date_str)
    return {
        "date": date_str,
        "weekday_name": d.strftime("%A"),
        "day_of_week": d.weekday(),
        "day_type": day_type_for(db, date_str),
    }
