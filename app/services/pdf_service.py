"""
app/services/pdf_service.py

Generates legal PDF documents (Legal Notice, NDA, Rental Agreement,
Complaint Letter, Affidavit) using ReportLab.

These are drafting aids, not finished legal instruments: every document
includes a disclaimer, and documents meant to be signed include actual
signature lines. The app fills in the wording; the parties themselves
(and, for the Affidavit, a Notary Public) are responsible for the
document's legal validity.
"""

import os
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib import colors

DOCUMENT_TYPES = {
    "legal_notice": "Legal Notice",
    "nda": "Non-Disclosure Agreement",
    "rental_agreement": "Rental Agreement",
    "complaint_letter": "Complaint Letter",
    "affidavit": "Affidavit",
}

# Standard disclaimer for documents the parties can sign themselves
# without needing a separate authority (Legal Notice, NDA, Rental
# Agreement, Complaint Letter). These are private agreements between
# the parties - the tool drafts the wording, the parties themselves
# give it legal effect by reviewing and signing it.
STANDARD_DISCLAIMER = (
    "This document is a draft template generated for informational and "
    "convenience purposes only. It does not constitute legal advice. "
    "Review all details carefully, adapt it to your specific situation, "
    "and consider having it reviewed by a qualified lawyer before "
    "signing or relying on it."
)

# Affidavits are a different category: the document has no legal effect
# at all until sworn before a notary/oath commissioner/magistrate. This
# warning is stronger and more specific than the standard disclaimer.
AFFIDAVIT_DISCLAIMER = (
    "This is a DRAFT STATEMENT ONLY. It is not a legally valid affidavit "
    "until it is signed in person before a Notary Public, Oath "
    "Commissioner, or other authorized official, as required in your "
    "jurisdiction. This application cannot notarize documents."
)


def _get_styles():
    """Return a stylesheet extended with custom paragraph styles used across templates."""
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DocTitle",
            fontSize=16,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName="Helvetica-Bold",
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            fontSize=11,
            leading=16,
            alignment=TA_JUSTIFY,
            spaceAfter=12,
            fontName="Helvetica",
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )
    )
    styles.add(
        ParagraphStyle(
            name="Disclaimer",
            fontSize=8.5,
            leading=11,
            alignment=TA_JUSTIFY,
            textColor=colors.grey,
            fontName="Helvetica-Oblique",
        )
    )
    styles.add(
        ParagraphStyle(
            name="AffidavitWarning",
            fontSize=10,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.red,
            fontName="Helvetica-Bold",
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SignatureLabel",
            fontSize=10,
            leading=14,
            fontName="Helvetica",
            spaceBefore=4,
        )
    )
    return styles


def _base_doc(output_path):
    """Create a standard A4 document template with consistent margins."""
    return SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )


def _add_disclaimer_footer(story, styles, text=STANDARD_DISCLAIMER):
    """Append a horizontal rule and the disclaimer text to the end of a document."""
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", color=colors.lightgrey, thickness=0.75))
    story.append(Spacer(1, 8))
    story.append(Paragraph(text, styles["Disclaimer"]))


def _signature_block(label, styles, include_witness=False):
    """
    Build a signature block: a signing line, a name label, and a date
    line, optionally with a witness line beneath it. Used for every
    document type the parties are meant to actually sign.
    """
    block = [
        Spacer(1, 26),
        Paragraph("_______________________________", styles["SignatureLabel"]),
        Paragraph(f"{label}", styles["SignatureLabel"]),
        Paragraph("Date: ______________________", styles["SignatureLabel"]),
    ]
    if include_witness:
        block.append(Spacer(1, 10))
        block.append(Paragraph("Witness Signature: _______________________________", styles["SignatureLabel"]))
        block.append(Paragraph("Witness Name: ______________________", styles["SignatureLabel"]))
    return block


def _build_legal_notice(data, styles):
    story = [Paragraph("LEGAL NOTICE", styles["DocTitle"])]
    story.append(Paragraph(f"Date: {data.get('date', date.today().isoformat())}", styles["Body"]))
    story.append(Paragraph(f"To: {data.get('recipient_name', '')}", styles["Body"]))
    story.append(Paragraph(f"Address: {data.get('recipient_address', '')}", styles["Body"]))
    story.append(Paragraph("Subject: " + data.get("subject", "Legal Notice"), styles["SectionHeading"]))
    story.append(Paragraph(data.get("body", ""), styles["Body"]))
    story.append(Spacer(1, 24))
    story.append(Paragraph(f"Sender: {data.get('sender_name', '')}", styles["Body"]))
    story.append(Paragraph(f"Address: {data.get('sender_address', '')}", styles["Body"]))
    story.extend(_signature_block("Sender's Signature", styles))
    _add_disclaimer_footer(story, styles)
    return story


