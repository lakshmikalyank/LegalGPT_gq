"""
tests/conftest.py

Shared pytest fixtures: a fresh, isolated test app per test (temp
SQLite DB, temp upload/generated/chroma folders, CSRF disabled), a
test client, and a client pre-authenticated with a registered user.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config


@pytest.fixture
def app(tmp_path):
    """A fresh app instance per test, backed by an isolated temp SQLite DB."""
    from app import create_app

    class TestConfig(Config):
        TESTING = True
        SEED_ADVOCATES_ON_STARTUP = False
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        GENERATED_FOLDER = str(tmp_path / "generated")
        CHROMA_DB_DIR = str(tmp_path / "chroma")

    application = create_app(TestConfig)
    application.config["SERVER_NAME"] = "localhost"

    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """A test client with a registered and logged-in user."""
    client.post(
        "/register",
        data={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123"},
    )
    return client