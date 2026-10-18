"""
app/routes/chat.py

Document upload and AI chat (RAG) blueprint.
"""

import os
import json
import logging

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import Document, ChatHistory, AnalysisCache
from app.services import rag_service

chat_bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)


def _allowed_file(filename):
    """Check whether a filename has an allowed extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


_SIGNATURES = {
    "pdf": (b"%PDF",),
    "docx": (b"PK\x03\x04",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}


def _content_matches_extension(file_path, ext):
    """Verify the file's leading bytes match its claimed extension."""
    with open(file_path, "rb") as fh:
        head = fh.read(8)
    return any(head.startswith(sig) for sig in _SIGNATURES.get(ext, ()))


@chat_bp.route("/chat", methods=["GET"])
@login_required
def chat_page():
    """Render the chat interface with the user's document list."""
    documents = (
        Document.query.filter_by(user_id=current_user.id)
        .order_by(Document.upload_date.desc())
        .all()
    )
    return render_template("chat.html", documents=documents)


@chat_bp.route("/uploads", methods=["GET"])
@login_required
def uploads_page():
    """Render the document management page with paginated uploads."""
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config["DOCUMENTS_PER_PAGE"]

    pagination = (
        Document.query.filter_by(user_id=current_user.id)
        .order_by(Document.upload_date.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return render_template("uploads.html", pagination=pagination, documents=pagination.items)


@chat_bp.route("/upload", methods=["POST"])
@login_required
def upload_document():
    """
    Handle document upload: save file, extract text, chunk, embed,
    and store the resulting vectors in ChromaDB.
    """
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file part in request."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected."}), 400

    if not _allowed_file(file.filename):
        return jsonify(
            {"success": False, "message": "Only PDF, DOCX and JPG/JPEG files are allowed."}
        ), 400

    original_filename = file.filename
    ext = original_filename.rsplit(".", 1)[-1].lower()
    safe_name = secure_filename(original_filename)
    stored_filename = f"user{current_user.id}_{os.urandom(4).hex()}_{safe_name}"

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    file_path = os.path.join(upload_folder, stored_filename)
    file.save(file_path)
    file_size = os.path.getsize(file_path)

    if file_size == 0 or not _content_matches_extension(file_path, ext):
        os.remove(file_path)
        message = (
            "The uploaded file is empty."
            if file_size == 0
            else "The file's contents do not match its extension. "
            "Upload a genuine PDF, DOCX or JPG/JPEG file."
        )
        return jsonify({"success": False, "message": message}), 400

    document = Document(
        user_id=current_user.id,
        filename=stored_filename,
        original_filename=original_filename,
        file_type=ext,
        file_size=file_size,
        processed=False,
    )
    db.session.add(document)
    db.session.commit()

    try:
        text = rag_service.extract_text(file_path, ext)
        chunk_count = rag_service.index_document(document.id, current_user.id, text)

        if chunk_count == 0:
            # No usable text was extracted (e.g. a scanned/image-only PDF,
            # or an unreadable encoding). Marking this as processed=True
            # would silently create a document that later fails every
            # analyze/chat request with "No indexed content was found".
            db.session.delete(document)
            db.session.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify(
                {
                    "success": False,
                    "message": "No readable text could be extracted from this file. "
                    "Try a clearer scan/photo or a text-based PDF or DOCX.",
                }
            ), 400

        document.chunk_count = chunk_count
        document.processed = True
        db.session.commit()
    except rag_service.DocumentExtractionError as exc:
        db.session.delete(document)
        db.session.commit()
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception:
        logger.exception("Failed to process document_id=%s", document.id)
        db.session.delete(document)
        db.session.commit()
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify(
            {
                "success": False,
                "message": "File uploaded but processing failed. "
                "Ensure the file is not corrupted and try again.",
            }
        ), 500

    logger.info("Document uploaded and indexed: %s (id=%s)", original_filename, document.id)
    return jsonify(
        {
            "success": True,
            "message": "Document uploaded and processed successfully.",
            "document": {
                "id": document.id,
                "filename": document.original_filename,
                "file_type": document.file_type,
                "chunk_count": document.chunk_count,
            },
        }
    )


@chat_bp.route("/documents/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_document(document_id):
    """Delete a document, its file on disk, and its vector embeddings."""
    document = Document.query.filter_by(
        id=document_id, user_id=current_user.id
    ).first()

    if document is None:
        return jsonify({"success": False, "message": "Document not found."}), 404

    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], document.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    try:
        rag_service.delete_document_embeddings(document.id)
    except Exception:
        logger.exception("Failed to delete embeddings for document_id=%s", document.id)

    # Purge any cached analysis results for this document so a future
    # document that happens to reuse this ID can never see stale cache.
    AnalysisCache.query.filter_by(document_id=document.id).delete()

    db.session.delete(document)
    db.session.commit()

    return jsonify({"success": True, "message": "Document deleted."})