def _build_nda(data, styles):
    story = [Paragraph("NON-DISCLOSURE AGREEMENT", styles["DocTitle"])]
    story.append(
        Paragraph(
            f"This Non-Disclosure Agreement (\"Agreement\") is entered into on "
            f"{data.get('date', date.today().isoformat())} between "
            f"{data.get('party_one', '')} (\"Disclosing Party\") and "
            f"{data.get('party_two', '')} (\"Receiving Party\").",
            styles["Body"],
        )
    )
    story.append(Paragraph("1. Purpose", styles["SectionHeading"]))
    story.append(Paragraph(data.get("purpose", ""), styles["Body"]))

    story.append(Paragraph("2. Confidential Information", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "The Receiving Party agrees to hold all confidential information "
            "disclosed by the Disclosing Party in strict confidence and not "
            "disclose it to any third party without prior written consent.",
            styles["Body"],
        )
    )

    story.append(Paragraph("3. Exclusions", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "This Agreement does not apply to information that: (a) is or "
            "becomes publicly available through no fault of the Receiving "
            "Party; (b) was already lawfully known to the Receiving Party "
            "prior to disclosure; (c) is independently developed by the "
            "Receiving Party without use of the Confidential Information; or "
            "(d) is required to be disclosed by law or a valid order of a "
            "court or government authority.",
            styles["Body"],
        )
    )

    story.append(Paragraph("4. Return or Destruction of Materials", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "Upon termination of this Agreement or upon the Disclosing "
            "Party's request, the Receiving Party shall promptly return or "
            "destroy all documents, materials, and other tangible "
            "manifestations of the Confidential Information.",
            styles["Body"],
        )
    )

    story.append(Paragraph("5. Term", styles["SectionHeading"]))
    story.append(
        Paragraph(
            f"This Agreement shall remain in effect for {data.get('duration', '2 years')} "
            "from the date of signing, unless terminated earlier by mutual "
            "written consent of both parties.",
            styles["Body"],
        )
    )

    story.append(Paragraph("6. Remedies", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "The parties acknowledge that unauthorized disclosure of "
            "Confidential Information may cause irreparable harm for which "
            "monetary damages alone may be inadequate, and that the "
            "Disclosing Party shall be entitled to seek injunctive relief "
            "in addition to any other available remedies.",
            styles["Body"],
        )
    )

    story.append(Paragraph("7. Governing Law", styles["SectionHeading"]))
    story.append(
        Paragraph(
            f"This Agreement shall be governed by and construed in "
            f"accordance with the laws of "
            f"{data.get('governing_law', '[Insert applicable jurisdiction]')}.",
            styles["Body"],
        )
    )

    story.extend(_signature_block("Disclosing Party's Signature", styles))
    story.extend(_signature_block("Receiving Party's Signature", styles))
    _add_disclaimer_footer(story, styles)
    return story


