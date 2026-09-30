// Email pane: editable preview, attachment, rewrite, save, copy and the explicit Send.
import { $, EMAIL_RE, api, el, formatTime, hideNotice, newRequestKey, renderNotices, setBusy, showNotice, toast } from "./util.js";
import { currentProfile, hasResume, onProfileChange, uploadResume } from "./profile.js";
import { gmailStatus, methodLabel, onGmailChange, openGmailDialog, refreshGmail } from "./gmail.js";
import { collectDetails } from "./review.js";
import { loadHistory } from "./history.js";
import { go } from "./shell.js";

let state;
let hooks;

const notice = () => $("composeNotice");

export function setMailState(mode) {
    $("mailEmpty").hidden = mode !== "empty";
    $("mailSkeleton").hidden = mode !== "loading";
    $("mailForm").hidden = mode !== "ready";
}

function setStatusPill(status) {
    const pill = $("mailStatus");
    pill.hidden = !status;
    if (!status) return;
    pill.className = `pill ${status}`;
    pill.textContent = { draft: "Draft", sent: "Sent", failed: "Not sent" }[status] || status;
}

function renderFrom() {
    const status = gmailStatus();
    const from = $("mailFrom");
    if (status.connected) {
        from.replaceChildren(el("strong", { text: status.account || "Your Gmail" }), ` · ${methodLabel(status.method)}`);
    } else {
        from.replaceChildren(
            el("button", { type: "button", className: "link-btn", text: "Connect Gmail to send", onClick: openGmailDialog }),
        );
    }
}

function renderAttachment() {
    const resume = currentProfile() && currentProfile().resume;
    const box = $("attachResume");
    if (!resume) box.checked = false;
    box.disabled = !resume || state.sent;
    $("attachmentName").textContent = resume ? (box.checked ? resume.filename : `Attach ${resume.filename}`) : "No resume on file";
    $("changeResumeBtn").textContent = resume ? "Change" : "Upload resume";
}

function autoGrow() {
    const body = $("mailBody");
    body.style.height = "auto";
    body.style.height = `${Math.min(Math.max(body.scrollHeight + 2, 320), 1000)}px`;
}

function setSent(sent) {
    state.sent = sent;
    for (const id of ["mailTo", "mailSubject", "mailBody"]) $(id).readOnly = sent;
    for (const id of ["regenerateBtn", "saveDraftBtn", "changeResumeBtn"]) $(id).disabled = sent;
    const button = $("sendMailBtn");
    button.disabled = sent;
    button.classList.toggle("sent", sent);
    if (sent) button.textContent = "Sent";
    else if (!button.getAttribute("aria-busy")) button.replaceChildren(...sendLabel());
    renderAttachment();
}

let sendContent = [];
const sendLabel = () => sendContent.map((node) => node.cloneNode(true));

/** Puts a generated (or reopened) draft into the composer. */
export function showDraft(draft, { to = "", regenerate = false, status = "draft" } = {}) {
    if (!regenerate || !$("mailTo").value.trim()) $("mailTo").value = to || "";
    $("mailSubject").value = draft.subject || "";
    $("mailBody").value = draft.body || "";
    if (!state.attachTouched) $("attachResume").checked = Boolean(draft.attachResume) && hasResume();
    renderNotices($("draftWarnings"), draft.warnings || [], "warn");
    state.edited = false;
    hideNotice(notice());
    setMailState("ready");
    setStatusPill(status);
    setSent(false);
    renderFrom();
    requestAnimationFrame(autoGrow);
}

export function resetComposer() {
    for (const id of ["mailTo", "mailSubject", "mailBody"]) $(id).value = "";
    $("attachResume").checked = false;
    renderNotices($("draftWarnings"), []);
    hideNotice(notice());
    setStatusPill(null);
    setMailState("empty");
    setSent(false);
}

function sendProblem(to, subject, body) {
    if (!to) return { field: "mailTo", message: "No recipient email found. Who should this email be sent to?" };
    if (!EMAIL_RE.test(to)) return { field: "mailTo", message: "The recipient email address isn't valid. Enter a single address like name@company.com." };
    if (!subject) return { field: "mailSubject", message: "Add a subject before sending." };
    if (!body) return { field: "mailBody", message: "The email body is empty." };
    if ($("attachResume").checked && !hasResume()) return { field: "attachResume", message: "Your resume isn't on file. Upload it or untick the attachment." };
    return null;
}

function actionFor(code) {
    if (code === "gmail_not_connected" || code === "gmail_auth") return { label: "Connect Gmail", onClick: openGmailDialog };
    if (code === "resume_missing") return { label: "Upload resume", onClick: () => $("composeResumeInput").click() };
    return undefined;
}

