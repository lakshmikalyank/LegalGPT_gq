/**
 * summary.js
 * Drives the lightweight "Generate Summary" modal — a one-click way to
 * get just the Simple Summary without opening the full Document
 * Analysis modal. Reuses the existing /documents/<id>/analyze endpoint
 * (mode: "summary") — no new route, no duplicated LLM logic.
 *
 * Shared by uploads.html and chat.html, same as analyze.js. Kept in
 * its own file and using its own state variables so it never
 * interferes with the existing Document Analysis feature.
 */

let currentSummaryDocId = null;
let currentSummaryLanguage = "en";
let lastSummaryText = null;

// Speech tag map scoped to summary.js's 4 supported languages. Named
// distinctly from analyze.js's LANGUAGE_SPEECH_TAGS since both files
// run in the same global script scope on this page (no modules), and
// two top-level `const` declarations with the same name would throw.
const SUMMARY_LANGUAGE_SPEECH_TAGS = {
    en: "en-US",
    te: "te-IN",
    hi: "hi-IN",
    ta: "ta-IN",
};

document.addEventListener("DOMContentLoaded", () => {
    initSummaryButtons();
    initSummaryLanguageSelect();
    initSummaryVoice();
    initSummaryModalReset();
});

/**
 * Wires up every "Generate Summary" button via event delegation, so
 * dynamically added documents (e.g. a newly uploaded one) are handled
 * automatically without a second init call.
 */
function initSummaryButtons() {
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".generate-summary-btn");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        const docId = btn.dataset.docId;
        if (docId) {
            currentSummaryDocId = docId;
            generateSummary(docId, currentSummaryLanguage);
        }
    });
}

/**
 * Wires up the language dropdown inside the summary modal. Changing
 * the language re-generates the summary for the currently open
 * document in the newly selected language.
 */
function initSummaryLanguageSelect() {
    const select = document.getElementById("summaryLanguageSelect");
    if (!select) return;

    select.addEventListener("change", () => {
        if (!currentSummaryDocId) return;

        currentSummaryLanguage = select.value;
        generateSummary(currentSummaryDocId, currentSummaryLanguage);
    });
}

/**
 * Resets the summary modal back to its initial state whenever it is
 * closed, so reopening it for a different document never shows a
 * stale summary or a leftover error.
 */
function initSummaryModalReset() {
    const modalEl = document.getElementById("summaryModal");
    if (!modalEl) return;

    modalEl.addEventListener("hidden.bs.modal", () => {
        stopSummaryReading();
        setSummaryModalState("idle");
        currentSummaryDocId = null;
        currentSummaryLanguage = "en";
        lastSummaryText = null;

        const select = document.getElementById("summaryLanguageSelect");
        if (select) select.value = "en";
    });
}

/**
 * Opens the summary modal, shows the loading state, calls the existing
 * analyze endpoint in summary mode with the given language, and
 * renders just the summary text.
 * @param {string|number} documentId
 * @param {string} language - a language code, e.g. "en", "te", "hi", "ta"
 */
