"""
app/routes/legal.py

Dashboard, legal document generation, advocate search, document
emailing, and admin panel blueprint.
"""

import os
import logging

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
    send_from_directory,
    abort,
)
from flask_login import login_required, current_user

from app import db
from app.models import User, Document, ChatHistory, GeneratedDocument, Advocate
from app.services import pdf_service, email_service

legal_bp = Blueprint("legal", __name__)
logger = logging.getLogger(__name__)


def _admin_required():
    """Abort with 403 if the current user is not an admin."""
    if not current_user.is_admin:
        abort(403)


@legal_bp.route("/dashboard")
@login_required
def dashboard():
    """Render the main dashboard with stats and recent uploads."""
    document_count = Document.query.filter_by(user_id=current_user.id).count()
    generated_count = GeneratedDocument.query.filter_by(user_id=current_user.id).count()
    chat_count = ChatHistory.query.filter_by(user_id=current_user.id).count()

    recent_uploads = (
        Document.query.filter_by(user_id=current_user.id)
        .order_by(Document.upload_date.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard.html",
        document_count=document_count,
        generated_count=generated_count,
        chat_count=chat_count,
        recent_uploads=recent_uploads,
    )


@legal_bp.route("/generate", methods=["GET"])
@login_required
def generate_form():
    """Render the legal document generation form page."""
    return render_template("generate.html", document_types=pdf_service.DOCUMENT_TYPES)


@legal_bp.route("/generate/<document_type>", methods=["POST"])
@login_required
def generate_document(document_type):
    """Generate a legal PDF document from submitted form data."""
    if document_type not in pdf_service.DOCUMENT_TYPES:
        return jsonify({"success": False, "message": "Unknown document type."}), 400

    form_data = request.form.to_dict()

    try:
        filename = pdf_service.generate_pdf(
            document_type, form_data, current_app.config["GENERATED_FOLDER"]
        )
    except Exception:
        logger.exception("Failed to generate PDF of type %s", document_type)
        return jsonify({"success": False, "message": "Failed to generate document."}), 500

    generated_doc = GeneratedDocument(
        user_id=current_user.id,
        document_type=document_type,
        filename=filename,
        title=pdf_service.DOCUMENT_TYPES[document_type],
    )
    db.session.add(generated_doc)
    db.session.commit()

    logger.info("Generated %s document (id=%s)", document_type, generated_doc.id)
    return jsonify(
        {
            "success": True,
            "message": "Document generated successfully.",
            "document": {
                "id": generated_doc.id,
                "title": generated_doc.title,
                "download_url": f"/generated/{generated_doc.id}/download",
            },
        }
    )


@legal_bp.route("/generated/<int:document_id>/download")
@login_required
def download_generated(document_id):
    """Download a previously generated PDF document."""
    generated_doc = GeneratedDocument.query.filter_by(
        id=document_id, user_id=current_user.id
    ).first()

    if generated_doc is None:
        abort(404)

    return send_from_directory(
        current_app.config["GENERATED_FOLDER"],
        generated_doc.filename,
        as_attachment=True,
        download_name=f"{generated_doc.title.replace(' ', '_')}.pdf",
    )


@legal_bp.route("/generated/<int:document_id>/email", methods=["POST"])
@login_required
def email_generated(document_id):
    """Email a generated PDF document as an attachment."""
    generated_doc = GeneratedDocument.query.filter_by(
        id=document_id, user_id=current_user.id
    ).first()

    if generated_doc is None:
        return jsonify({"success": False, "message": "Document not found."}), 404

    data = request.get_json(silent=True) or {}
    to_email = (data.get("email") or "").strip()

    if not to_email:
        return jsonify({"success": False, "message": "Recipient email is required."}), 400

    file_path = os.path.join(
        current_app.config["GENERATED_FOLDER"], generated_doc.filename
    )

    success, message = email_service.send_email_with_attachment(
        to_email=to_email,
        subject=f"Your {generated_doc.title} from LegalGPT",
        body=(
            f"Dear User,\n\nPlease find attached your requested "
            f"{generated_doc.title}.\n\nRegards,\nLegalGPT Team"
        ),
        attachment_path=file_path,
        attachment_name=f"{generated_doc.title.replace(' ', '_')}.pdf",
    )

    if success:
        generated_doc.emailed = True
        db.session.commit()

    return jsonify({"success": success, "message": message})


@legal_bp.route("/search", methods=["GET"])
@login_required
def search_page():
    """Render the advocate search page."""
    cities = [c[0] for c in db.session.query(Advocate.city).distinct().all()]
    specializations = [
        s[0] for s in db.session.query(Advocate.specialization).distinct().all()
    ]
    return render_template(
        "search.html", cities=cities, specializations=specializations
    )


@legal_bp.route("/api/advocates", methods=["GET"])
@login_required
def search_advocates():
    """Search advocates by city, specialization, and minimum experience."""
    city = request.args.get("city", "").strip()
    specialization = request.args.get("specialization", "").strip()
    min_experience = request.args.get("min_experience", type=int)

    query = Advocate.query
    if city:
        query = query.filter(Advocate.city.ilike(f"%{city}%"))
    if specialization:
        query = query.filter(Advocate.specialization.ilike(f"%{specialization}%"))
    if min_experience is not None:
        query = query.filter(Advocate.experience_years >= min_experience)

    advocates = query.order_by(Advocate.rating.desc()).all()

    return jsonify(
        {
            "success": True,
            "advocates": [
                {
                    "id": a.id,
                    "name": a.name,
                    "city": a.city,
                    "specialization": a.specialization,
                    "experience_years": a.experience_years,
                    "phone": a.phone,
                    "email": a.email,
                    "rating": a.rating,
                }
                for a in advocates
            ],
        }
    )


@legal_bp.route("/admin")
@login_required
def admin_panel():
    """Render the admin panel with platform-wide statistics and management tools."""
    _admin_required()

    total_users = User.query.count()
    total_documents = Document.query.count()
    total_generated = GeneratedDocument.query.count()
    total_chats = ChatHistory.query.count()

    all_users = User.query.order_by(User.created_at.desc()).all()
    all_advocates = Advocate.query.order_by(Advocate.name.asc()).all()

    return render_template(
        "admin.html",
        total_users=total_users,
        total_documents=total_documents,
        total_generated=total_generated,
        total_chats=total_chats,
        all_users=all_users,
        all_advocates=all_advocates,
    )


@legal_bp.route("/api/admin/chat-history")
@login_required
def admin_chat_history():
    """Return all users' chat history for admin review."""
    _admin_required()

    history = ChatHistory.query.order_by(ChatHistory.timestamp.desc()).limit(100).all()

    return jsonify(
        {
            "success": True,
            "history": [
                {
                    "user": h.user.username,
                    "question": h.question,
                    "answer": h.answer,
                    "timestamp": h.timestamp.isoformat(),
                }
                for h in history
            ],
        }
    )


@legal_bp.route("/admin/advocates", methods=["POST"])
@login_required
def admin_create_advocate():
    """Create a new advocate directory entry."""
    _admin_required()

    data = request.form.to_dict()
    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    specialization = (data.get("specialization") or "").strip()

    if not name or not city or not specialization:
        return jsonify(
            {"success": False, "message": "Name, city, and specialization are required."}
        ), 400

    try:
        experience_years = int(data.get("experience_years") or 0)
        rating = float(data.get("rating") or 0)
    except ValueError:
        return jsonify(
            {"success": False, "message": "Experience and rating must be numbers."}
        ), 400

    advocate = Advocate(
        name=name,
        city=city,
        specialization=specialization,
        experience_years=experience_years,
        phone=(data.get("phone") or "").strip() or None,
        email=(data.get("email") or "").strip() or None,
        rating=rating,
    )
    db.session.add(advocate)
    db.session.commit()

    return jsonify({"success": True, "message": "Advocate added.", "id": advocate.id})


@legal_bp.route("/admin/advocates/<int:advocate_id>/update", methods=["POST"])
@login_required
def admin_update_advocate(advocate_id):
    """Update an existing advocate directory entry."""
    _admin_required()

    advocate = Advocate.query.get(advocate_id)
    if advocate is None:
        return jsonify({"success": False, "message": "Advocate not found."}), 404

    data = request.form.to_dict()
    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    specialization = (data.get("specialization") or "").strip()

    if not name or not city or not specialization:
        return jsonify(
            {"success": False, "message": "Name, city, and specialization are required."}
        ), 400

    try:
        experience_years = int(data.get("experience_years") or 0)
        rating = float(data.get("rating") or 0)
    except ValueError:
        return jsonify(
            {"success": False, "message": "Experience and rating must be numbers."}
        ), 400

    advocate.name = name
    advocate.city = city
    advocate.specialization = specialization
    advocate.experience_years = experience_years
    advocate.phone = (data.get("phone") or "").strip() or None
    advocate.email = (data.get("email") or "").strip() or None
    advocate.rating = rating
    db.session.commit()

    return jsonify({"success": True, "message": "Advocate updated."})


@legal_bp.route("/admin/advocates/<int:advocate_id>/delete", methods=["POST"])
@login_required
def admin_delete_advocate(advocate_id):
    """Delete an advocate directory entry."""
    _admin_required()

    advocate = Advocate.query.get(advocate_id)
    if advocate is None:
        return jsonify({"success": False, "message": "Advocate not found."}), 404

    db.session.delete(advocate)
    db.session.commit()

    return jsonify({"success": True, "message": "Advocate deleted."})


@legal_bp.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
def admin_toggle_user_role(user_id):
    """Promote a user to admin, or demote an admin back to a regular user."""
    _admin_required()

    if user_id == current_user.id:
        return jsonify(
            {"success": False, "message": "You cannot change your own admin status."}
        ), 400

    user = User.query.get(user_id)
    if user is None:
        return jsonify({"success": False, "message": "User not found."}), 404

    user.is_admin = not user.is_admin
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"{user.username} is now {'an admin' if user.is_admin else 'a regular user'}.",
            "is_admin": user.is_admin,
        }
    )


@legal_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    """Delete a user account and all of their associated data."""
    _admin_required()

    if user_id == current_user.id:
        return jsonify(
            {"success": False, "message": "You cannot delete your own account."}
        ), 400

    user = User.query.get(user_id)
    if user is None:
        return jsonify({"success": False, "message": "User not found."}), 404

    db.session.delete(user)
    db.session.commit()

    return jsonify({"success": True, "message": f"{user.username} deleted."})