async function send() {
    if (state.sending || state.sent) return;
    const to = $("mailTo").value.trim();
    const subject = $("mailSubject").value.trim();
    const body = $("mailBody").value.trim();
    const problem = sendProblem(to, subject, body);
    if (problem) {
        showNotice(notice(), "error", problem.message);
        $(problem.field).focus();
        return;
    }

    const button = $("sendMailBtn");
    state.sending = true;
    setBusy(button, true, "Sending");
    $("regenerateBtn").disabled = true;
    $("saveDraftBtn").disabled = true;
    hideNotice(notice());
    try {
        const status = await refreshGmail();
        if (!status.connected) {
            showNotice(notice(), "info", "Connect Gmail first. Your email stays right here; click Send again once you're connected.", { label: "Connect Gmail", onClick: openGmailDialog });
            openGmailDialog();
            return;
        }
        if (!state.sendKey) state.sendKey = newRequestKey();
        const details = collectDetails();
        const data = await api("/api/email-assistant/send", {
            method: "POST",
            headers: { "Idempotency-Key": state.sendKey },
            json: {
                to,
                subject,
                body,
                attachResume: $("attachResume").checked,
                historyId: state.historyId,
                companyName: details.companyName,
                jobTitle: details.jobTitle,
                sourceType: details.sourceType,
            },
        });
        state.historyId = data.historyId;
        setBusy(button, false);
        setSent(true);
        setStatusPill("sent");
        const when = data.sentAt ? ` at ${formatTime(data.sentAt)}` : "";
        const message = data.alreadySent ? `This email was already sent${when}, so it wasn't sent again.` : `Email sent to ${to}${when}.`;
        showNotice(notice(), "success", message, { label: "Write another", onClick: hooks.newEmail });
        toast("success", data.alreadySent ? "Already sent earlier. Not sent twice." : `Sent to ${to}`);
    } catch (error) {
        if (error.data && error.data.historyId) state.historyId = error.data.historyId;
        if (error.status >= 500 || error.status === 0) setStatusPill("failed");
        const keep = /draft/i.test(error.message) ? "" : " Your email is still here.";
        showNotice(notice(), "error", `${error.message}${keep}`, actionFor(error.code));
    } finally {
        state.sending = false;
        if (!state.sent) {
            setBusy(button, false);
            button.replaceChildren(...sendLabel());
            $("regenerateBtn").disabled = false;
            $("saveDraftBtn").disabled = false;
        }
        loadHistory();
    }
}

async function saveDraft() {
    const payload = {
        recipient: $("mailTo").value.trim(),
        subject: $("mailSubject").value.trim(),
        body: $("mailBody").value.trim(),
        attachResume: $("attachResume").checked,
    };
    if (!payload.subject || !payload.body) {
        showNotice(notice(), "error", "Add a subject and message before saving.");
        return;
    }
    const button = $("saveDraftBtn");
    setBusy(button, true, "Saving");
    try {
        if (state.historyId) {
            await api(`/api/update-activity/${encodeURIComponent(state.historyId)}`, { method: "PATCH", json: payload });
        } else {
            if (!payload.recipient) throw new Error("Add a recipient before saving this draft.");
            const data = await api("/api/log-activity", { method: "POST", json: { ...payload, status: "draft" } });
            state.historyId = data.activity.id;
        }
        state.edited = false;
        toast("success", "Draft saved to History.");
        loadHistory();
    } catch (error) {
        showNotice(notice(), "error", error.message);
    } finally {
        setBusy(button, false);
    }
}

async function copyEmail() {
    const text = `Subject: ${$("mailSubject").value.trim()}\n\n${$("mailBody").value.trim()}`;
    try {
        await navigator.clipboard.writeText(text);
        toast("success", "Copied subject and message.");
    } catch {
        $("mailBody").select();
        toast("info", "Press Ctrl+C to copy the selected message.");
    }
}

async function followUp() {
    const subject = $("mailSubject").value.trim();
    const body = $("mailBody").value.trim();
    const to = $("mailTo").value.trim();
    if (!subject && !body) {
        showNotice(notice(), "error", "Write or generate an email first, then I can draft a follow-up to it.");
        return;
    }
    if (state.edited && !state.sent && !window.confirm("Replace this email with a follow-up? Unsaved edits will be lost.")) return;
    try {
        const data = await api("/api/generate-follow-up", { method: "POST", json: { subject, body, recipient: to } });
        state.historyId = null;
        state.sendKey = newRequestKey();
        state.attachTouched = false;
        showDraft({ subject: data.subject, body: data.body, attachResume: false, warnings: [] }, { to, regenerate: true });
        toast("info", "Follow-up drafted. Review it before sending.");
    } catch (error) {
        showNotice(notice(), "error", error.message);
    }
}

function useInBatch() {
    $("subject").value = $("mailSubject").value;
    $("message").value = $("mailBody").value;
    go("batch");
    toast("info", "Subject and message copied into Batch send.");
}

export function initComposer(sharedState, sharedHooks) {
    state = sharedState;
    hooks = sharedHooks;
    sendContent = Array.from($("sendMailBtn").childNodes, (node) => node.cloneNode(true));

    for (const id of ["mailSubject", "mailBody"]) $(id).addEventListener("input", () => { state.edited = true; });
    $("mailBody").addEventListener("input", autoGrow);
    $("attachResume").addEventListener("change", () => {
        state.attachTouched = true;
        renderAttachment();
    });
    $("changeResumeBtn").addEventListener("click", () => $("composeResumeInput").click());
    $("composeResumeInput").addEventListener("change", async () => {
        const file = $("composeResumeInput").files[0];
        $("composeResumeInput").value = "";
        if (!file) return;
        try {
            await uploadResume(file);
            $("attachResume").checked = true;
            state.attachTouched = true;
            renderAttachment();
            toast("success", `Resume uploaded and attached: ${file.name}`);
        } catch (error) {
            showNotice(notice(), "error", error.message);
        }
    });

    $("sendMailBtn").addEventListener("click", send);
    $("saveDraftBtn").addEventListener("click", saveDraft);
    $("copyBtn").addEventListener("click", copyEmail);
    $("regenerateBtn").addEventListener("click", () => hooks.generate({ regenerate: true }));
    $("followUpBtn").addEventListener("click", followUp);
    $("useInBatchBtn").addEventListener("click", useInBatch);
    onProfileChange(renderAttachment);
    onGmailChange(renderFrom);
    resetComposer();
}
