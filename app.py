import os
from pathlib import Path
from flask import Flask, render_template, session, redirect, url_for

from db import close_db, init_db, get_db
from auth import bp as auth_bp, current_user
from routes.meals import bp as meals_bp
from routes.feedback import bp as feedback_bp
from routes.analytics import bp as analytics_bp

BASE_DIR = Path(__file__).parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def create_app(database_path=None):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = os.environ.get("SFMS_SECRET_KEY", "dev-secret-change-in-production")
    app.config["DATABASE"] = database_path or str(INSTANCE_DIR / "sfms.db")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(analytics_bp)

    if not Path(app.config["DATABASE"]).exists():
        init_db(app)
    else:
        # make sure schema exists even if the db file was created empty
        init_db(app)

    @app.get("/")
    def index():
        return render_template("login.html")

    @app.get("/student")
    def student_page():
        return render_template("student.html")

    @app.get("/staff")
    def staff_page():
        return render_template("staff.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
