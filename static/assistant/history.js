// History view: stats, filter + search, and a detail dialog for each email.
import { $, api, el, formatTime, timeAgo, toast } from "./util.js";

const SOURCE_LABELS = { screenshot: "From a screenshot", clipboard: "From pasted text" };
const STATUS_LABELS = { draft: "Draft", sent: "Sent", failed: "Not sent", sending: "Sending", "follow-up": "Follow-up" };
const REOPENABLE = new Set(["draft", "failed", "follow-up"]);
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

let records = [];
let hooks = { open: () => {}, reuse: () => {}, compose: () => {} };

const statusOf = (record) => String(record.status || "draft").toLowerCase().replace(/[^a-z-]/g, "");
const whenOf = (record) => record.sent_at || record.updated_at || record.created_at;

function renderStats() {
    const count = (status) => records.filter((record) => statusOf(record) === status).length;
    const weekAgo = Date.now() - WEEK_MS;
    $("statSent").textContent = count("sent");
    $("statDraft").textContent = count("draft") + count("follow-up");
    $("statFailed").textContent = count("failed");
    $("statWeek").textContent = records.filter((r) => statusOf(r) === "sent" && new Date(r.sent_at || r.updated_at).getTime() > weekAgo).length;
    const open = records.filter((record) => REOPENABLE.has(statusOf(record))).length;
    const badge = $("navHistoryCount");
    badge.hidden = open === 0;
    badge.textContent = open;
    badge.title = `${open} unsent`;
}

function matches(record) {
    const filter = document.querySelector('input[name="historyFilter"]:checked').value;
    const status = statusOf(record);
    if (filter === "draft" && !(status === "draft" || status === "follow-up")) return false;
    if (filter !== "all" && filter !== "draft" && status !== filter) return false;
    const query = $("historySearch").value.trim().toLowerCase();
    if (!query) return true;
    return [record.recipient, record.company, record.role, record.subject].some((value) => (value || "").toLowerCase().includes(query));
}

function renderRow(record) {
    const status = statusOf(record);
    const initial = (record.company || record.recipient || "?").trim().charAt(0) || "?";
    const meta = [record.recipient || "No recipient yet", record.company, record.role].filter(Boolean).join(" · ");
    const when = whenOf(record);
    return el(
        "button",
        { type: "button", className: "history-row", onClick: () => openDetail(record), "aria-label": `${STATUS_LABELS[status] || status}: ${record.subject || "no subject"}` },
        el("span", { className: "history-avatar", "aria-hidden": "true", text: initial }),
        el("span", { className: "history-main" }, el("strong", { text: record.subject || "(no subject)" }), el("span", { className: "history-meta", text: meta })),
        el(
            "span",
            { className: "history-side" },
            el("span", { className: `pill ${status}`, text: STATUS_LABELS[status] || status }),
            when ? el("time", { datetime: when, title: formatTime(when), text: timeAgo(when) }) : null,
        ),
    );
}

function renderEmpty() {
    const filtered = records.length > 0;
    return el(
        "div",
        { className: "empty-state" },
        el("h3", { text: filtered ? "Nothing matches" : "No emails yet" }),
        el("p", { text: filtered ? "Try a different filter or search." : "Emails you write with Compose show up here with their status." }),
        filtered ? null : el("button", { type: "button", className: "btn btn-primary", text: "Write your first email", onClick: () => hooks.compose() }),
    );
}

function render() {
    renderStats();
    const visible = records.filter(matches);
    $("activityList").replaceChildren(...(visible.length ? visible.map(renderRow) : [renderEmpty()]));
}

function openDetail(record) {
    const status = statusOf(record);
    const dialog = $("historyDialog");
    const pill = $("historyDialogStatus");
    pill.className = `pill ${status}`;
    pill.textContent = STATUS_LABELS[status] || status;
    $("historyDialogTitle").textContent = record.subject || "(no subject)";

    const rows = [
        ["To", record.recipient || "No recipient yet"],
        ["Company", record.company],
        ["Role", record.role],
        ["Source", SOURCE_LABELS[record.source_type]],
        ["Attachment", record.attachment ? record.attachment.filename : null],
        ["Created", record.created_at ? formatTime(record.created_at) : null],
        ["Sent", record.sent_at ? formatTime(record.sent_at) : null],
    ].filter(([, value]) => value);
    $("historyDialogMeta").replaceChildren(...rows.flatMap(([label, value]) => [el("dt", { text: label }), el("dd", { text: value })]));
    $("historyDialogBody").textContent = record.body || "";
    $("historyDialogError").hidden = !(status === "failed" && record.error);
    $("historyDialogError").textContent = record.error || "";

    const close = () => dialog.close();
    const actions = [];
    if (status !== "sent" && status !== "sending") {
        actions.push(el("button", { type: "button", className: "btn btn-quiet", text: "Delete", onClick: () => { close(); removeRecord(record); } }));
    }
    if (REOPENABLE.has(status)) {
        actions.push(el("button", { type: "button", className: "btn btn-primary", text: "Open in Compose", onClick: () => { close(); hooks.open(record); } }));
    } else if (status === "sent") {
        actions.push(el("button", { type: "button", className: "btn btn-quiet", text: "Reuse as new email", onClick: () => { close(); hooks.reuse(record); } }));
    }
    $("historyDialogActions").replaceChildren(...actions);
    dialog.showModal();
}

async function removeRecord(record) {
    if (!window.confirm(`Delete "${record.subject || "this draft"}" from your history?`)) return;
    try {
        records = (await api(`/api/delete-activity/${encodeURIComponent(record.id)}`, { method: "DELETE" })).activities;
        render();
        toast("info", "Deleted from history.");
    } catch (error) {
        toast("error", error.message);
    }
}

export async function loadHistory() {
    try {
        records = (await api("/api/list-activities")).activities || [];
        render();
    } catch (error) {
        $("activityList").replaceChildren(el("div", { className: "empty-state" }, el("h3", { text: "Couldn't load your history" }), el("p", { text: error.message })));
    }
}

export function initHistory(sharedHooks) {
    hooks = { ...hooks, ...sharedHooks };
    $("refreshActivityBtn").addEventListener("click", loadHistory);
    $("historySearch").addEventListener("input", render);
    document.querySelectorAll('input[name="historyFilter"]').forEach((radio) => radio.addEventListener("change", render));
    return loadHistory();
}
