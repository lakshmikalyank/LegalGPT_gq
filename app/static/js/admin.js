/**
 * admin.js
 * Loads platform-wide chat history into the admin panel via
 * /api/admin/chat-history.
 */

document.addEventListener("DOMContentLoaded", () => {
    loadAdminChatHistory();
    document.getElementById("refreshChatBtn").addEventListener("click", loadAdminChatHistory);
    initUserManagement();
    initAdvocateManagement();
});

/**
 * Fetches and renders the most recent chat exchanges across all users.
 */
function loadAdminChatHistory() {
    const container = document.getElementById("adminChatHistory");
    container.innerHTML = `
        <div class="text-center text-muted py-4">
            <div class="spinner-border spinner-border-sm me-2"></div> Loading chat history...
        </div>`;

    fetch("/api/admin/chat-history")
        .then((res) => res.json())
        .then((data) => {
            if (!data.success || data.history.length === 0) {
                container.innerHTML = `<p class="text-muted small text-center py-4 mb-0">No chat activity yet.</p>`;
                return;
            }
            container.innerHTML = "";
            data.history.forEach((entry) => {
                const row = document.createElement("div");
                row.className = "mb-3 pb-3 border-bottom";
                row.innerHTML = `
                    <div class="d-flex justify-content-between">
                        <span class="fw-semibold small"><i class="bi bi-person-circle"></i> ${entry.user}</span>
                        <span class="text-muted small">${new Date(entry.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="small mt-1"><strong>Q:</strong> ${entry.question}</div>
                    <div class="small text-muted"><strong>A:</strong> ${entry.answer}</div>
                `;
                container.appendChild(row);
            });
        })
        .catch(() => {
            container.innerHTML = `<p class="text-danger small text-center py-4 mb-0">Failed to load chat history.</p>`;
        });
}

// ==========================================================================
// User Management
// ==========================================================================

function initUserManagement() {
    document.addEventListener("click", (e) => {
        const toggleBtn = e.target.closest(".toggle-role-btn");
        if (toggleBtn) {
            toggleUserRole(toggleBtn.dataset.userId);
            return;
        }
        const deleteBtn = e.target.closest(".delete-user-btn");
        if (deleteBtn) {
            deleteUser(deleteBtn.dataset.userId);
        }
    });
}

function toggleUserRole(userId) {
    fetch(`/admin/users/${userId}/toggle-admin`, { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (!data.success) {
                alert(data.message || "Failed to update user role.");
                return;
            }
            const row = document.getElementById(`user-row-${userId}`);
            const badge = row.querySelector(".user-role-badge");
            badge.textContent = data.is_admin ? "Admin" : "User";
            badge.classList.toggle("bg-danger", data.is_admin);
            badge.classList.toggle("bg-secondary", !data.is_admin);
        })
        .catch(() => alert("Failed to reach the server."));
}

function deleteUser(userId) {
    if (!confirm("Delete this user and all their data? This cannot be undone.")) return;

    fetch(`/admin/users/${userId}/delete`, { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (!data.success) {
                alert(data.message || "Failed to delete user.");
                return;
            }
            const row = document.getElementById(`user-row-${userId}`);
            if (row) row.remove();
        })
        .catch(() => alert("Failed to reach the server."));
}

// ==========================================================================
// Advocate Management
// ==========================================================================

function initAdvocateManagement() {
    const modalEl = document.getElementById("advocateModal");
    const form = document.getElementById("advocateForm");

    document.getElementById("addAdvocateBtn").addEventListener("click", () => {
        resetAdvocateForm();
        document.getElementById("advocateModalTitle").textContent = "Add Advocate";
    });

    document.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-advocate-btn");
        if (editBtn) {
            openAdvocateEditForm(editBtn.dataset.advocateId);
            return;
        }
        const deleteBtn = e.target.closest(".delete-advocate-btn");
        if (deleteBtn) {
            deleteAdvocate(deleteBtn.dataset.advocateId);
        }
    });

    modalEl.addEventListener("hidden.bs.modal", resetAdvocateForm);

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        saveAdvocate();
    });
}

function resetAdvocateForm() {
    document.getElementById("advocateId").value = "";
    document.getElementById("advocateName").value = "";
    document.getElementById("advocateCity").value = "";
    document.getElementById("advocateSpecialization").value = "";
    document.getElementById("advocateExperience").value = "0";
    document.getElementById("advocateRating").value = "0";
    document.getElementById("advocatePhone").value = "";
    document.getElementById("advocateEmail").value = "";
    document.getElementById("advocateFormStatus").innerHTML = "";
    document.getElementById("advocateModalTitle").textContent = "Add Advocate";
}

function openAdvocateEditForm(advocateId) {
    const row = document.getElementById(`advocate-row-${advocateId}`);
    if (!row) return;

    document.getElementById("advocateId").value = advocateId;
    document.getElementById("advocateName").value = row.dataset.name;
    document.getElementById("advocateCity").value = row.dataset.city;
    document.getElementById("advocateSpecialization").value = row.dataset.specialization;
    document.getElementById("advocateExperience").value = row.dataset.experience;
    document.getElementById("advocateRating").value = row.dataset.rating;
    document.getElementById("advocatePhone").value = row.dataset.phone;
    document.getElementById("advocateEmail").value = row.dataset.email;
    document.getElementById("advocateModalTitle").textContent = "Edit Advocate";

    bootstrap.Modal.getOrCreateInstance(document.getElementById("advocateModal")).show();
}

function saveAdvocate() {
    const advocateId = document.getElementById("advocateId").value;
    const statusDiv = document.getElementById("advocateFormStatus");

    const formData = new FormData();
    formData.append("name", document.getElementById("advocateName").value.trim());
    formData.append("city", document.getElementById("advocateCity").value.trim());
    formData.append("specialization", document.getElementById("advocateSpecialization").value.trim());
    formData.append("experience_years", document.getElementById("advocateExperience").value);
    formData.append("rating", document.getElementById("advocateRating").value);
    formData.append("phone", document.getElementById("advocatePhone").value.trim());
    formData.append("email", document.getElementById("advocateEmail").value.trim());

    const url = advocateId
        ? `/admin/advocates/${advocateId}/update`
        : "/admin/advocates";

    fetch(url, { method: "POST", body: formData })
        .then((res) => res.json())
        .then((data) => {
            if (!data.success) {
                statusDiv.innerHTML = `<div class="text-danger small mt-2">${data.message}</div>`;
                return;
            }
            bootstrap.Modal.getInstance(document.getElementById("advocateModal")).hide();
            window.location.reload();
        })
        .catch(() => {
            statusDiv.innerHTML = `<div class="text-danger small mt-2">Failed to reach the server.</div>`;
        });
}

function deleteAdvocate(advocateId) {
    if (!confirm("Delete this advocate from the directory?")) return;

    fetch(`/admin/advocates/${advocateId}/delete`, { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (!data.success) {
                alert(data.message || "Failed to delete advocate.");
                return;
            }
            const row = document.getElementById(`advocate-row-${advocateId}`);
            if (row) row.remove();
        })
        .catch(() => alert("Failed to reach the server."));
}extract_text()