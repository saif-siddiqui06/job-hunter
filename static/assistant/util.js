// Shared helpers for the AI Email Assistant modules.

export const $ = (id) => document.getElementById(id);

export const EMAIL_RE = /^[^\s@,;<>"]+@[^\s@,;<>"]+\.[A-Za-z]{2,24}$/;

export class ApiError extends Error {
    constructor(message, { status = 0, code = null, data = null } = {}) {
        super(message);
        this.status = status;
        this.code = code;
        this.data = data;
    }
}

/** fetch() wrapper: adds the CSRF header, parses JSON, and turns failures into ApiError. */
export async function api(path, { method = "GET", json, form, headers = {} } = {}) {
    const init = {
        method,
        credentials: "same-origin",
        headers: { "X-Requested-With": "ApplyRocket", ...headers },
    };
    if (json !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(json);
    } else if (form) {
        init.body = form;
    }

    let response;
    try {
        response = await fetch(path, init);
    } catch {
        throw new ApiError("Connection error. Make sure the app server is running, then try again.");
    }

    let data = null;
    try {
        data = await response.json();
    } catch {
        // Non-JSON error page; handled below.
    }
    if (response.status === 401 && data && data.code === "login_required" && location.pathname !== "/login") {
        location.replace("/login");
    }
    if (!response.ok || !data || data.success === false) {
        const fallback = response.status === 413
            ? "Upload exceeds the maximum allowed size."
            : `Something went wrong (error ${response.status}). Please try again.`;
        throw new ApiError((data && data.error) || fallback, {
            status: response.status,
            code: (data && data.code) || null,
            data,
        });
    }
    return data;
}

/** Tiny element builder. Text is always set via textContent, never parsed as HTML. */
export function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === "className") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
        else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

/** Shows a notice. `action` is an optional { label, onClick } rendered as an inline button. */
export function showNotice(node, type, message, action) {
    node.className = `notice ${type}`;
    node.replaceChildren(document.createTextNode(message));
    if (action) {
        node.append(el("button", { type: "button", className: "notice-action", text: action.label, onClick: action.onClick }));
    }
    node.hidden = false;
}

export function hideNotice(node) {
    node.hidden = true;
    node.replaceChildren();
}

export function renderNotices(container, messages, type = "warn") {
    container.replaceChildren(...messages.map((message) => el("div", { className: `notice ${type}`, role: "note", text: message })));
}

const idleContent = new WeakMap();

/** Disables a button and swaps its content for a spinner + label while work is in progress. */
export function setBusy(button, busy, busyLabel) {
    if (busy) {
        if (!idleContent.has(button)) idleContent.set(button, Array.from(button.childNodes, (node) => node.cloneNode(true)));
        button.disabled = true;
        button.replaceChildren(el("span", { className: "spinner", "aria-hidden": "true" }), busyLabel);
        button.setAttribute("aria-busy", "true");
    } else {
        button.disabled = false;
        if (idleContent.has(button)) button.replaceChildren(...idleContent.get(button));
        idleContent.delete(button);
        button.removeAttribute("aria-busy");
    }
}

export function newRequestKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function formatTime(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} h ago`;
    const days = Math.round(hours / 24);
    if (days < 7) return `${days} d ago`;
    return date.toLocaleDateString([], { day: "numeric", month: "short" });
}

/** Short-lived message in the corner. `action` is an optional { label, onClick }. */
export function toast(type, message, action, timeout = 5000) {
    const node = el("div", { className: `toast ${type}`, role: type === "error" ? "alert" : "status" }, el("span", { text: message }));
    const dismiss = () => {
        node.classList.add("leaving");
        setTimeout(() => node.remove(), 200);
    };
    if (action) {
        node.append(el("button", { type: "button", className: "notice-action", text: action.label, onClick: () => { action.onClick(); dismiss(); } }));
    }
    $("toasts").append(node);
    setTimeout(dismiss, timeout);
}
