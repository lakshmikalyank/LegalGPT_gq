/**
 * uploads.js
 * Handles the upload dropzone and document deletion on the
 * document management page (uploads.html).
 */

document.addEventListener("DOMContentLoaded", () => {
    initDropzone();
    initDeleteButtons();
});

/**
 * Wires up the upload dropzone: click-to-browse, drag-and-drop, and
 * submits the selected file to /upload via fetch.
 */
function initDropzone() {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");

    dropzone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            uploadFile(fileInput.files[0]);
        }
    });

    ["dragover", "dragleave", "drop"].forEach((eventName) => {
        dropzone.addEventListener(eventName, (e) => e.preventDefault());
    });

    dropzone.addEventListener("dragover", () => dropzone.classList.add("dragover"));
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
}

/**
 * Uploads a file to the server. On success, reloads the page so the
 * new document appears in the paginated table with accurate stats.
 * @param {File} file
 */
function uploadFile(file) {
    const statusDiv = document.getElementById("uploadStatus");
    statusDiv.innerHTML = `
        <div class="d-flex align-items-center text-muted small">
            <div class="spinner-border spinner-border-sm me-2" role="status"></div>
            Uploading and processing "${file.name}"...
        </div>`;

    const formData = new FormData();
    formData.append("file", file);

    fetch("/upload", { method: "POST", body: formData })
        .then((res) => res.json())
        .then((data) => {
            if (data.success) {
                statusDiv.innerHTML = `<div class="text-success small"><i class="bi bi-check-circle"></i> ${data.message}</div>`;
                setTimeout(() => window.location.reload(), 900);
            } else {
                statusDiv.innerHTML = `<div class="text-danger small"><i class="bi bi-x-circle"></i> ${data.message}</div>`;
            }
        })
        .catch(() => {
            statusDiv.innerHTML = `<div class="text-danger small">Upload failed. Please try again.</div>`;
        });
}

/**
 * Wires up delete buttons for each document row in the table.
 */
function initDeleteButtons() {
    document.querySelectorAll(".delete-upload-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const docId = btn.dataset.docId;
            deleteDocument(docId);
        });
    });
}

/**
 * Deletes a document after confirmation and removes its table row.
 * @param {string|number} docId
 */
function deleteDocument(docId) {
    if (!confirm("Delete this document? This cannot be undone.")) return;

    fetch(`/documents/${docId}/delete`, { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (data.success) {
                const row = document.getElementById(`row-doc-${docId}`);
                if (row) row.remove();
            } else {
                alert(data.message || "Failed to delete document.");
            }
        })
        .catch(() => {
            alert("Failed to reach the server.");
        });
}