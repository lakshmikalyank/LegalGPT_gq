"""
app/__init__.py

Flask application factory for LegalGPT.

This module creates and configures the Flask application instance,
initializes all extensions (SQLAlchemy, LoginManager), registers all
blueprints (auth, chat, legal), sets up logging, and ensures required
folders exist.

Usage:
    from app import create_app
    app = create_app()
    app.run()
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask

from config import Config
from app.extensions import db, login_manager, csrf


def create_app(config_class=Config):
    """
    Application factory function.

    Creates a Flask app instance, applies configuration, initializes
    extensions, registers blueprints, and sets up logging.

    Args:
        config_class: The configuration class to use (defaults to
            the base Config class from config.py).

    Returns:
        Flask: A fully configured Flask application instance.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Run any additional config initialization (creates folders, etc.)
    config_class.init_app(app)

    # ------------------------------------------------------------------
    # Initialize extensions
    # ------------------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Flask-Login configuration
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # ------------------------------------------------------------------
    # Set up logging
    # ------------------------------------------------------------------
    _configure_logging(app)

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    from app.routes.auth import auth_bp
    from app.routes.chat import chat_bp
    from app.routes.legal import legal_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(legal_bp)

    # ------------------------------------------------------------------
    # User loader for Flask-Login
    # ------------------------------------------------------------------
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        """
        Reload the user object from the user ID stored in the session.

        Args:
            user_id (str): The user's primary key, stored as a string
                in the session by Flask-Login.

        Returns:
            User or None: The corresponding User object, or None if
                not found.
        """
        return db.session.get(User, int(user_id))

    # ------------------------------------------------------------------
    # Create database tables if they do not already exist
    # ------------------------------------------------------------------
    with app.app_context():
        db.create_all()
        app.logger.info("Database tables verified/created successfully.")

        if app.config.get("SEED_ADVOCATES_ON_STARTUP", True):
            try:
                from seed_data import seed_default_advocates

                added = seed_default_advocates()
                app.logger.info("Advocate seeding complete (%s new).", added)
            except Exception:
                db.session.rollback()
                app.logger.exception("Advocate seeding failed; continuing startup.")

    _register_error_handlers(app)

    app.logger.info("LegalGPT application created successfully.")

    return app


def _register_error_handlers(app):
    """Register handlers that render a friendly error.html for common HTTP errors."""
    from flask import render_template

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template(
            "error.html",
            code=403,
            title="Access Forbidden",
            message="You do not have permission to access this page.",
        ), 403

    @app.errorhandler(413)
    def too_large_error(error):
        from flask import jsonify, request

        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        message = f"File is too large. The maximum upload size is {limit_mb} MB."
        if request.path == "/upload":
            return jsonify({"success": False, "message": message}), 413
        return render_template(
            "error.html", code=413, title="File Too Large", message=message
        ), 413

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template(
            "error.html",
            code=404,
            title="Page Not Found",
            message="The page you are looking for does not exist.",
        ), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Internal server error")
        return render_template(
            "error.html",
            code=500,
            title="Internal Server Error",
            message="Something went wrong on our end. Please try again later.",
        ), 500


def _configure_logging(app):
    """
    Configure application-wide logging.

    Sets up a rotating file handler that writes logs to logs/legalgpt.log
    and also logs to the console when in debug mode.

    Args:
        app: The Flask application instance.
    """
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "legalgpt.log")

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1024 * 1024 * 5, backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s "
            "[in %(pathname)s:%(lineno)d]"
        )
    )
    file_handler.setLevel(logging.INFO)

    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("LegalGPT startup - logging configured.")