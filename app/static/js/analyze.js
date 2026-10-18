/**
 * analyze.js
 * Drives the Document Analysis modal: triggers the analysis request,
 * manages loading/error/result states, handles the Summary/Full mode
 * toggle, and renders the structured backend response into cards.
 *
 * Shared by uploads.html (table row actions) and chat.html (sidebar
 * document list) — both use the same #analysisModal markup and
 * .analyze-doc-btn trigger class, so this file only needs to be
 * written once.
 */

let currentAnalysisDocId = null;
let currentAnalysisMode = "full";
let currentAnalysisLanguage = "en";
let lastRenderedAnalysis = null;

// Maps each supported language code to a BCP-47 speech tag so the
// synthesized voice matches the selected analysis language, when the
// browser/OS has a matching voice installed. Falls back to the
// browser's default voice if no matching voice is available.
const LANGUAGE_SPEECH_TAGS = {
    en: "en-US",
    hi: "hi-IN",
    ta: "ta-IN",
    te: "te-IN",
    kn: "kn-IN",
    bn: "bn-IN",
    mr: "mr-IN",
    gu: "gu-IN",
    ml: "ml-IN",
    pa: "pa-IN",
    ur: "ur-IN",
};

document.addEventListener("DOMContentLoaded", () => {
    initAnalyzeButtons();
    initModeToggle();
    initLanguageSelect();
    initReadAloud();
    initAnalysisModalReset();
});

/**
 * Wires up every "Analyze" button on the page via event delegation, so
 * buttons added dynamically later (e.g. a newly uploaded document) are
 * automatically handled too.
 */
function initAnalyzeButtons() {
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".analyze-doc-btn");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        const docId = btn.dataset.docId;
        if (docId) {
            currentAnalysisDocId = docId;
            runDocumentAnalysis(docId, currentAnalysisMode, currentAnalysisLanguage);
        }
    });
}

/**
 * Wires up the Summary/Full toggle buttons inside the modal. Switching
 * mode re-runs analysis for the currently open document with the newly
 * selected mode.
 */
function initModeToggle() {
    const toggle = document.getElementById("analysisModeToggle");
    if (!toggle) return;

    toggle.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-mode]");
        if (!btn || !currentAnalysisDocId) return;

        const selectedMode = btn.dataset.mode;
        if (selectedMode === currentAnalysisMode) return;

        currentAnalysisMode = selectedMode;
        setActiveModeButton(selectedMode);
        runDocumentAnalysis(currentAnalysisDocId, currentAnalysisMode, currentAnalysisLanguage);
    });
}

/**
 * Wires up the language dropdown. Changing the language re-runs
 * analysis for the currently open document with the newly selected
 * language, keeping the current mode unchanged.
 */
function initLanguageSelect() {
    const select = document.getElementById("analysisLanguageSelect");
    if (!select) return;

    select.addEventListener("change", () => {
        if (!currentAnalysisDocId) return;

        currentAnalysisLanguage = select.value;
        runDocumentAnalysis(currentAnalysisDocId, currentAnalysisMode, currentAnalysisLanguage);
    });
}

/**
 * Updates which toggle button shows as active.
 * @param {"summary"|"full"} mode
 */
function setActiveModeButton(mode) {
    const toggle = document.getElementById("analysisModeToggle");
    if (!toggle) return;

    toggle.querySelectorAll("button[data-mode]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
    });
}

/**
 * Resets the analysis modal back to its initial state whenever it is
 * closed, so reopening it for a different document never shows stale
 * results, a leftover error, a stuck spinner, or the wrong mode.
 */
function initAnalysisModalReset() {
    const modalEl = document.getElementById("analysisModal");
    if (!modalEl) return;

    modalEl.addEventListener("hidden.bs.modal", () => {
        if (activeAnalysisController) {
            activeAnalysisController.abort();
            activeAnalysisController = null;
        }
        stopReading();
        setAnalysisModalState("idle");
        currentAnalysisDocId = null;
        currentAnalysisMode = "full";
        currentAnalysisLanguage = "en";
        lastRenderedAnalysis = null;
        setActiveModeButton("full");

        const select = document.getElementById("analysisLanguageSelect");
        if (select) select.value = "en";
    });
}

