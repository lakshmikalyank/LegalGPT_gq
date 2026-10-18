"""
app/routes/auth.py

Authentication blueprint: registration, login, logout.
"""

import re
import logging

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.models import User

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.route("/", methods=["GET"])
def index():
    """Render the public landing page, or redirect to dashboard if already logged in."""
    if current_user.is_authenticated:
        return redirect(url_for("legal.dashboard"))
    return render_template("index.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handle new user registration."""
    if current_user.is_authenticated:
        return redirect(url_for("legal.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Basic server-side validation (never trust client-side alone)
        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if len(username) < 3:
            flash("Username must be at least 3 characters long.", "danger")
            return render_template("register.html")

        if not EMAIL_REGEX.match(email):
            flash("Please enter a valid email address.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return render_template("register.html")

        user = User(username=username, email=email)
        user.set_password(password)

        # First registered user becomes admin automatically
        if User.query.count() == 0:
            user.is_admin = True

        db.session.add(user)
        db.session.commit()

        logger.info("New user registered: %s", username)
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for("legal.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            (User.username == username) | (User.email == username.lower())
        ).first()

        if user is None or not user.check_password(password):
            logger.warning("Failed login attempt for '%s'", username)
            flash("Invalid username or password.", "danger")
            return render_template("login.html")

        login_user(user, remember=remember)
        logger.info("User logged in: %s", user.username)

        next_page = request.args.get("next")
        return redirect(next_page or url_for("legal.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    """Log the current user out and end their session."""
    logger.info("User logged out: %s", current_user.username)
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Display account details and handle password changes."""
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_new_password = request.form.get("confirm_new_password", "")

        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("auth.profile"))

        if len(new_password) < 6:
            flash("New password must be at least 6 characters long.", "danger")
            return redirect(url_for("auth.profile"))

        if new_password != confirm_new_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("auth.profile"))

        current_user.set_password(new_password)
        db.session.commit()

        logger.info("Password changed for user: %s", current_user.username)
        flash("Password updated successfully.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html")