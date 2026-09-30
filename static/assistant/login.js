// Sign-in / create-account page.
import { $, api, hideNotice, setBusy, showNotice } from "./util.js";

let mode = "login";
let inviteRequired = false;

function render() {
    const signup = mode === "signup";
    $("authTitle").textContent = signup ? "Create your account" : "Sign in";
    $("authSub").textContent = signup ? "Your profile, resume and history stay private to you." : "Welcome back.";
    $("authSubmit").textContent = signup ? "Create account" : "Sign in";
    $("password").autocomplete = signup ? "new-password" : "current-password";
    $("passwordHint").hidden = !signup;
    $("inviteField").hidden = !(signup && inviteRequired);
    hideNotice($("authNotice"));
}

async function submit(event) {
    event.preventDefault();
    const username = $("username").value.trim();
    const password = $("password").value;
    if (!username || !password) {
        showNotice($("authNotice"), "error", "Enter your username and password.");
        return;
    }
    const button = $("authSubmit");
    setBusy(button, true, mode === "signup" ? "Creating account" : "Signing in");
    try {
        await api(`/api/auth/${mode}`, { method: "POST", json: { username, password, inviteCode: $("inviteCode").value } });
        location.replace("/");
    } catch (error) {
        showNotice($("authNotice"), "error", error.message);
        setBusy(button, false);
    }
}

document.querySelectorAll('input[name="authMode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
        mode = radio.value;
        render();
    });
});
$("authForm").addEventListener("submit", submit);

api("/api/auth/me").then((data) => {
    if (data.username) location.replace("/");
    inviteRequired = data.signupCodeRequired;
    render();
}).catch(() => render());
$("username").focus();
