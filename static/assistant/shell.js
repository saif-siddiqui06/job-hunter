// App shell: sidebar navigation between the Compose, History, Batch send and Profile views.
import { $ } from "./util.js";

const VIEWS = { compose: "Compose", history: "History", batch: "Batch send", profile: "Profile" };
const listeners = new Set();

export const currentView = () => {
    const name = location.hash.slice(1);
    return name in VIEWS ? name : "compose";
};

export const onViewChange = (listener) => listeners.add(listener);

function render() {
    const name = currentView();
    for (const view of Object.keys(VIEWS)) $(`view-${view}`).hidden = view !== name;
    document.querySelectorAll(".nav-item").forEach((link) => {
        const active = link.dataset.view === name;
        link.classList.toggle("active", active);
        if (active) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
    });
    document.title = `${VIEWS[name]} · Apply Rocket`;
    listeners.forEach((listener) => listener(name));
}

export function go(name) {
    if (currentView() === name && location.hash === `#${name}`) render();
    else location.hash = name;
}

export function initShell() {
    window.addEventListener("hashchange", () => {
        render();
        window.scrollTo({ top: 0 });
    });
    render();
}
