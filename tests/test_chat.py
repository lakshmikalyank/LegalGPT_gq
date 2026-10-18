"""
tests/test_chat.py

Tests for document upload, chat Q&A, and document analysis (including
the analysis cache). rag_service's LLM/ChromaDB calls are mocked since
the Groq API and ChromaDB aren't available in a test environment.
"""

import io
import json
from unittest.mock import MagicMock

from app import db
from app.models import Document, ChatHistory, AnalysisCache


def _create_processed_document(app, user_id, filename="lease.pdf"):
    """Insert a Document row directly, bypassing the real upload/index pipeline."""
    with app.app_context():
        document = Document(
            user_id=user_id,
            filename=filename,
            original_filename=filename,
            file_type="pdf",
            file_size=1024,
            chunk_count=3,
            processed=True,
        )
        db.session.add(document)
        db.session.commit()
        return document.id


def _get_user_id(app, username="testuser"):
    from app.models import User

    with app.app_context():
        return User.query.filter_by(username=username).first().id


def test_upload_rejects_invalid_extension(auth_client):
    data = {"file": (io.BytesIO(b"not a real document"), "malware.exe")}
    response = auth_client.post(
        "/upload", data=data, content_type="multipart/form-data"
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_upload_success_creates_processed_document(auth_client, app, monkeypatch):
    monkeypatch.setattr(
        "app.routes.chat.rag_service.extract_text", lambda path, ext: "Sample lease text."
    )
    monkeypatch.setattr(
        "app.routes.chat.rag_service.index_document", lambda doc_id, user_id, text: 3
    )

    data = {"file": (io.BytesIO(b"%PDF-1.4 fake content"), "lease.pdf")}
    response = auth_client.post(
        "/upload", data=data, content_type="multipart/form-data"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["document"]["chunk_count"] == 3

    with app.app_context():
        doc = Document.query.filter_by(original_filename="lease.pdf").first()
        assert doc is not None
        assert doc.processed is True


def test_ask_question_saves_chat_history(auth_client, app, monkeypatch):
    user_id = _get_user_id(app)
    doc_id = _create_processed_document(app, user_id)

    monkeypatch.setattr(
        "app.routes.chat.rag_service.answer_question",
        lambda question, user_id, document_id=None: "The lease ends in 2027.",
    )

    response = auth_client.post(
        "/chat/ask",
        data=json.dumps({"question": "When does the lease end?", "document_id": doc_id}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["answer"] == "The lease ends in 2027."

    with app.app_context():
        assert ChatHistory.query.filter_by(document_id=doc_id).count() == 1


def test_ask_question_rejects_empty_question(auth_client):
    response = auth_client.post(
        "/chat/ask",
        data=json.dumps({"question": "   "}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_analyze_document_not_yet_processed_returns_400(auth_client, app):
    user_id = _get_user_id(app)
    with app.app_context():
        doc = Document(
            user_id=user_id,
            filename="pending.pdf",
            original_filename="pending.pdf",
            file_type="pdf",
            processed=False,
        )
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

    response = auth_client.post(f"/documents/{doc_id}/analyze")
    assert response.status_code == 400


def test_analyze_document_returns_result_and_uses_cache(auth_client, app, monkeypatch):
    user_id = _get_user_id(app)
    doc_id = _create_processed_document(app, user_id)

    fake_result = {
        "summary": "This is a rental agreement.",
        "important_dates": {"agreement_date": "2024-01-01"},
        "mode": "summary",
        "truncated": False,
    }
    mock_analyze = MagicMock(return_value=fake_result)
    monkeypatch.setattr("app.routes.chat.rag_service.analyze_document", mock_analyze)

    # First request: should call the (mocked) LLM pipeline.
    response1 = auth_client.post(
        f"/documents/{doc_id}/analyze",
        data=json.dumps({"mode": "summary", "language": "en"}),
        content_type="application/json",
    )
    assert response1.status_code == 200
    payload1 = response1.get_json()
    assert payload1["cached"] is False
    assert payload1["analysis"]["summary"] == "This is a rental agreement."
    assert mock_analyze.call_count == 1

    # Second identical request: should be served from cache, not the LLM.
    response2 = auth_client.post(
        f"/documents/{doc_id}/analyze",
        data=json.dumps({"mode": "summary", "language": "en"}),
        content_type="application/json",
    )
    assert response2.status_code == 200
    payload2 = response2.get_json()
    assert payload2["cached"] is True
    assert payload2["analysis"]["summary"] == "This is a rental agreement."
    assert mock_analyze.call_count == 1  # not called again

    with app.app_context():
        assert AnalysisCache.query.filter_by(document_id=doc_id).count() == 1


def test_analyze_document_rejects_invalid_mode(auth_client, app):
    user_id = _get_user_id(app)
    doc_id = _create_processed_document(app, user_id)

    response = auth_client.post(
        f"/documents/{doc_id}/analyze",
        data=json.dumps({"mode": "invalid_mode"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_delete_document_removes_row_and_cache(auth_client, app):
    user_id = _get_user_id(app)
    doc_id = _create_processed_document(app, user_id)

    with app.app_context():
        db.session.add(
            AnalysisCache(
                document_id=doc_id, mode="full", language="en", result_json="{}"
            )
        )
        db.session.commit()

    response = auth_client.post(f"/documents/{doc_id}/delete")
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        assert Document.query.get(doc_id) is None
        assert AnalysisCache.query.filter_by(document_id=doc_id).count() == 0