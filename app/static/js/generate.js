/**
 * generate.js
 * Handles switching between document-type field sets, submitting the
 * generation form via AJAX, and emailing the resulting PDF.
 */

let lastGeneratedDocId = null;

document.addEventListener("DOMContentLoaded", () => {
    initTypeSwitcher();
    initFormSubmit();
    initEmailModal();
});

/**
 * Shows only the field set matching the currently selected document type.
 */
function initTypeSwitcher() {
    const typeSelect = document.getElementById("documentType");

    const showFieldsFor = (type) => {
        document.querySelectorAll(".doc-fields").forEach((el) => {
            el.classList.toggle("d-none", el.dataset.type !== type);
        });
    };

    typeSelect.addEventListener("change", () => showFieldsFor(typeSelect.value));
    showFieldsFor(typeSelect.value);
}

/**
 * Submits the visible field set to /generate/<type> and renders the result.
 */
function initFormSubmit() {
    const form = document.getElementById("generateForm");

    form.addEventListener("submit", (e) => {
        e.preventDefault();

        const type = document.getElementById("documentType").value;
        const visibleFieldSet = document.querySelector(`.doc-fields[data-type="${type}"]`);
        const formData = new FormData();

        visibleFieldSet.querySelectorAll("input, textarea").forEach((field) => {
            formData.append(field.name, field.value);
        });

        const resultDiv = document.getElementById("generateResult");
        resultDiv.innerHTML = `
            <div class="text-muted py-5">
                <div class="spinner-border spinner-border-sm me-2"></div> Generating document...
            </div>`;

        fetch(`/generate/${type}`, { method: "POST", body: formData })
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    renderGeneratedResult(data.document);
                } else {
                    resultDiv.innerHTML = `<div class="text-danger py-4">${data.message}</div>`;
                }
            })
            .catch(() => {
                resultDiv.innerHTML = `<div class="text-danger py-4">Failed to reach the server.</div>`;
            });
    });
}

/**
 * Renders the generated-document result card with download/email actions.
 * @param {{id: number, title: string, download_url: string}} doc
 */
function renderGeneratedResult(doc) {
    lastGeneratedDocId = doc.id;
    const resultDiv = document.getElementById("generateResult");

    resultDiv.innerHTML = `
        <div class="text-start">
            <div class="d-flex align-items-center mb-3">
                <div class="stat-icon icon-green me-2" style="width:42px;height:42px;">
                    <i class="bi bi-check-circle"></i>
                </div>
                <div>
                    <div class="fw-semibold">${doc.title}</div>
                    <div class="text-muted small">Generated successfully</div>
                </div>
            </div>
            <a href="${doc.download_url}" class="btn btn-success w-100 mb-2">
                <i class="bi bi-download"></i> Download PDF
            </a>
            <button class="btn btn-outline-primary w-100" data-bs-toggle="modal" data-bs-target="#emailModal">
                <i class="bi bi-envelope"></i> Email this Document
            </button>
        </div>
    `;
}

/**
 * Wires up the "Send" button inside the email modal.
 */
function initEmailModal() {
    document.getElementById("sendEmailBtn").addEventListener("click", () => {
        const email = document.getElementById("emailRecipient").value.trim();
        const statusDiv = document.getElementById("emailStatus");

        if (!email) {
            statusDiv.innerHTML = `<div class="text-danger small">Please enter a recipient email.</div>`;
            return;
        }
        if (!lastGeneratedDocId) {
            statusDiv.innerHTML = `<div class="text-danger small">Generate a document first.</div>`;
            return;
        }

        statusDiv.innerHTML = `<div class="text-muted small"><div class="spinner-border spinner-border-sm me-2"></div>Sending...</div>`;

        fetch(`/generated/${lastGeneratedDocId}/email`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
        })
            .then((res) => res.json())
            .then((data) => {
                statusDiv.innerHTML = data.success
                    ? `<div class="text-success small"><i class="bi bi-check-circle"></i> ${data.message}</div>`
                    : `<div class="text-danger small"><i class="bi bi-x-circle"></i> ${data.message}</div>`;
            })
            .catch(() => {
                statusDiv.innerHTML = `<div class="text-danger small">Failed to send email.</div>`;
            });
    });
}