"""
seed_data.py

Populates the Advocate table with sample directory data so the
Advocate Search feature has results to display out of the box.

Usage:
    python seed_data.py
"""

# Demonstration data only - not independently verified real-world advocates.
# Phone numbers are strings on purpose (one begins with a zero).
DEFAULT_ADVOCATES = [
    {"name": "Anil Reddy", "city": "Vijayawada", "specialization": "Property Law",
     "experience_years": 15, "phone": "9876543212", "email": "anil.reddy@example.com", "rating": 4.9},
    {"name": "Venkatesh Rao", "city": "Visakhapatnam", "specialization": "Civil Law",
     "experience_years": 18, "phone": "9876543214", "email": "venkatesh.rao@example.com", "rating": 4.9},
    {"name": "Arjun Patel", "city": "Mumbai", "specialization": "Tax Law",
     "experience_years": 14, "phone": "9876543216", "email": "arjun.patel@example.com", "rating": 4.8},
    {"name": "Rajesh Sharma", "city": "Delhi", "specialization": "Criminal Law",
     "experience_years": 15, "phone": "0987123456", "email": "rajesh.sharma@gmail.com", "rating": 4.7},
    {"name": "Sneha Gupta", "city": "Chennai", "specialization": "Corporate Law",
     "experience_years": 10, "phone": "9876543213", "email": "sneha.gupta@example.com", "rating": 4.7},
    {"name": "Sai Krishna", "city": "Nellore", "specialization": "Property Law",
     "experience_years": 9, "phone": "9876543218", "email": "sai.krishna@example.com", "rating": 4.7},
    {"name": "Priya Sharma", "city": "Bengaluru", "specialization": "Family Law",
     "experience_years": 8, "phone": "9876543211", "email": "priya.sharma@example.com", "rating": 4.6},
    {"name": "Neha Singh", "city": "Delhi", "specialization": "Cyber Law",
     "experience_years": 7, "phone": "9876543217", "email": "neha.singh@example.com", "rating": 4.6},
    # Specialization was not supplied; "Not specified" is used, not invented.
    {"name": "Lakshmi Devi", "city": "Tirupati", "specialization": "Not specified",
     "experience_years": 6, "phone": "9876543215", "email": "lakshmi.devi@example.com", "rating": 4.5},
    {"name": "Kiran Kumar", "city": "Guntur", "specialization": "Labour Law",
     "experience_years": 11, "phone": "9876543219", "email": "kiran.kumar@example.com", "rating": 4.5},
]

# Pre-existing sample entries, kept as-is.
SAMPLE_ADVOCATES = [
    {"name": "Rajesh Kumar Sharma", "city": "Delhi", "specialization": "Criminal Law",
     "experience_years": 15, "phone": "+91-9811023456", "email": "rajesh.sharma@lawfirm.in", "rating": 4.7},
    {"name": "Priya Mehta", "city": "Mumbai", "specialization": "Corporate Law",
     "experience_years": 10, "phone": "+91-9821034567", "email": "priya.mehta@lawfirm.in", "rating": 4.5},
    {"name": "Anil Verma", "city": "Bengaluru", "specialization": "Property Law",
     "experience_years": 12, "phone": "+91-9845123456", "email": "anil.verma@lawfirm.in", "rating": 4.3},
    {"name": "Sunita Rao", "city": "Hyderabad", "specialization": "Family Law",
     "experience_years": 8, "phone": "+91-9866234567", "email": "sunita.rao@lawfirm.in", "rating": 4.6},
    {"name": "Vikram Singh", "city": "Chandigarh", "specialization": "Civil Law",
     "experience_years": 20, "phone": "+91-9814345678", "email": "vikram.singh@lawfirm.in", "rating": 4.8},
    {"name": "Neha Kapoor", "city": "Delhi", "specialization": "Intellectual Property Law",
     "experience_years": 6, "phone": "+91-9811456789", "email": "neha.kapoor@lawfirm.in", "rating": 4.2},
    {"name": "Manoj Iyer", "city": "Chennai", "specialization": "Labour Law",
     "experience_years": 14, "phone": "+91-9840567890", "email": "manoj.iyer@lawfirm.in", "rating": 4.4},
    {"name": "Kavita Joshi", "city": "Pune", "specialization": "Tax Law",
     "experience_years": 11, "phone": "+91-9822678901", "email": "kavita.joshi@lawfirm.in", "rating": 4.5},
    {"name": "Arjun Nair", "city": "Kochi", "specialization": "Consumer Protection Law",
     "experience_years": 7, "phone": "+91-9847789012", "email": "arjun.nair@lawfirm.in", "rating": 4.1},
    {"name": "Deepika Reddy", "city": "Hyderabad", "specialization": "Corporate Law",
     "experience_years": 9, "phone": "+91-9866890123", "email": "deepika.reddy@lawfirm.in", "rating": 4.3},
    {"name": "Suresh Pillai", "city": "Bengaluru", "specialization": "Criminal Law",
     "experience_years": 18, "phone": "+91-9845901234", "email": "suresh.pillai@lawfirm.in", "rating": 4.9},
    {"name": "Ritu Bansal", "city": "Mumbai", "specialization": "Family Law",
     "experience_years": 13, "phone": "+91-9821012345", "email": "ritu.bansal@lawfirm.in", "rating": 4.6},
]


def seed_default_advocates():
    """
    Insert any default/sample advocate that is not already present.

    Idempotent: a record is matched by e-mail (case-insensitive), or by
    name + city when it has no e-mail, so restarts and redeploys never
    create duplicates. Existing rows are never modified or deleted, so
    admin edits and user-added advocates are preserved. Must be called
    inside an application context.

    Returns:
        int: number of records inserted.
    """
    from app import db
    from app.models import Advocate

    existing_emails = {
        (a.email or "").lower() for a in Advocate.query.with_entities(Advocate.email)
    }
    existing_name_city = {
        (a.name.lower(), a.city.lower())
        for a in Advocate.query.with_entities(Advocate.name, Advocate.city)
    }
    inserted = 0
    for entry in DEFAULT_ADVOCATES + SAMPLE_ADVOCATES:
        email = (entry["email"] or "").lower()
        if email in existing_emails or (
            entry["name"].lower(), entry["city"].lower()
        ) in existing_name_city:
            continue
        db.session.add(Advocate(**entry))
        existing_emails.add(email)
        inserted += 1
    if inserted:
        db.session.commit()
    return inserted


def seed_advocates():
    """CLI entry point: seed the directory using a fresh app context."""
    from app import create_app

    app = create_app()
    with app.app_context():
        count = seed_default_advocates()
        print(f"Seeded {count} new advocate record(s); existing records untouched.")


if __name__ == "__main__":
    seed_advocates()
