"""
tests/test_legal.py

Tests for the dashboard, advocate search, legal document generation,
and admin panel routes (including admin-only access control).
"""

import json

from app import db
from app.models import Advocate, User


def _register(client, username, email="user@example.com"):
    return client.post(
        "/register",
        data={
            "username": username,
            "email": email,
            "password": "password123",
            "confirm_password": "password123",
        },
    )


def _login(client, username):
    return client.post(
        "/login", data={"username": username, "password": "password123"}
    )


def test_dashboard_loads_for_logged_in_user(auth_client):
    response = auth_client.get("/dashboard")
    assert response.status_code == 200
    assert b"Documents Uploaded" in response.data


def test_advocate_search_filters_by_city_and_specialization(auth_client, app):
    with app.app_context():
        db.session.add_all(
            [
                Advocate(
                    name="Rajesh Sharma", city="Delhi",
                    specialization="Criminal Law", experience_years=15, rating=4.7,
                ),
                Advocate(
                    name="Priya Mehta", city="Mumbai",
                    specialization="Corporate Law", experience_years=10, rating=4.5,
                ),
            ]
        )
        db.session.commit()

    response = auth_client.get("/api/advocates?city=Delhi")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert len(payload["advocates"]) == 1
    assert payload["advocates"][0]["name"] == "Rajesh Sharma"


def test_advocate_search_min_experience_filter(auth_client, app):
    with app.app_context():
        db.session.add_all(
            [
                Advocate(name="A", city="Pune", specialization="Tax Law", experience_years=3, rating=4.0),
                Advocate(name="B", city="Pune", specialization="Tax Law", experience_years=12, rating=4.2),
            ]
        )
        db.session.commit()

    response = auth_client.get("/api/advocates?min_experience=10")
    payload = response.get_json()

    assert len(payload["advocates"]) == 1
    assert payload["advocates"][0]["name"] == "B"


def test_generate_legal_notice_creates_downloadable_pdf(auth_client):
    response = auth_client.post(
        "/generate/legal_notice",
        data={
            "recipient_name": "John Doe",
            "recipient_address": "123 Main St",
            "subject": "Payment Overdue",
            "body": "Please settle the outstanding amount within 15 days.",
            "sender_name": "Jane Smith",
            "sender_address": "456 Oak Ave",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "download_url" in payload["document"]

    download_response = auth_client.get(payload["document"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.data[:4] == b"%PDF"


def test_generate_rejects_unknown_document_type(auth_client):
    response = auth_client.post("/generate/not_a_real_type", data={})
    assert response.status_code == 400


def test_admin_panel_forbidden_for_non_admin(client, app):
    # The first registered user becomes admin automatically, so the
    # second user registered here is guaranteed to be a regular user.
    _register(client, "firstuser", "first@example.com")
    _register(client, "seconduser", "second@example.com")
    _login(client, "seconduser")

    response = client.get("/admin")
    assert response.status_code == 403


def test_admin_panel_accessible_to_first_registered_user(auth_client):
    # auth_client's "testuser" is the first (and only) registered user,
    # so per auth.py's logic they are automatically an admin.
    response = auth_client.get("/admin")
    assert response.status_code == 200
    assert b"Advocate Directory" in response.data


def test_admin_can_toggle_another_users_role(auth_client, app):
    # auth.register() redirects immediately if already logged in, so we
    # must log out before registering the second user, then log back in.
    auth_client.get("/logout")
    _register(auth_client, "regularuser", "regular@example.com")
    _login(auth_client, "testuser")

    with app.app_context():
        target = User.query.filter_by(username="regularuser").first()
        assert target.is_admin is False
        target_id = target.id

    response = auth_client.post(f"/admin/users/{target_id}/toggle-admin")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["is_admin"] is True

    with app.app_context():
        assert User.query.get(target_id).is_admin is True


def test_admin_cannot_change_own_role(auth_client, app):
    with app.app_context():
        self_id = User.query.filter_by(username="testuser").first().id

    response = auth_client.post(f"/admin/users/{self_id}/toggle-admin")
    assert response.status_code == 400


def test_admin_can_create_update_delete_advocate(auth_client, app):
    create_response = auth_client.post(
        "/admin/advocates",
        data={
            "name": "New Advocate",
            "city": "Chennai",
            "specialization": "Family Law",
            "experience_years": "5",
            "rating": "4.0",
        },
    )
    assert create_response.status_code == 200
    advocate_id = create_response.get_json()["id"]

    update_response = auth_client.post(
        f"/admin/advocates/{advocate_id}/update",
        data={
            "name": "Updated Advocate",
            "city": "Chennai",
            "specialization": "Family Law",
            "experience_years": "6",
            "rating": "4.5",
        },
    )
    assert update_response.status_code == 200

    with app.app_context():
        assert Advocate.query.get(advocate_id).name == "Updated Advocate"

    delete_response = auth_client.post(f"/admin/advocates/{advocate_id}/delete")
    assert delete_response.status_code == 200

    with app.app_context():
        assert Advocate.query.get(advocate_id) is None