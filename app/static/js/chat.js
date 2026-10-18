/**
 * chat.js
 * Handles document upload, AI chat messaging (AJAX), the typing
 * animation, and document deletion on the chat page.
 */

let activeDocumentId = "";

document.addEventListener("DOMContentLoaded", () => {
    initDropzone();
    initDocumentSelection();
    initChatInput();
    initDeleteButtons();
    initClearChat();
    loadChatHistory();
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
 * Uploads a file to the server and refreshes the document list on success.
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
                addDocumentToSidebar(data.document);
                setTimeout(() => {
                    const modal = bootstrap.Modal.getInstance(document.getElementById("uploadModal"));
                    if (modal) modal.hide();
                    statusDiv.innerHTML = "";
                }, 1200);
            } else {
                statusDiv.innerHTML = `<div class="text-danger small"><i class="bi bi-x-circle"></i> ${data.message}</div>`;
            }
        })
        .catch(() => {
            statusDiv.innerHTML = `<div class="text-danger small">Upload failed. Please try again.</div>`;
        });
}

/**
 * Appends a newly uploaded document to the sidebar list without a page reload.
 * @param {{id: number, filename: string, file_type: string}} doc
 */
function addDocumentToSidebar(doc) {
    const list = document.getElementById("documentList");
    const emptyMsg = list.querySelector("p");
    if (emptyMsg) emptyMsg.remove();

    const icon = doc.file_type === "pdf" ? "bi-file-earmark-pdf" : (doc.file_type === "docx" ? "bi-file-earmark-word" : "bi-file-earmark-image");
    const item = document.createElement("div");
    item.className = "chat-doc-item";
    item.id = `doc-${doc.id}`;
    item.dataset.docId = doc.id;
    item.innerHTML = `
        <i class="bi ${icon}"></i>
        <span class="text-truncate" style="max-width: 190px;" title="${doc.filename}">${doc.filename}</span>
        <i class="bi bi-trash text-danger ms-auto delete-doc-btn" data-doc-id="${doc.id}"
           style="font-size: 0.8rem;" title="Delete document"></i>
    `;
    list.appendChild(item);

    item.addEventListener("click", (e) => {
        if (!e.target.classList.contains("delete-doc-btn")) selectDocument(doc.id, item);
    });
    item.querySelector(".delete-doc-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteDocument(doc.id, item);
    });
}

/**
 * Sets up click handlers for selecting a document (or "All Documents")
 * to scope chat questions to.
 */
function initDocumentSelection() {
    document.querySelectorAll(".chat-doc-item").forEach((item) => {
        item.addEventListener("click", (e) => {
            if (e.target.classList.contains("delete-doc-btn")) return;
            selectDocument(item.dataset.docId || "", item);
        });
    });
}

/**
 * Marks a document as active in the sidebar and reloads chat history
 * scoped to that document.
 */
function selectDocument(docId, itemEl) {
    activeDocumentId = docId;
    document.querySelectorAll(".chat-doc-item").forEach((el) => el.classList.remove("active"));
    itemEl.classList.add("active");
    loadChatHistory();
}

/**
 * Sets up the chat input box and send button.
 */
function initChatInput() {
    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("sendBtn");

    sendBtn.addEventListener("click", sendMessage);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendMessage();
    });
}

/**
 * Wires up the Clear Chat button: confirms with the user, deletes the
 * currently displayed chat history (scoped to the active document, or
 * all history if "All Documents" is selected), and clears the chat
 * window immediately on success — no page refresh needed.
 */
function initClearChat() {
    const clearBtn = document.getElementById("clearChatBtn");
    if (!clearBtn) return;

    clearBtn.addEventListener("click", () => {
        const confirmed = confirm(
            "Clear this chat history? This cannot be undone. " +
            "Your uploaded documents and their analysis will not be affected."
        );
        if (!confirmed) return;

        fetch("/chat/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ document_id: activeDocumentId || null }),
        })
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    clearChatWindow();
                } else {
                    alert(data.message || "Failed to clear chat history.");
                }
            })
            .catch(() => {
                alert("Failed to reach the server. Please try again.");
            });
    });
}

/**
 * Empties the chat window and restores the initial empty state, without
 * requiring a page reload.
 */
function clearChatWindow() {
    const messages = document.getElementById("chatMessages");
    messages.innerHTML = `
        <div class="text-center text-muted py-5" id="chatEmptyState">
            <i class="bi bi-robot" style="font-size: 2.2rem;"></i>
            <p class="mt-2 mb-0">Ask me anything about your uploaded documents.</p>
        </div>`;
}

/**
 * Sends the current chat input as a question to /chat/ask and renders
 * the response, including a typing animation while waiting.
 */
