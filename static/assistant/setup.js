// "Get ready to send" checklist on the Compose start screen.
import { $ } from "./util.js";
import { currentProfile, onProfileChange } from "./profile.js";
import { gmailStatus, onGmailChange, openGmailDialog } from "./gmail.js";

function render() {
    const profile = currentProfile() || {};
    const steps = {
        setupGmail: Boolean(gmailStatus().connected),
        setupProfile: Boolean(profile.fullName && profile.experience),
        setupResume: Boolean(profile.resume),
    };
    let done = 0;
    for (const [id, complete] of Object.entries(steps)) {
        $(id).classList.toggle("done", complete);
        done += complete ? 1 : 0;
    }
    const total = Object.keys(steps).length;
    $("setupCount").textContent = done === total ? "All set" : `${done} of ${total} done`;
    $("setupCard").classList.toggle("complete", done === total);
}

export function initSetup() {
    $("setupGmailBtn").addEventListener("click", openGmailDialog);
    onProfileChange(render);
    onGmailChange(render);
    render();
}
