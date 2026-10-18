"""
tests/test_auth.py

Tests for registration, login, and logout.
"""

from app.models import User


def test_register_creates_user(client, app):
    response = client.post(
        "/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is not None


def test_register_rejects_mismatched_passwords(client):
    response = client.post(
        "/register",
        data={
            "username": "bob",
            "email": "bob@example.com",
            "password": "password123",
            "confirm_password": "different456",
        },
        follow_redirects=True,
    )

    assert b"Passwords do not match" in response.data


def test_register_rejects_duplicate_username(client):
    client.post(
        "/register",
        data={
            "username": "carol",
            "email": "carol1@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    response = client.post(
        "/register",
        data={
            "username": "carol",
            "email": "carol2@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=True,
    )

    assert b"Username already taken" in response.data


def test_login_with_correct_credentials_redirects_to_dashboard(client):
    client.post(
        "/register",
        data={
            "username": "dave",
            "email": "dave@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    response = client.post(
        "/login",
        data={"username": "dave", "password": "password123"},
    )

    assert response.status_code == 302
    assert "/dashboard" in response.location


def test_login_with_wrong_password_shows_error(client):
    client.post(
        "/register",
        data={
            "username": "erin",
            "email": "erin@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    response = client.post(
        "/login",
        data={"username": "erin", "password": "wrongpassword"},
        follow_redirects=True,
    )

    assert b"Invalid username or password" in response.data


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.location


def test_logout_ends_session(auth_client):
    response = auth_client.get("/dashboard")
    assert response.status_code == 200

    auth_client.get("/logout")

    response = auth_client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.location