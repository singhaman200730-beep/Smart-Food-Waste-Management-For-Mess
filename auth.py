from functools import wraps
from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, row_to_dict

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def role_required(role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return jsonify({"error": "authentication required"}), 401
            if session.get("role") != role:
                return jsonify({"error": f"{role} role required"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_user(db):
    if "user_id" not in session:
        return None
    return db.execute("SELECT id, name, email, role FROM users WHERE id = ?",
                       (session["user_id"],)).fetchone()


@bp.post("/register")
def register():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = data.get("role")

    if not name or not email or not password or role not in ("student", "staff"):
        return jsonify({"error": "name, email, password and a valid role are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return jsonify({"error": "an account with this email already exists"}), 409

    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, generate_password_hash(password, method="pbkdf2:sha256:260000"), role),
    )
    db.commit()
    session["user_id"] = cur.lastrowid
    session["role"] = role
    return jsonify({"id": cur.lastrowid, "name": name, "email": email, "role": role}), 201


@bp.post("/login")
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid email or password"}), 401

    session["user_id"] = user["id"]
    session["role"] = user["role"]
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    db = get_db()
    user = current_user(db)
    if not user:
        return jsonify({"error": "not authenticated"}), 401
    return jsonify(row_to_dict(user))
