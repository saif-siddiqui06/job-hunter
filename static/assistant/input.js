// Source box: one place for pasted text or a screenshot (browse, drag and drop, or Ctrl+V).
import { $, hideNotice, showNotice } from "./util.js";

const IMAGE_TYPES = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" };
const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

const EXAMPLES = {
    recruiter: `Hi there,

Thanks for connecting! I'm Sarah, a recruiter at ABC Technologies. We're hiring a Data Analyst for our Pune office (hybrid).

If you're interested, please send your resume to careers@example.com with the subject "DA-2291 Application" before 15 October.

Best regards,
Sarah Khan
Talent Acquisition, ABC Technologies`,
    jobpost: `We're hiring! Northwind Labs is looking for a Backend Developer (Python, Django, PostgreSQL) to join our platform team.

- 2+ years of experience building APIs
- Remote-friendly (India)

To apply, email your CV to jobs@example.org. Shortlisted candidates will hear from us within a week.

#hiring #python #backend`,
    interview: `Hi,

Thank you for applying for the Frontend Engineer role at Contoso. We'd like to invite you to a 30-minute video interview.

Could you reply with two or three time slots that work for you next week?

Kind regards,
Priya Sharma
HR, Contoso
priya.sharma@example.net`,
};

let imageFile = null;
let previewUrl = null;

export const getInput = () => ({ file: imageFile, text: $("pasteInput").value });
export const getPreviewUrl = () => previewUrl;

function imageProblem(file) {
    if (!IMAGE_TYPES[file.type]) return "Please upload a valid image (PNG, JPG or WEBP).";
    if (file.size > IMAGE_MAX_BYTES) return "Image exceeds the maximum allowed size (5 MB).";
    return null;
}

/** Pasted images often arrive as "image.png" or with no usable name; give them a proper one. */
function withImageName(file) {
    if (/\.(png|jpe?g|webp)$/i.test(file.name || "")) return file;
    return new File([file], `pasted-screenshot.${IMAGE_TYPES[file.type]}`, { type: file.type });
}

function updateHint() {
    const count = $("pasteInput").value.length;
    $("pasteCount").textContent = imageFile
        ? "Screenshot ready · Ctrl + Enter to analyze"
        : count ? `${count.toLocaleString()} / 20,000 · Ctrl + Enter to analyze` : "Ctrl + Enter to analyze";
}

export function setImage(file) {
    const problem = imageProblem(file);
    if (problem) {
        showNotice($("inputNotice"), "error", problem);
        return false;
    }
    clearImage();
    imageFile = withImageName(file);
    previewUrl = URL.createObjectURL(imageFile);
    $("shotImage").src = previewUrl;
    $("shotName").textContent = `${imageFile.name} · ${Math.max(1, Math.round(imageFile.size / 1024))} KB`;
    $("shotPreview").hidden = false;
    $("pasteInput").placeholder = "Optional: add a note for this email, e.g. \"mention I can join immediately\"";
    hideNotice($("inputNotice"));
    updateHint();
    return true;
}

function clearImage() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    imageFile = null;
    $("shotInput").value = "";
    $("shotImage").removeAttribute("src");
    $("shotPreview").hidden = true;
    $("pasteInput").placeholder = $("pasteInput").dataset.placeholder;
    updateHint();
}

export function resetInput() {
    clearImage();
    $("pasteInput").value = "";
    hideNotice($("inputNotice"));
    updateHint();
}

function imageFromClipboard(event) {
    const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
    const item = items.find((entry) => entry.kind === "file" && entry.type.startsWith("image/"));
    return item ? item.getAsFile() : null;
}

/**
 * @param {{ onAnalyze: () => void, acceptsPastedImage: (event: ClipboardEvent) => boolean }} hooks
 */
export function initInput({ onAnalyze, acceptsPastedImage }) {
    const box = $("sourceBox");
    const text = $("pasteInput");
    text.dataset.placeholder = text.placeholder;

    $("shotPick").addEventListener("click", () => $("shotInput").click());
    $("shotInput").addEventListener("change", () => $("shotInput").files[0] && setImage($("shotInput").files[0]));
    $("shotRemove").addEventListener("click", () => {
        clearImage();
        text.focus();
    });

    const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
    box.addEventListener("dragover", (event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        box.classList.add("dragging");
    });
    box.addEventListener("dragleave", (event) => {
        if (!box.contains(event.relatedTarget)) box.classList.remove("dragging");
    });
    box.addEventListener("drop", (event) => {
        box.classList.remove("dragging");
        if (!hasFiles(event)) return;
        event.preventDefault();
        setImage(event.dataTransfer.files[0]);
    });

    // Screenshots copied with Snipping Tool / Print Screen / a browser arrive as clipboard image files.
    document.addEventListener("paste", (event) => {
        const file = imageFromClipboard(event);
        if (!file) return;
        // Copying from Word/Outlook puts both text and an image rendition on the clipboard; text wins in text fields.
        const pastedText = event.clipboardData.getData("text/plain");
        const inTextField = event.target instanceof Element && event.target.closest("input, textarea");
        const inSource = event.target instanceof Element && box.contains(event.target);
        if ((inTextField && !inSource && pastedText.trim()) || (inSource && pastedText.trim()) || !acceptsPastedImage(event)) return;
        event.preventDefault();
        if (setImage(file)) $("analyzeBtn").focus();
    });

    text.addEventListener("input", updateHint);
    text.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onAnalyze();
        }
    });
    document.querySelectorAll("[data-example]").forEach((chip) => {
        chip.addEventListener("click", () => {
            clearImage();
            text.value = EXAMPLES[chip.dataset.example];
            updateHint();
            text.focus();
        });
    });
    $("analyzeBtn").addEventListener("click", onAnalyze);
    updateHint();
}