/**
 * Opens the analysis modal (if not already open), shows the loading
 * state, calls the backend endpoint with the given mode and language,
 * and renders the result or an error.
 * @param {string|number} documentId
 * @param {"full"|"summary"} mode
 * @param {string} language - a language code from the dropdown, e.g. "hi"
 */
let activeAnalysisController = null;

function runDocumentAnalysis(documentId, mode, language) {
    const modalEl = document.getElementById("analysisModal");
    if (!modalEl) return;

    // Cancel any previous request still in flight, so a slow, stale
    // response (e.g. from a language switched away from) can never
    // arrive after a newer one and overwrite the modal.
    if (activeAnalysisController) {
        activeAnalysisController.abort();
    }
    const controller = new AbortController();
    activeAnalysisController = controller;

    // Stop any speech from a previous analysis before loading a new one.
    stopReading();

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    setAnalysisModalState("loading");
    modal.show();

    fetch(`/documents/${documentId}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, language }),
        signal: controller.signal,
    })
        .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (controller !== activeAnalysisController) return; // superseded, ignore
            if (ok && data.success) {
                lastRenderedAnalysis = data.analysis;
                renderAnalysisCards(data.analysis);
                setAnalysisModalState("result");
            } else {
                showAnalysisError(data.message || "Analysis failed. Please try again.");
            }
        })
        .catch((err) => {
            if (err.name === "AbortError") return; // expected when superseded
            if (controller !== activeAnalysisController) return;
            showAnalysisError("Failed to reach the server. Please check your connection and try again.");
        });
}

/**
 * Switches the modal between its visual states: idle, loading, error,
 * or result. Only one is ever visible at a time.
 * @param {"idle"|"loading"|"error"|"result"} state
 */
function setAnalysisModalState(state) {
    const loading = document.getElementById("analysisLoading");
    const error = document.getElementById("analysisError");
    const results = document.getElementById("analysisResults");

    loading.classList.add("d-none");
    error.classList.add("d-none");
    results.classList.add("d-none");

    if (state === "loading") {
        loading.innerHTML = `
            <div class="spinner-border spinner-border-sm me-2"></div>
            Analyzing document... this may take a moment.
        `;
        loading.classList.remove("d-none");
    } else if (state === "error") {
        error.classList.remove("d-none");
    } else if (state === "result") {
        results.classList.remove("d-none");
    }
    // "idle" leaves everything hidden, ready for the next open.
}

/**
 * Displays an error message inside the modal's error state.
 * @param {string} message
 */
function showAnalysisError(message) {
    const errorDiv = document.getElementById("analysisError");
    errorDiv.innerHTML = `
        <i class="bi bi-exclamation-triangle" style="font-size: 1.8rem;"></i>
        <p class="mt-2 mb-0">${escapeHtml(message)}</p>
    `;
    setAnalysisModalState("error");
}

/**
 * Renders the analysis sections as cards inside #analysisResults.
 * The backend's response shape depends on mode:
 *   - "summary": { summary, important_dates, mode }
 *   - "full":    { summary, important_dates, people_mentioned,
 *                  actions_required, important_clauses, mode }
 * Only the cards for keys actually present are rendered, so summary
 * mode naturally shows 2 cards and full mode shows 5.
 * @param {Object} analysis
 */
function renderAnalysisCards(analysis) {
    const container = document.getElementById("analysisResults");
    container.innerHTML = "";

    if (analysis.truncated) {
        container.appendChild(buildTruncationWarning());
    }

    container.appendChild(buildSummaryCard(analysis.summary));
    container.appendChild(buildDatesCard(analysis.important_dates));

    // These three keys are only present in "full" mode responses.
    if ("people_mentioned" in analysis) {
        container.appendChild(buildPeopleCard(analysis.people_mentioned));
    }
    if ("actions_required" in analysis) {
        container.appendChild(buildActionsCard(analysis.actions_required));
    }
    if ("important_clauses" in analysis) {
        container.appendChild(buildClausesCard(analysis.important_clauses));
    }
}

/**
 * Builds a warning banner shown when the document was too long to be
 * fully analyzed — only the first portion of the text was sent to the
 * LLM, so the analysis may be incomplete.
 * @returns {HTMLElement}
 */
function buildTruncationWarning() {
    const banner = document.createElement("div");
    banner.className = "analysis-truncation-warning";
    banner.innerHTML = `
        <i class="bi bi-exclamation-triangle-fill"></i>
        <span>This document is very long. Only the first portion was analyzed,
        so some details further in the document may not be reflected here.</span>
    `;
    return banner;
}

/**
 * Card: Simple Summary
 */
function buildSummaryCard(summary) {
    const card = createAnalysisCard("bi-file-text", "Simple Summary", "analysis-card-summary");
    const body = card.querySelector(".analysis-card-body");
    body.innerHTML = `<p class="mb-0">${escapeHtml(summary || "No summary available.")}</p>`;
    return card;
}

/**
 * Card: Important Dates
 */
function buildDatesCard(dates) {
    const card = createAnalysisCard("bi-calendar-event", "Important Dates", "analysis-card-dates");
    const body = card.querySelector(".analysis-card-body");

    const labels = {
        agreement_date: "Agreement Date",
        effective_date: "Effective Date",
        expiry_date: "Expiry Date",
        renewal_date: "Renewal Date",
        payment_deadlines: "Payment Deadlines",
        court_dates: "Court Dates",
    };

    if (!dates || Object.keys(dates).length === 0) {
        body.innerHTML = `<p class="text-muted mb-0">No dates found.</p>`;
        return card;
    }

    const rows = Object.entries(labels)
        .map(([key, label]) => {
            const value = dates[key] || "Not Found";
            const isFound = value !== "Not Found";
            return `
                <div class="date-row">
                    <span class="date-label">${label}</span>
                    <span class="date-value ${isFound ? "" : "text-muted"}">${escapeHtml(value)}</span>
                </div>`;
        })
        .join("");

    body.innerHTML = rows;
    return card;
}

/**
 * Card: People Mentioned (full mode only)
 */
function buildPeopleCard(people) {
    const card = createAnalysisCard("bi-people", "People Mentioned", "analysis-card-people");
    const body = card.querySelector(".analysis-card-body");

    if (!people || people.length === 0) {
        body.innerHTML = `<p class="text-muted mb-0">No people or organizations identified.</p>`;
        return card;
    }

    body.innerHTML = people
        .map(
            (person) => `
            <div class="person-chip">
                <i class="bi bi-person-circle"></i>
                <span class="fw-semibold">${escapeHtml(person.name || "Unknown")}</span>
                ${person.role ? `<span class="badge bg-light text-dark border ms-1">${escapeHtml(person.role)}</span>` : ""}
            </div>`
        )
        .join("");
    return card;
}

/**
 * Card: Actions Required (full mode only)
 */
function buildActionsCard(actions) {
    const card = createAnalysisCard("bi-list-check", "Actions Required", "analysis-card-actions");
    const body = card.querySelector(".analysis-card-body");

    if (!actions || actions.length === 0) {
        body.innerHTML = `<p class="text-muted mb-0">No specific actions identified.</p>`;
        return card;
    }

    body.innerHTML = `
        <ul class="action-list mb-0">
            ${actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}
        </ul>`;
    return card;
}

/**
 * Card: Important Clauses (full mode only)
 */
function buildClausesCard(clauses) {
    const card = createAnalysisCard("bi-journal-text", "Important Clauses", "analysis-card-clauses");
    const body = card.querySelector(".analysis-card-body");

    if (!clauses || clauses.length === 0) {
        body.innerHTML = `<p class="text-muted mb-0">No notable clauses identified.</p>`;
        return card;
    }

    body.innerHTML = clauses
        .map(
            (clause) => `
            <div class="clause-item">
                <div class="clause-name">${escapeHtml(clause.clause_name || "Clause")}</div>
                <div class="clause-explanation">${escapeHtml(clause.explanation || "")}</div>
            </div>`
        )
        .join("");
    return card;
}

/**
 * Builds the shared card shell (icon + title + body container) used
 * by every analysis card.
 * @returns {HTMLElement}
 */
function createAnalysisCard(iconClass, title, extraClass) {
    const card = document.createElement("div");
    card.className = `analysis-card ${extraClass}`;
    card.innerHTML = `
        <div class="analysis-card-header">
            <i class="bi ${iconClass}"></i>
            <span>${title}</span>
        </div>
        <div class="analysis-card-body"></div>
    `;
    return card;
}

/**
 * Escapes HTML special characters to prevent the analysis text
 * (which originates from an LLM) from being interpreted as markup.
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

// ==========================================================================
// Voice / Text-to-Speech (browser built-in SpeechSynthesis API)
// ==========================================================================

/**
 * Wires up the Read Aloud and Stop buttons in the analysis modal.
 * Uses the browser's native speechSynthesis API — no backend call,
 * no external service.
 */
function initReadAloud() {
    const readBtn = document.getElementById("readAloudBtn");
    const stopBtn = document.getElementById("stopReadingBtn");
    if (!readBtn || !stopBtn) return;

    if (!("speechSynthesis" in window)) {
        readBtn.disabled = true;
        readBtn.title = "Text-to-speech is not supported in this browser.";
        return;
    }

    readBtn.addEventListener("click", () => {
        if (lastRenderedAnalysis) {
            speakAnalysis(lastRenderedAnalysis, currentAnalysisLanguage);
        }
    });

    stopBtn.addEventListener("click", stopReading);
}

/**
 * Speaks the given analysis aloud using SpeechSynthesis, in the given
 * language when a matching voice is available.
 * @param {Object} analysis
 * @param {string} languageCode
 */
function speakAnalysis(analysis, languageCode) {
    if (!("speechSynthesis" in window)) return;

    stopReading();

    const text = buildSpeakableText(analysis);
    if (!text) return;

    const utterance = new SpeechSynthesisUtterance(text);
    const speechTag = LANGUAGE_SPEECH_TAGS[languageCode] || "en-US";
    utterance.lang = speechTag;

    const matchingVoice = window.speechSynthesis
        .getVoices()
        .find((voice) => voice.lang === speechTag || voice.lang.startsWith(languageCode));
    if (matchingVoice) {
        utterance.voice = matchingVoice;
    }

    utterance.onstart = () => setReadingState(true);
    utterance.onend = () => setReadingState(false);
    utterance.onerror = () => setReadingState(false);

    window.speechSynthesis.speak(utterance);
}

/**
 * Cancels any in-progress speech and resets the button states.
 */
function stopReading() {
    if ("speechSynthesis" in window && window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
    }
    setReadingState(false);
}

/**
 * Toggles the Read Aloud / Stop button visibility based on whether
 * speech is currently playing.
 * @param {boolean} isReading
 */
function setReadingState(isReading) {
    const readBtn = document.getElementById("readAloudBtn");
    const stopBtn = document.getElementById("stopReadingBtn");
    if (!readBtn || !stopBtn) return;

    readBtn.classList.toggle("d-none", isReading);
    stopBtn.classList.toggle("d-none", !isReading);
}

/**
 * Converts a structured analysis object into plain, speakable text.
 * Only reads sections that are actually present, so it works for both
 * Summary mode (summary + dates) and Full mode (all 5 sections).
 * @param {Object} analysis
 * @returns {string}
 */
function buildSpeakableText(analysis) {
    const parts = [];

    if (analysis.summary) {
        parts.push(`Summary. ${analysis.summary}`);
    }

    if (analysis.important_dates) {
        const labels = {
            agreement_date: "Agreement date",
            effective_date: "Effective date",
            expiry_date: "Expiry date",
            renewal_date: "Renewal date",
            payment_deadlines: "Payment deadlines",
            court_dates: "Court dates",
        };
        const dateLines = Object.entries(labels)
            .map(([key, label]) => {
                const value = analysis.important_dates[key];
                return value && value !== "Not Found" ? `${label}: ${value}` : null;
            })
            .filter(Boolean);

        if (dateLines.length > 0) {
            parts.push(`Important dates. ${dateLines.join(". ")}.`);
        }
    }

    if (Array.isArray(analysis.people_mentioned) && analysis.people_mentioned.length > 0) {
        const peopleLines = analysis.people_mentioned.map((p) =>
            p.role ? `${p.name}, ${p.role}` : p.name
        );
        parts.push(`People mentioned. ${peopleLines.join(". ")}.`);
    }

    if (Array.isArray(analysis.actions_required) && analysis.actions_required.length > 0) {
        parts.push(`Actions required. ${analysis.actions_required.join(". ")}.`);
    }

    if (Array.isArray(analysis.important_clauses) && analysis.important_clauses.length > 0) {
        const clauseLines = analysis.important_clauses.map(
            (c) => `${c.clause_name}. ${c.explanation}`
        );
        parts.push(`Important clauses. ${clauseLines.join(". ")}.`);
    }

    return parts.join(" ");
}