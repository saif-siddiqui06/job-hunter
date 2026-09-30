// Apply Rocket: app shell + the compose flow (source -> details -> email -> confirmed send).
import { $, api, hideNotice, newRequestKey, setBusy, showNotice } from "./util.js";
import { currentView, go, initShell, onViewChange } from "./shell.js";
import { currentProfile, initProfile, saveProfileFields } from "./profile.js";
import { initGmail } from "./gmail.js";
import { getInput, getPreviewUrl, initInput, resetInput } from "./input.js";
import { clearReview, collectDetails, detailsProblem, initReview, renderContext, renderSavedDetails } from "./review.js";
import { initComposer, resetComposer, setMailState, showDraft } from "./composer.js";
import { initHistory, loadHistory } from "./history.js";
import { initBatch } from "./batch.js";
import { initSetup } from "./setup.js";

const STEPS = ["input", "review", "compose"];

const state = {
    step: "input",
    context: null,
    historyId: null,
    sendKey: null,
    edited: false,
    attachTouched: false,
    sent: false,
    sending: false,
};

function goTo(step) {
    state.step = step;
    $("inputCard").hidden = step !== "input";
    $("workspace").hidden = step === "input";
    document.querySelectorAll(".stepper li").forEach((item) => {
        const index = STEPS.indexOf(item.dataset.step);
        item.classList.toggle("active", item.dataset.step === step);
        item.classList.toggle("done", index < STEPS.indexOf(step));
    });
}

function startNewDraft() {
    Object.assign(state, { context: null, historyId: null, sendKey: null, edited: false, attachTouched: false, sent: false });
}

const retryable = (error) => error.status === 0 || error.status === 429 || error.status >= 500;
const selected = (name) => document.querySelector(`input[name="${name}"]:checked`).value;

function renderSourcePeek(label) {
    const url = getPreviewUrl();
    const text = getInput().text.trim().replace(/\s+/g, " ");
    $("sourcePeekImage").hidden = !url;
    if (url) $("sourcePeekImage").src = url;
    $("sourcePeekText").textContent = label || (url ? `Screenshot${text ? " + your note" : ""}` : text.slice(0, 120));
}

async function analyze() {
    const input = getInput();
    const text = input.text.trim();
    const notice = $("inputNotice");
    hideNotice(notice);
    if (!input.file && text.replace(/\s/g, "").length < 10) {
        showNotice(notice, "error", "Paste a message or job post, or add a screenshot first.");
        $("pasteInput").focus();
        return;
    }

    const button = $("analyzeBtn");
    if (button.disabled) return;
    setBusy(button, true, input.file ? "Reading screenshot" : "Analyzing");
    $("inputCard").setAttribute("aria-busy", "true");
    try {
        const senderEmail = (currentProfile() && currentProfile().email) || "";
        let data;
        if (input.file) {
            const form = new FormData();
            form.append("screenshot", input.file, input.file.name);
            if (senderEmail) form.append("senderEmail", senderEmail);
            data = await api("/api/email-assistant/extract", { method: "POST", form });
        } else {
            data = await api("/api/email-assistant/extract", { method: "POST", json: { text, senderEmail } });
        }
        startNewDraft();
        state.context = data.context;
        resetComposer();
        renderContext(data.context, currentProfile());
        if (input.file && text) $("ctxNote").value = text.slice(0, 1000);
        renderSourcePeek();
        goTo("review");
        const firstGap = document.querySelector("#reviewCard .needs-attention");
        (firstGap || $("generateBtn")).focus({ preventScroll: true });
    } catch (error) {
        showNotice(notice, "error", error.message, retryable(error) ? { label: "Try again", onClick: analyze } : undefined);
    } finally {
        setBusy(button, false);
        $("inputCard").removeAttribute("aria-busy");
    }
}