@chat_bp.route("/chat/ask", methods=["POST"])
@login_required
def ask_question():
    """
    Handle an AJAX chat question: run the RAG pipeline and return the
    generated answer, saving the exchange to chat history.
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    document_id = data.get("document_id")

    if not question:
        return jsonify({"success": False, "message": "Question cannot be empty."}), 400

    if document_id:
        owned = Document.query.filter_by(
            id=document_id, user_id=current_user.id
        ).first()
        if owned is None:
            return jsonify({"success": False, "message": "Invalid document."}), 403

    answer = rag_service.answer_question(
        question=question, user_id=current_user.id, document_id=document_id
    )

    history_entry = ChatHistory(
        user_id=current_user.id,
        document_id=document_id,
        question=question,
        answer=answer,
    )
    db.session.add(history_entry)
    db.session.commit()

    return jsonify({"success": True, "answer": answer, "timestamp": history_entry.timestamp.isoformat()})


@chat_bp.route("/chat/history", methods=["GET"])
@login_required
def chat_history():
    """Return the current user's chat history as JSON (for reloading the chat window)."""
    document_id = request.args.get("document_id", type=int)

    query = ChatHistory.query.filter_by(user_id=current_user.id)
    if document_id:
        query = query.filter_by(document_id=document_id)

    history = query.order_by(ChatHistory.timestamp.asc()).all()

    return jsonify(
        {
            "success": True,
            "history": [
                {
                    "question": h.question,
                    "answer": h.answer,
                    "timestamp": h.timestamp.isoformat(),
                }
                for h in history
            ],
        }
    )


@chat_bp.route("/documents/<int:document_id>/analyze", methods=["POST"])
@login_required
def analyze_document(document_id):
    """
    Run structured document analysis on an uploaded document using the
    existing RAG pipeline and Groq LLM.

    Accepts an optional JSON body:
        {"mode": "full" | "summary", "language": "<code>"}

    "mode" defaults to "full" (summary + dates + people + actions +
    clauses); "summary" returns only summary + dates.

    "language" defaults to "en". If set to a supported Indian language
    code (see rag_service.SUPPORTED_LANGUAGES), the analysis is generated
    in English first and then translated — the English generation logic
    is unaffected by this parameter.
    """
    document = Document.query.filter_by(
        id=document_id, user_id=current_user.id
    ).first()

    if document is None:
        return jsonify({"success": False, "message": "Document not found."}), 404

    if not document.processed:
        return jsonify(
            {
                "success": False,
                "message": "This document has not finished processing yet. "
                "Please wait a moment and try again.",
            }
        ), 400

    request_data = request.get_json(silent=True) or {}
    mode = request_data.get("mode", "full")
    language = request_data.get("language", "en")

    if mode not in ("full", "summary"):
        return jsonify(
            {
                "success": False,
                "message": "Invalid analysis mode. Use 'full' or 'summary'.",
            }
        ), 400

    if language not in rag_service.SUPPORTED_LANGUAGES:
        return jsonify(
            {
                "success": False,
                "message": "Unsupported language selected.",
            }
        ), 400

    # Check the cache first: an identical (document, mode, language)
    # request returns instantly instead of re-running the LLM pipeline.
    cached = AnalysisCache.query.filter_by(
        document_id=document.id, mode=mode, language=language
    ).first()

    if cached is not None:
        try:
            analysis = json.loads(cached.result_json)
            logger.info(
                "Document analysis served from cache: document_id=%s mode=%s language=%s",
                document_id, mode, language,
            )
            return jsonify({"success": True, "analysis": analysis, "cached": True})
        except (json.JSONDecodeError, ValueError):
            # Corrupted cache row (should not normally happen) — log it,
            # delete it, and fall through to regenerate fresh below.
            logger.exception(
                "Corrupted cache entry for document_id=%s mode=%s language=%s; regenerating",
                document_id, mode, language,
            )
            db.session.delete(cached)
            db.session.commit()

    try:
        analysis = rag_service.analyze_document(
            document_id=document.id, user_id=current_user.id, mode=mode
        )
    except ValueError:
        return jsonify(
            {
                "success": False,
                "message": "No indexed content was found for this document.",
            }
        ), 400
    except Exception:
        logger.exception("Document analysis failed for document_id=%s", document_id)
        return jsonify(
            {
                "success": False,
                "message": "Analysis failed. Please check your Groq API key and try again.",
            }
        ), 500

    if language != "en":
        try:
            analysis = rag_service.translate_analysis(analysis, language)
        except Exception:
            # translate_analysis() already fails safe internally, but this
            # guards against any unexpected error still reaching the route.
            logger.exception(
                "Unexpected error translating analysis for document_id=%s", document_id
            )

    # Store the freshly generated result in the cache for next time.
    # Uses the unique (document_id, mode, language) constraint to avoid
    # duplicate rows if two requests race each other.
    try:
        cache_entry = AnalysisCache(
            document_id=document.id,
            mode=mode,
            language=language,
            result_json=json.dumps(analysis),
        )
        db.session.add(cache_entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(
            "Failed to write analysis cache for document_id=%s mode=%s language=%s",
            document_id, mode, language,
        )

    logger.info(
        "Document analyzed: document_id=%s mode=%s language=%s",
        document_id, mode, language,
    )
    return jsonify({"success": True, "analysis": analysis, "cached": False})


@chat_bp.route("/chat/clear", methods=["POST"])
@login_required
def clear_chat():
    """
    Delete the current user's chat history. If a document_id is given,
    only that document's chat history is cleared (matching whatever is
    currently displayed in the chat window); otherwise all of the
    user's chat history is cleared.

    Only ChatHistory rows are affected — documents, analysis cache,
    ChromaDB embeddings, and all other data are untouched.
    """
    data = request.get_json(silent=True) or {}
    document_id = data.get("document_id")

    query = ChatHistory.query.filter_by(user_id=current_user.id)
    if document_id:
        query = query.filter_by(document_id=document_id)

    deleted_count = query.delete()
    db.session.commit()

    logger.info(
        "Cleared %d chat message(s) for user_id=%s document_id=%s",
        deleted_count, current_user.id, document_id,
    )
    return jsonify({"success": True, "message": "Chat history cleared.", "deleted": deleted_count})