function generateSummary(documentId, language) {
    const modalEl = document.getElementById("summaryModal");
    if (!modalEl) return;

    // Stop any speech from a previous summary before loading a new one.
    stopSummaryReading();

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    setSummaryModalState("loading");
    modal.show();

    fetch(`/documents/${documentId}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "summary", language }),
    })
        .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (ok && data.success) {
                showSummaryText(data.analysis.summary, data.analysis.truncated);
            } else {
                showSummaryError(data.message || "Failed to generate summary. Please try again.");
            }
        })
        .catch(() => {
            showSummaryError("Failed to reach the server. Please check your connection and try again.");
        });
}

/**
 * Switches the summary modal between its visual states: idle, loading,
 * error, or result. Only one is visible at a time.
 * @param {"idle"|"loading"|"error"|"result"} state
 */
function setSummaryModalState(state) {
    const loading = document.getElementById("summaryLoading");
    const error = document.getElementById("summaryError");
    const result = document.getElementById("summaryResult");

    loading.classList.add("d-none");
    error.classList.add("d-none");
    result.classList.add("d-none");

    if (state === "loading") {
        loading.classList.remove("d-none");
    } else if (state === "error") {
        error.classList.remove("d-none");
    } else if (state === "result") {
        result.classList.remove("d-none");
    }
    // "idle" leaves everything hidden, ready for the next open.
}

/**
 * Displays the generated summary text.
 * @param {string} summary
 */
function showSummaryText(summary, truncated) {
    const textEl = document.getElementById("summaryText");
    const resultEl = document.getElementById("summaryResult");
    lastSummaryText = summary || "No summary was returned for this document.";

    const existingWarning = resultEl.querySelector(".summary-truncation-warning");
    if (existingWarning) existingWarning.remove();

    if (truncated) {
        const warning = document.createElement("div");
        warning.className = "summary-truncation-warning";
        warning.innerHTML = `
            <i class="bi bi-exclamation-triangle-fill"></i>
            <span>This document is very long — the summary may not cover the full text.</span>
        `;
        resultEl.insertBefore(warning, textEl);
    }

    textEl.textContent = lastSummaryText;
    setSummaryModalState("result");
}

/**
 * Displays an error message inside the summary modal.
 * @param {string} message
 */
function showSummaryError(message) {
    const errorDiv = document.getElementById("summaryError");
    errorDiv.innerHTML = `
        <i class="bi bi-exclamation-triangle" style="font-size: 1.6rem;"></i>
        <p class="mt-2 mb-0">${message}</p>
    `;
    setSummaryModalState("error");
}

// ==========================================================================
// Voice Reading (browser built-in SpeechSynthesis API)
// ==========================================================================

/**
 * Wires up the Play and Stop buttons in the summary modal. Uses the
 * browser's native speechSynthesis API — no backend call, no external
 * paid service.
 */
function initSummaryVoice() {
    const playBtn = document.getElementById("summaryPlayBtn");
    const stopBtn = document.getElementById("summaryStopBtn");
    if (!playBtn || !stopBtn) return;

    if (!("speechSynthesis" in window)) {
        playBtn.disabled = true;
        playBtn.title = "Text-to-speech is not supported in this browser.";
        return;
    }

    playBtn.addEventListener("click", () => {
        if (lastSummaryText) {
            playSummary(lastSummaryText, currentSummaryLanguage);
        }
    });

    stopBtn.addEventListener("click", stopSummaryReading);
}

/**
 * Speaks the given summary text aloud, in the given language when a
 * matching voice is available. Stops any speech already in progress
 * first, so only one summary is ever read at a time.
 * @param {string} text
 * @param {string} languageCode
 */
function playSummary(text, languageCode) {
    if (!("speechSynthesis" in window) || !text) return;

    stopSummaryReading();

    const utterance = new SpeechSynthesisUtterance(text);
    const speechTag = SUMMARY_LANGUAGE_SPEECH_TAGS[languageCode] || "en-US";
    utterance.lang = speechTag;

    const matchingVoice = window.speechSynthesis
        .getVoices()
        .find((voice) => voice.lang === speechTag || voice.lang.startsWith(languageCode));
    if (matchingVoice) {
        utterance.voice = matchingVoice;
    }

    utterance.onstart = () => setSummaryReadingState(true);
    utterance.onend = () => setSummaryReadingState(false);
    utterance.onerror = () => setSummaryReadingState(false);

    window.speechSynthesis.speak(utterance);
}

/**
 * Cancels any in-progress speech and resets the Play/Stop button states.
 */
function stopSummaryReading() {
    if ("speechSynthesis" in window && window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
    }
    setSummaryReadingState(false);
}

/**
 * Toggles the Play / Stop button visibility based on whether speech is
 * currently playing.
 * @param {boolean} isReading
 */
function setSummaryReadingState(isReading) {
    const playBtn = document.getElementById("summaryPlayBtn");
    const stopBtn = document.getElementById("summaryStopBtn");
    if (!playBtn || !stopBtn) return;

    playBtn.classList.toggle("d-none", isReading);
    stopBtn.classList.toggle("d-none", !isReading);
}