def _build_rental_agreement(data, styles):
    story = [Paragraph("RENTAL AGREEMENT", styles["DocTitle"])]
    story.append(
        Paragraph(
            f"This Rental Agreement is made on {data.get('date', date.today().isoformat())} "
            f"between {data.get('landlord_name', '')} (\"Landlord\") and "
            f"{data.get('tenant_name', '')} (\"Tenant\") for the property located at "
            f"{data.get('property_address', '')}.",
            styles["Body"],
        )
    )

    table_data = [
        ["Monthly Rent", data.get("monthly_rent", "")],
        ["Security Deposit", data.get("security_deposit", "")],
        ["Lease Start Date", data.get("start_date", "")],
        ["Lease Duration", data.get("duration", "")],
    ]
    table = Table(table_data, colWidths=[200, 250])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 10))
    story.append(table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Terms and Conditions", styles["SectionHeading"]))
    story.append(
        Paragraph(
            data.get(
                "terms",
                "The Tenant agrees to pay rent on time and maintain the "
                "property in good condition throughout the lease term.",
            ),
            styles["Body"],
        )
    )

    story.append(Paragraph("Maintenance and Repairs", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "The Tenant shall promptly notify the Landlord of any damage or "
            "needed repairs. The Landlord is responsible for maintaining "
            "the structural condition and major systems of the property; "
            "the Tenant is responsible for damage caused by their own "
            "negligence or misuse.",
            styles["Body"],
        )
    )

    story.append(Paragraph("Utilities", styles["SectionHeading"]))
    story.append(
        Paragraph(
            data.get(
                "utilities",
                "Unless otherwise agreed in writing, the Tenant is "
                "responsible for electricity, water, and other utility "
                "charges incurred during the tenancy.",
            ),
            styles["Body"],
        )
    )

    story.append(Paragraph("Termination and Notice", styles["SectionHeading"]))
    story.append(
        Paragraph(
            data.get(
                "termination_notice",
                "Either party may terminate this Agreement by providing at "
                "least 30 days' written notice to the other party, subject "
                "to any minimum lease term stated above.",
            ),
            styles["Body"],
        )
    )

    story.append(Paragraph("Return of Security Deposit", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "The security deposit shall be refunded to the Tenant within a "
            "reasonable period after the end of the tenancy, less any "
            "deductions for unpaid rent or damage beyond normal wear and "
            "tear.",
            styles["Body"],
        )
    )

    story.append(Paragraph("Subletting", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "The Tenant shall not sublet the property, in whole or in "
            "part, without the prior written consent of the Landlord.",
            styles["Body"],
        )
    )

    story.extend(_signature_block("Landlord's Signature", styles))
    story.extend(_signature_block("Tenant's Signature", styles))
    _add_disclaimer_footer(story, styles)
    return story


def _build_complaint_letter(data, styles):
    story = [Paragraph("COMPLAINT LETTER", styles["DocTitle"])]
    story.append(Paragraph(f"Date: {data.get('date', date.today().isoformat())}", styles["Body"]))
    story.append(Paragraph(f"To: {data.get('recipient_name', '')}", styles["Body"]))
    story.append(Paragraph(f"From: {data.get('sender_name', '')}", styles["Body"]))
    story.append(Paragraph("Subject: " + data.get("subject", "Complaint"), styles["SectionHeading"]))
    story.append(Paragraph(data.get("body", ""), styles["Body"]))
    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            "I request that this matter be resolved at the earliest and look "
            "forward to a prompt response.",
            styles["Body"],
        )
    )
    story.extend(_signature_block("Sender's Signature", styles))
    _add_disclaimer_footer(story, styles)
    return story


def _build_affidavit(data, styles):
    story = [Paragraph("AFFIDAVIT", styles["DocTitle"])]
    story.append(Paragraph(AFFIDAVIT_DISCLAIMER, styles["AffidavitWarning"]))
    story.append(
        Paragraph(
            f"I, {data.get('deponent_name', '')}, resident of "
            f"{data.get('deponent_address', '')}, do hereby solemnly affirm and "
            "declare as follows:",
            styles["Body"],
        )
    )
    story.append(Paragraph(data.get("declaration", ""), styles["Body"]))
    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            "I state that the above information is true and correct to the "
            "best of my knowledge and belief, and that nothing material has "
            "been concealed.",
            styles["Body"],
        )
    )

    story.extend(_signature_block("Deponent's Signature", styles))

    story.append(Spacer(1, 26))
    story.append(Paragraph("FOR NOTARIAL USE ONLY", styles["SectionHeading"]))
    story.append(
        Paragraph(
            "Sworn/affirmed before me this ____ day of ______________, "
            "20____.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 20))
    story.append(Paragraph("_______________________________", styles["SignatureLabel"]))
    story.append(Paragraph("Notary Public / Oath Commissioner Signature and Seal", styles["SignatureLabel"]))

    _add_disclaimer_footer(story, styles, text=AFFIDAVIT_DISCLAIMER)
    return story


_BUILDERS = {
    "legal_notice": _build_legal_notice,
    "nda": _build_nda,
    "rental_agreement": _build_rental_agreement,
    "complaint_letter": _build_complaint_letter,
    "affidavit": _build_affidavit,
}


def generate_pdf(document_type, data, output_folder):
    """
    Generate a legal PDF document of the given type.

    Args:
        document_type (str): One of DOCUMENT_TYPES keys.
        data (dict): Form data used to populate the document.
        output_folder (str): Directory to save the generated PDF in.

    Returns:
        str: The filename (not full path) of the generated PDF.

    Raises:
        ValueError: If document_type is not supported.
    """
    if document_type not in _BUILDERS:
        raise ValueError(f"Unsupported document type: {document_type}")

    styles = _get_styles()
    filename = f"{document_type}_{os.urandom(4).hex()}.pdf"
    output_path = os.path.join(output_folder, filename)

    doc = _base_doc(output_path)
    story = _BUILDERS[document_type](data, styles)
    doc.build(story)

    return filename
