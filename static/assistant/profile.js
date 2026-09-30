// Profile view: the sender facts the AI may use, plus the stored resume.
import { $, api, hideNotice, setBusy, showNotice, toast } from "./util.js";

const RESUME_MAX_BYTES = 5 * 1024 * 1024;
const FIELDS = {
    fullName: "pfName",
    email: "pfEmail",
    phone: "pfPhone",
    headline: "pfHeadline",
    linkedinUrl: "pfLinkedin",
    portfolioUrl: "pfPortfolio",
    experience: "pfExperience",
};
// How much each part contributes to a useful email (sums to 100).
const WEIGHTS = { fullName: 20, experience: 20, resume: 15, skills: 10, headline: 10, email: 5, phone: 5, linkedinUrl: 10, portfolioUrl: 5 };

let profile = null;
const listeners = new Set();

export const currentProfile = () => profile;
export const hasResume = () => Boolean(profile && profile.resume);
export const onProfileChange = (listener) => listeners.add(listener);

function score(p) {
    let total = 0;
    for (const [key, weight] of Object.entries(WEIGHTS)) {
        const value = key === "resume" ? p.resume : p[key];
        if (Array.isArray(value) ? value.length : value) total += weight;
    }
    return total;
}

function renderSummary() {
    const value = score(profile);
    const missing = [];
    if (!profile.fullName) missing.push("your name");
    if (!profile.experience) missing.push("your experience");
    if (!profile.resume) missing.push("a resume");
    $("profileScore").textContent = `${value}% complete`;
    $("profileSummary").textContent = missing.length
        ? `Add ${missing.join(", ").replace(/, ([^,]*)$/, " and $1")} so emails sound like you.`
        : "Looking good. The AI has what it needs to write personal emails.";
    $("profileMeter").style.width = `${value}%`;
    const meter = $("navProfileMeter");
    meter.hidden = false;
    meter.textContent = `${value}%`;
    meter.classList.toggle("low", value < 60);
}

function renderResume() {
    const resume = profile.resume;
    $("profileResumeZone").classList.toggle("has-file", Boolean(resume));
    $("profileResumeName").textContent = resume ? resume.filename : "No resume uploaded";
    $("profileResumeHint").textContent = resume
        ? `${Math.max(1, Math.round(resume.size / 1024))} KB · click or drop a file to replace it`
        : "Drop a PDF or DOCX (max 5 MB), or click to choose";
    $("profileResumeRemove").hidden = !resume;
}

function setProfile(next, { fillForm = true } = {}) {
    profile = next;
    if (fillForm) {
        for (const [field, id] of Object.entries(FIELDS)) $(id).value = profile[field] || "";
        $("pfSkills").value = (profile.skills || []).join(", ");
    }
    renderSummary();
    renderResume();
    listeners.forEach((listener) => listener(profile));
}

export async function loadProfile() {
    try {
        setProfile((await api("/api/profile")).profile);
    } catch (error) {
        showNotice($("profileNotice"), "error", `Couldn't load your profile: ${error.message}`);
    }
}

export async function saveProfileFields(fields) {
    const data = await api("/api/profile", { method: "PUT", json: fields });
    setProfile(data.profile, { fillForm: false });
    for (const key of Object.keys(fields)) if (FIELDS[key]) $(FIELDS[key]).value = data.profile[key] || "";
    return data.profile;
}

export function resumeFileProblem(file) {
    if (!/\.(pdf|docx)$/i.test(file.name)) return "Upload your resume as a PDF or DOCX file.";
    if (file.size > RESUME_MAX_BYTES) return "Resume exceeds the maximum allowed size (5 MB).";
    return null;
}

export async function uploadResume(file) {
    const problem = resumeFileProblem(file);
    if (problem) throw new Error(problem);
    const form = new FormData();
    form.append("resume", file, file.name);
    const data = await api("/api/profile/resume", { method: "POST", form });
    // Uploading a PDF can fill in the experience text, so refresh the form too.
    setProfile(data.profile, { fillForm: !$("pfExperience").value });
    return data.profile;
}

async function saveProfile(event) {
    event.preventDefault();
    const button = $("saveProfileBtn");
    const fields = {};
    for (const [field, id] of Object.entries(FIELDS)) fields[field] = $(id).value;
    fields.skills = $("pfSkills").value.split(",").map((skill) => skill.trim()).filter(Boolean);

    setBusy(button, true, "Saving");
    hideNotice($("profileNotice"));
    try {
        setProfile((await api("/api/profile", { method: "PUT", json: fields })).profile);
        toast("success", "Profile saved.");
    } catch (error) {
        showNotice($("profileNotice"), "error", error.message);
    } finally {
        setBusy(button, false);
    }
}

async function handleResumeFile(file) {
    if (!file) return;
    hideNotice($("profileNotice"));
    try {
        await uploadResume(file);
        toast("success", `Resume uploaded: ${file.name}`);
    } catch (error) {
        showNotice($("profileNotice"), "error", error.message);
    }
}

export function initProfile() {
    const zone = $("profileResumeZone");
    const input = $("profileResumeInput");
    $("profileForm").addEventListener("submit", saveProfile);
    zone.addEventListener("click", (event) => {
        if (!event.target.closest("#profileResumeRemove")) input.click();
    });
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
        handleResumeFile(event.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => {
        const file = input.files[0];
        input.value = "";
        handleResumeFile(file);
    });
    $("profileResumeRemove").addEventListener("click", async () => {
        if (!window.confirm("Remove your stored resume?")) return;
        try {
            setProfile((await api("/api/profile/resume", { method: "DELETE" })).profile, { fillForm: false });
            toast("info", "Resume removed.");
        } catch (error) {
            showNotice($("profileNotice"), "error", error.message);
        }
    });
    return loadProfile();
}
