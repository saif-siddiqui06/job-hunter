// Batch send: one message to every address in a CSV, sent from the connected Gmail.
import { $, EMAIL_RE, el, hideNotice, setBusy, showNotice, toast } from "./util.js";
import { currentProfile, onProfileChange } from "./profile.js";
import { openGmailDialog, refreshGmail } from "./gmail.js";

const EMAIL_COLUMNS = ["email", "e-mail"];
let csvFile = null;
let recipients = [];
let uploadFile = null;

/** Mirrors the server's CSV reading closely enough to preview who will get the email. */
function parseRecipients(text) {
    const rows = text.replace(/^﻿/, "").split(/\r?\n/).filter((line) => line.trim());
    if (!rows.length) return [];
    const header = rows[0].split(",").map((cell) => cell.trim().toLowerCase());
    const column = Math.max(0, header.findIndex((cell) => EMAIL_COLUMNS.includes(cell)));
    return rows.slice(1)
        .map((row) => (row.split(",")[column] || "").trim().replace(/^"|"$/g, ""))
        .filter((value) => value.includes("@"));
}

function renderRecipients() {
    const preview = $("csvPreview");
    const zone = $("csvZone");
    zone.classList.toggle("has-file", Boolean(csvFile));
    $("csvLabel").textContent = csvFile ? csvFile.name : "Drop a CSV or click to choose";
    $("csvHint").textContent = csvFile ? `${recipients.length} recipient${recipients.length === 1 ? "" : "s"} found · click to replace` : 'Needs an "email" column, like: email,name';
    preview.hidden = !csvFile;
    if (!csvFile) return;
    const invalid = recipients.filter((email) => !EMAIL_RE.test(email)).length;
    preview.replaceChildren(
        el("strong", { text: recipients.length ? `Sending to ${recipients.length} recipient${recipients.length === 1 ? "" : "s"}` : "No email addresses found in this file" }),
        ...recipients.slice(0, 6).map((email) => el("span", { className: "tag", text: email })),
        recipients.length > 6 ? el("span", { className: "tag", text: `+${recipients.length - 6} more` }) : null,
        invalid ? el("span", { className: "tag warn", text: `${invalid} look invalid` }) : null,
    );
    updateSendLabel();
}

async function setCsv(file) {
    if (!file) return;
    if (!/\.csv$/i.test(file.name)) {
        showNotice($("result"), "error", "Choose a .csv file.");
        return;
    }
    csvFile = file;
    recipients = parseRecipients(await file.text());
    hideNotice($("result"));
    renderRecipients();
}

function attachChoice() {
    return document.querySelector('input[name="batchAttach"]:checked').value;
}

function renderAttachment() {
    const resume = currentProfile() && currentProfile().resume;
    const profileOption = document.querySelector('input[name="batchAttach"][value="profile"]');
    profileOption.disabled = !resume;
    $("batchProfileResume").textContent = resume ? `(${resume.filename})` : "(none uploaded yet)";
    if (!resume && profileOption.checked) document.querySelector('input[name="batchAttach"][value="none"]').checked = true;
    $("resumeName").textContent = attachChoice() === "upload" && uploadFile ? `Attaching ${uploadFile.name}` : "";
}

function updateSendLabel() {
    $("sendBtn").textContent = recipients.length ? `Send to ${recipients.length} recipient${recipients.length === 1 ? "" : "s"}` : "Send batch";
}

function setProgress(percent, label, count) {
    $("progressWrap").hidden = false;
    $("progressBar").style.width = `${percent}%`;
    if (label) $("progressLabel").textContent = label;
    if (count) $("progressCount").textContent = count;
}

async function readProgress(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = null;
    const handle = (event) => {
        if (event.type === "error") throw new Error(event.error || "Something went wrong while sending.");
        if (event.type === "start") setProgress(0, "Preparing emails", `0 / ${event.total}`);
        if (event.type === "progress") setProgress(event.percent, `${event.status === "sent" ? "Sent to" : "Failed:"} ${event.recipient}`, `${event.current} / ${event.total}`);
        if (event.type === "done") done = event;
    };
    for (;;) {
        const { value, done: finished } = await reader.read();
        if (finished) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        lines.filter((line) => line.trim()).forEach((line) => handle(JSON.parse(line)));
    }
    if (buffer.trim()) handle(JSON.parse(buffer));
    return done;
}

async function sendBatch(event) {
    event.preventDefault();
    const subject = $("subject").value.trim();
    const message = $("message").value.trim();
    const result = $("result");
    hideNotice(result);
    if (!subject || !message) return showNotice(result, "error", "Add a subject and a message.");
    if (!csvFile || !recipients.length) return showNotice(result, "error", "Add a CSV with at least one email address.");
    if (attachChoice() === "upload" && !uploadFile) return showNotice(result, "error", "Choose the file to attach, or pick another attachment option.");

    const status = await refreshGmail();
    if (!status.connected) {
        showNotice(result, "info", "Connect Gmail first, then click Send again.", { label: "Connect Gmail", onClick: openGmailDialog });
        openGmailDialog();
        return;
    }
    if (!window.confirm(`Send "${subject}" to ${recipients.length} recipient${recipients.length === 1 ? "" : "s"} from ${status.account || "your Gmail"}?`)) return;

    const form = new FormData();
    form.append("auth_method", "connected");
    form.append("subject", subject);
    form.append("message", message);
    form.append("csv", csvFile, csvFile.name);
    if (attachChoice() === "upload") form.append("resume", uploadFile, uploadFile.name);
    if (attachChoice() === "profile") form.append("use_profile_resume", "1");

    const button = $("sendBtn");
    setBusy(button, true, "Sending");
    setProgress(0, "Starting", `0 / ${recipients.length}`);
    try {
        const response = await fetch("/send", { method: "POST", body: form, credentials: "same-origin", headers: { "X-Requested-With": "ApplyRocket" } });
        if (!response.ok || !(response.headers.get("content-type") || "").includes("application/x-ndjson")) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || "Something went wrong while sending.");
        }
        const done = await readProgress(response);
        if (done) {
            const failed = done.failed ? `, ${done.failed} failed` : "";
            showNotice(result, done.failed ? "warn" : "success", `Done. ${done.count} of ${done.total} emails sent${failed}.`);
            toast(done.failed ? "info" : "success", `Batch finished: ${done.count} sent${failed}.`);
        }
    } catch (error) {
        showNotice(result, "error", error.message === "Failed to fetch" ? "Connection error. Make sure the app is still running." : error.message);
    } finally {
        setBusy(button, false);
        updateSendLabel();
        setTimeout(() => { $("progressWrap").hidden = true; }, 1500);
    }
}

function clearForm() {
    $("emailForm").reset();
    csvFile = null;
    recipients = [];
    uploadFile = null;
    hideNotice($("result"));
    $("progressWrap").hidden = true;
    renderRecipients();
    renderAttachment();
    updateSendLabel();
}

export function initBatch() {
    const zone = $("csvZone");
    const input = $("csvFile");
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            input.click();
        }
    });
    zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("dragging");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
    zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("dragging");
        setCsv(event.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => setCsv(input.files[0]));

    document.querySelectorAll('input[name="batchAttach"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            if (radio.value === "upload" && !uploadFile) $("resumeFile").click();
            renderAttachment();
        });
    });
    $("resumeFile").addEventListener("change", () => {
        uploadFile = $("resumeFile").files[0] || null;
        renderAttachment();
    });

    $("emailForm").addEventListener("submit", sendBatch);
    $("clearBtn").addEventListener("click", clearForm);
    onProfileChange(renderAttachment);
    renderAttachment();
}