async function generate({ regenerate = false } = {}) {
    const notice = regenerate ? $("composeNotice") : $("reviewNotice");
    hideNotice($("reviewNotice"));
    hideNotice($("composeNotice"));
    const details = collectDetails();
    const problem = detailsProblem(details);
    if (problem) {
        showNotice($("reviewNotice"), "error", problem.message);
        problem.field.focus();
        return;
    }
    if (regenerate && state.edited && !window.confirm("Rewriting will replace your edits to the subject and message. Continue?")) return;

    const button = regenerate ? $("regenerateBtn") : $("generateBtn");
    if (button.disabled) return;
    const firstDraft = $("mailForm").hidden;
    setBusy(button, true, regenerate ? "Rewriting" : "Writing your email");
    if (firstDraft) {
        setMailState("loading");
        if (window.innerWidth <= 1100) $("composeCard").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try {
        const { saveSenderName, ...payload } = details;
        if (saveSenderName && payload.senderName) {
            const saved = await saveProfileFields({ fullName: payload.senderName }).catch(() => null);
            if (saved) $("nameAsk").hidden = true;
        }
        const data = await api("/api/email-assistant/draft", {
            method: "POST",
            json: { ...payload, style: selected("style"), length: selected("length"), historyId: state.historyId },
        });
        state.historyId = data.historyId;
        if (!state.sendKey) state.sendKey = newRequestKey();
        showDraft(data.draft, { to: details.recipientEmail, regenerate });
        goTo("compose");
        loadHistory();
    } catch (error) {
        if (firstDraft) setMailState("empty");
        showNotice(notice, "error", error.message, retryable(error) ? { label: "Try again", onClick: () => generate({ regenerate }) } : undefined);
    } finally {
        setBusy(button, false);
    }
}

function loadRecord(record, { reuse }) {
    if (state.edited && !state.sent && !window.confirm("Open this email? Unsaved edits to the current one will be lost.")) return;
    startNewDraft();
    resetInput();
    state.historyId = reuse ? null : record.id;
    state.sendKey = newRequestKey();
    renderSavedDetails(record, currentProfile());
    renderSourcePeek(reuse ? `Reusing: ${record.subject || "sent email"}` : `Saved draft: ${record.subject || "untitled"}`);
    const failed = record.status === "failed";
    const warnings = failed && record.error ? [`Last send attempt failed: ${record.error}`] : [];
    showDraft(
        { subject: record.subject, body: record.body, attachResume: Boolean(record.attach_resume || record.attachment), warnings },
        { to: record.recipient, status: failed ? "failed" : "draft" },
    );
    state.attachTouched = true;
    goTo("compose");
    go("compose");
}

function newEmail() {
    if (state.step !== "input" && state.edited && !state.sent && !window.confirm("Discard this email and start a new one?")) return;
    startNewDraft();
    resetInput();
    clearReview();
    resetComposer();
    goTo("input");
    go("compose");
    $("pasteInput").focus();
}

/** Pasted images go to Compose when pasted in the source box, or anywhere non-editable on step 1. */
function acceptsPastedImage(event) {
    if (currentView() !== "compose") return false;
    const target = event.target instanceof Element ? event.target : null;
    if (target && $("inputCard").contains(target)) return true;
    const editable = target && target.closest("input, textarea, select, [contenteditable]");
    return state.step === "input" && !editable;
}

initShell();
initComposer(state, { generate, newEmail });
initInput({ onAnalyze: analyze, acceptsPastedImage });
initReview();
initProfile();
initGmail();
initHistory({
    open: (record) => loadRecord(record, { reuse: false }),
    reuse: (record) => loadRecord(record, { reuse: true }),
    compose: newEmail,
});
initBatch();
initSetup();

$("newEmailBtn").addEventListener("click", newEmail);
$("generateBtn").addEventListener("click", () => generate());
$("sourcePeek").addEventListener("click", () => {
    goTo("input");
    $("pasteInput").focus();
});
$("reviewCard").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        generate();
    }
});
onViewChange((view) => {
    if (view === "history") loadHistory();
});
api("/api/auth/me").then((data) => { $("accountName").textContent = data.username || ""; }).catch(() => undefined);
$("logoutBtn").addEventListener("click", async () => {
    if (state.edited && !state.sent && !window.confirm("Log out? Unsaved edits to this email will be lost.")) return;
    state.edited = false;
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    location.replace("/login");
});
window.addEventListener("beforeunload", (event) => {
    if (state.edited && !state.sent) event.preventDefault();
});
