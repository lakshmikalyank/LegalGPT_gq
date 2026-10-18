"""
app/extensions.py

Centralized Flask extension instances.

Extensions are instantiated here (unbound) and initialized against the
app instance inside app/__init__.py's create_app(). Keeping them in a
separate module avoids circular imports: models.py, routes, and
services can import db/login_manager directly without importing the
app package itself.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()