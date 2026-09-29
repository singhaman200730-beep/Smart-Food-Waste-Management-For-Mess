import sqlite3
from pathlib import Path
from flask import g, current_app

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db = get_db()
        with open(SCHEMA_PATH, "r") as f:
            db.executescript(f.read())
        db.commit()


def get_or_create_meal(db, date, meal_type):
    row = db.execute(
        "SELECT * FROM meals WHERE date = ? AND meal_type = ?", (date, meal_type)
    ).fetchone()
    if row:
        return row
    cur = db.execute(
        "INSERT INTO meals (date, meal_type) VALUES (?, ?)", (date, meal_type)
    )
    db.commit()
    return db.execute("SELECT * FROM meals WHERE id = ?", (cur.lastrowid,)).fetchone()


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]
