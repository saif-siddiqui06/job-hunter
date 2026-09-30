// Gmail connection: sidebar status, the Connect Gmail dialog, and Google sign-in results.
import { $, EMAIL_RE, api, hideNotice, setBusy, showNotice, toast } from "./util.js";
import { currentProfile } from "./profile.js";

let status = { connected: false, method: null, account: null, googleConfigured: false };
const listeners = new Set();

export const gmailStatus = () => status;
export const onGmailChange = (listener) => listeners.add(listener);
export const methodLabel = (method) => (method === "google" ? "Google sign-in" : "App Password");

const GOOGLE_RESULTS = {
    connected: ["success", "Gmail connected with Google."],
    missing_config: ["error", "Google sign-in isn't set up on this computer yet. Connect with an App Password instead."],
    missing_dependencies: ["error", "Google sign-in needs its Python packages. Run pip install -r requirements.txt, or use an App Password."],
    denied: ["info", "Google sign-in was cancelled."],
    failed: ["error", "Google sign-in didn't finish. Try again, or connect with an App Password."],
};

function render() {
    const connected = Boolean(status.connected);
    $("gmailDot").className = `gmail-dot ${connected ? "on" : "off"}`;
    $("gmailTitle").textContent = connected ? "Gmail connected" : "Gmail not connected";
    $("gmailAccount").textContent = connected ? status.account || methodLabel(status.method) : "Needed to send email";
    const manage = $("gmailManageBtn");
    manage.textContent = connected ? "Manage" : "Connect Gmail";
    manage.classList.toggle("cta", !connected);

    $("gmailConnectedBox").hidden = !connected;
    $("gmailConnectForms").hidden = connected;
    $("gmailConnectedAccount").textContent = status.account || "Your Gmail account";
    $("gmailConnectedMethod").textContent = `Connected with ${methodLabel(status.method)}`;
    $("googleReady").hidden = !status.googleConfigured;
    $("googleNotReady").hidden = Boolean(status.googleConfigured);
}

export async function refreshGmail() {
    try {
        const response = await fetch("/auth/status", { credentials: "same-origin" });
        if (response.status === 401) location.replace("/login");
        if (response.ok) status = await response.json();
    } catch {
        // Keep the last known status; the server re-checks on every send anyway.
    }
    render();
    listeners.forEach((listener) => listener(status));
    return status;
}

function showMethod(method) {
    $("appPasswordForm").hidden = method !== "app_password";
    $("googlePane").hidden = method !== "google";
}

export function openGmailDialog() {
    render();
    hideNotice($("apNotice"));
    const profile = currentProfile();
    if (!$("apEmail").value && profile && profile.email) $("apEmail").value = profile.email;
    const dialog = $("gmailDialog");
    if (!dialog.open) dialog.showModal();
    if (!status.connected) ($("apEmail").value ? $("apPassword") : $("apEmail")).focus();
}

async function connectAppPassword(event) {
    event.preventDefault();
    const email = $("apEmail").value.trim();
    const appPassword = $("apPassword").value;
    const notice = $("apNotice");
    if (!EMAIL_RE.test(email)) {
        showNotice(notice, "error", "Enter the Gmail address you want to send from.");
        $("apEmail").focus();
        return;
    }
    if (appPassword.replace(/\s/g, "").length < 8) {
        showNotice(notice, "error", "Paste the 16-letter App Password from your Google account.");
        $("apPassword").focus();
        return;
    }

    const button = $("apConnectBtn");
    setBusy(button, true, "Checking with Gmail");
    hideNotice(notice);
    try {
        await api("/api/gmail/app-password", { method: "POST", json: { email, appPassword } });
        $("apPassword").value = "";
        await refreshGmail();
        $("gmailDialog").close();
        toast("success", `Gmail connected: ${status.account}`);
    } catch (error) {
        showNotice(notice, "error", error.message);
    } finally {
        setBusy(button, false);
    }
}

async function disconnect() {
    if (!window.confirm("Disconnect Gmail? You'll need to connect again before sending.")) return;
    try {
        await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
        await refreshGmail();
        toast("info", "Gmail disconnected.");
    }
}

function handleGoogleResult() {
    const params = new URLSearchParams(location.search);
    const result = GOOGLE_RESULTS[params.get("google_auth")];
    if (!result) return;
    history.replaceState(null, "", location.pathname + location.hash);
    toast(result[0], result[1], undefined, 7000);
    if (result[0] === "error" && !status.connected) openGmailDialog();
}

export function initGmail() {
    $("gmailManageBtn").addEventListener("click", openGmailDialog);
    $("appPasswordForm").addEventListener("submit", connectAppPassword);
    $("gmailDisconnect").addEventListener("click", disconnect);
    document.querySelectorAll('input[name="gmailMethod"]').forEach((radio) => {
        radio.addEventListener("change", () => showMethod(radio.value));
    });
    $("apToggle").addEventListener("click", () => {
        const input = $("apPassword");
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        $("apToggle").textContent = show ? "Hide" : "Show";
        $("apToggle").setAttribute("aria-pressed", String(show));
    });
    showMethod("app_password");
    return refreshGmail().then(handleGoogleResult);
}