function sendMessage() {
    const input = document.getElementById("chatInput");
    const question = input.value.trim();
    if (!question) return;

    appendMessage(question, "user");
    input.value = "";
    removeEmptyState();

    const typingEl = appendTypingIndicator();

    fetch("/chat/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, document_id: activeDocumentId || null }),
    })
        .then((res) => res.json())
        .then((data) => {
            typingEl.remove();
            if (data.success) {
                appendMessage(data.answer, "assistant");
            } else {
                appendMessage(data.message || "Something went wrong.", "assistant");
            }
        })
        .catch(() => {
            typingEl.remove();
            appendMessage("Failed to reach the server. Please try again.", "assistant");
        });
}

/**
 * Appends a chat bubble to the message area and scrolls to the bottom.
 */
function appendMessage(text, sender) {
    const messages = document.getElementById("chatMessages");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;

    const textSpan = document.createElement("span");
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    if (sender === "assistant" && "speechSynthesis" in window) {
        const speakBtn = document.createElement("button");
        speakBtn.className = "chat-bubble-speak-btn";
        speakBtn.title = "Read aloud";
        speakBtn.innerHTML = `<i class="bi bi-volume-up"></i>`;
        speakBtn.addEventListener("click", () => toggleChatMessageSpeech(text, speakBtn));
        bubble.appendChild(speakBtn);
    }

    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
}

let activeChatUtteranceBtn = null;

/**
 * Plays or stops Read Aloud for a single chat answer. Stops whichever
 * message is currently playing first, so only one plays at a time.
 */
function toggleChatMessageSpeech(text, btn) {
    const wasActive = btn === activeChatUtteranceBtn;

    window.speechSynthesis.cancel();
    if (activeChatUtteranceBtn) {
        activeChatUtteranceBtn.classList.remove("speaking");
        activeChatUtteranceBtn.innerHTML = `<i class="bi bi-volume-up"></i>`;
        activeChatUtteranceBtn = null;
    }

    if (wasActive) return;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.onend = () => {
        if (activeChatUtteranceBtn === btn) {
            btn.classList.remove("speaking");
            btn.innerHTML = `<i class="bi bi-volume-up"></i>`;
            activeChatUtteranceBtn = null;
        }
    };

    btn.classList.add("speaking");
    btn.innerHTML = `<i class="bi bi-stop-fill"></i>`;
    activeChatUtteranceBtn = btn;
    window.speechSynthesis.speak(utterance);
}

/**
 * Appends an animated "assistant is typing" indicator bubble.
 * @returns {HTMLElement} The indicator element, so it can be removed later.
 */
function appendTypingIndicator() {
    const messages = document.getElementById("chatMessages");
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble assistant typing-indicator";
    bubble.innerHTML = "<span></span><span></span><span></span>";
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
}

/**
 * Hides the "ask me anything" empty state once the conversation starts.
 */
function removeEmptyState() {
    const emptyState = document.getElementById("chatEmptyState");
    if (emptyState) emptyState.remove();
}

/**
 * Loads and renders chat history, optionally scoped to the active document.
 */
function loadChatHistory() {
    const messages = document.getElementById("chatMessages");
    const url = activeDocumentId
        ? `/chat/history?document_id=${encodeURIComponent(activeDocumentId)}`
        : "/chat/history";

    fetch(url)
        .then((res) => res.json())
        .then((data) => {
            messages.innerHTML = "";
            if (!data.success || data.history.length === 0) {
                messages.innerHTML = `
                    <div class="text-center text-muted py-5" id="chatEmptyState">
                        <i class="bi bi-robot" style="font-size: 2.2rem;"></i>
                        <p class="mt-2 mb-0">Ask me anything about your uploaded documents.</p>
                    </div>`;
                return;
            }
            data.history.forEach((entry) => {
                appendMessage(entry.question, "user");
                appendMessage(entry.answer, "assistant");
            });
        });
}

/**
 * Wires up delete buttons for documents already present at page load.
 */
function initDeleteButtons() {
    document.querySelectorAll(".delete-doc-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const docId = btn.dataset.docId;
            const item = document.getElementById(`doc-${docId}`);
            deleteDocument(docId, item);
        });
    });
}

/**
 * Deletes a document after confirmation and removes it from the sidebar.
 */
function deleteDocument(docId, itemEl) {
    if (!confirm("Delete this document? This cannot be undone.")) return;

    fetch(`/documents/${docId}/delete`, { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (data.success) {
                itemEl.remove();
                if (activeDocumentId == docId) {
                    activeDocumentId = "";
                    loadChatHistory();
                }
            } else {
                alert(data.message || "Failed to delete document.");
            }
        });
}