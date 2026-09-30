// Step 2: show what was extracted, ask for anything missing, and collect the confirmed details.
import { $, EMAIL_RE, el, renderNotices } from "./util.js";

const LOW_CONFIDENCE = 0.6;
let context = null;

function setHint(id, text, kind = "") {
    const hint = $(`${id}Hint`);
    hint.textContent = text || "";
    hint.className = `field-hint${kind ? ` ${kind}` : ""}`;
    $(id).classList.toggle("needs-attention", kind === "missing" && !$(id).value.trim());
}

function fieldHint(id, value, confidence, missingText) {
    if (!value) setHint(id, missingText, missingText ? "missing" : "");
    else if (typeof confidence === "number" && confidence < LOW_CONFIDENCE) setHint(id, "Please check: I'm not sure about this.", "warn");
    else setHint(id, "");
}

function renderChooser(ctx) {
    const chooser = $("recipientChooser");
    const candidates = ctx.candidateEmails || [];
    if (!ctx.needsRecipientConfirmation || !candidates.length) {
        chooser.hidden = true;
        return;
    }
    $("chooserTitle").textContent = candidates.length > 1
        ? `Multiple email addresses found (${candidates.length}). Which one should receive this email?`
        : "Please confirm the recipient.";
    const options = candidates.map((candidate) => {
        const tags = [];
        if (candidate.suggested) tags.push(el("span", { className: "tag good", text: "Suggested" }));
        if (candidate.noReply) tags.push(el("span", { className: "tag warn", text: "no-reply" }));
        if (!candidate.verified && ctx.sourceType === "screenshot") tags.push(el("span", { className: "tag warn", text: "Read by AI, check spelling" }));
        const radio = el("input", { type: "radio", name: "recipientChoice", value: candidate.email });
        radio.addEventListener("change", () => {
            $("ctxRecipient").value = candidate.email;
            setHint("ctxRecipient", "");
        });
        return el("label", { className: "chooser-option" }, radio, el("span", { text: candidate.email }), ...tags);
    });
    $("chooserOptions").replaceChildren(...options);
    chooser.hidden = false;
}

function recipientHint(ctx) {
    const source = ctx.sourceType === "screenshot" ? "screenshot" : "text";
    if (ctx.recipientEmail) {
        const candidate = (ctx.candidateEmails || []).find((item) => item.email === ctx.recipientEmail);
        const aiOnly = ctx.sourceType === "screenshot" && candidate && !candidate.verified;
        setHint("ctxRecipient", aiOnly ? "Read from the image by AI. Double-check the spelling." : "", aiOnly ? "warn" : "");
    } else if (ctx.needsRecipientConfirmation && (ctx.candidateEmails || []).length) {
        setHint("ctxRecipient", "Choose an address above, or type a different one.", "missing");
    } else {
        setHint("ctxRecipient", `No email address was found in this ${source}. Who should this email be sent to?`, "missing");
    }
}

/** Fills the review card from an EmailContext returned by /api/email-assistant/extract. */
export function renderContext(ctx, profile) {
    context = ctx;
    const confidence = ctx.confidence || {};
    const pill = $("analysisPill");
    pill.hidden = !ctx.analysis;
    pill.className = `pill ${ctx.analysis === "basic" ? "basic" : "ai"}`;
    pill.textContent = ctx.analysis === "basic" ? "Basic extraction" : "Read by AI";
    const warnings = [...(ctx.warnings || [])];
    renderNotices($("reviewWarnings"), warnings, "warn");
    renderChooser(ctx);

    $("ctxRecipient").value = ctx.recipientEmail || "";
    $("ctxRecipientName").value = ctx.recipientName || "";
    $("ctxCompany").value = ctx.companyName || "";
    $("ctxRole").value = ctx.jobTitle || "";
    $("ctxPurpose").value = ctx.context || "";
    $("ctxNote").value = "";

    recipientHint(ctx);
    setHint("ctxRecipientName", "");
    fieldHint("ctxCompany", ctx.companyName, confidence.companyName, "I couldn't find the company. Add it if you know it.");
    const roleNeeded = (ctx.missing || []).includes("jobTitle");
    fieldHint("ctxRole", ctx.jobTitle, confidence.jobTitle, roleNeeded ? "I couldn't determine the exact job title. Add it if you know it." : "");
    fieldHint("ctxPurpose", ctx.context, undefined, "What is the purpose of this email?");

    const details = ctx.importantDetails || [];
    $("ctxDetails").replaceChildren(...details.map((detail) => el("li", { text: detail })));
    $("ctxDetailsGroup").hidden = details.length === 0;

    $("extractedText").textContent = ctx.extractedText || "";
    $("extractedTextBox").hidden = !ctx.extractedText;
    $("extractedTextBox").open = false;

    $("nameAsk").hidden = Boolean(profile && profile.fullName);
    $("askName").value = "";
}

/** Minimal context when reopening a saved draft from history. */
export function renderSavedDetails(record, profile) {
    renderContext(
        {
            sourceType: record.source_type || "clipboard",
            recipientEmail: record.recipient || null,
            companyName: record.company || null,
            jobTitle: record.role || null,
            context: "",
            candidateEmails: [],
            warnings: [],
            missing: [],
            confidence: {},
            emailType: "other",
        },
        profile,
    );
    setHint("ctxPurpose", "Add the purpose before regenerating this saved draft.", "missing");
}

export function clearReview() {
    context = null;
    $("recipientChooser").hidden = true;
    renderNotices($("reviewWarnings"), []);
}

export function collectDetails() {
    const ctx = context || {};
    return {
        recipientEmail: $("ctxRecipient").value.trim(),
        recipientName: $("ctxRecipientName").value.trim(),
        companyName: $("ctxCompany").value.trim(),
        jobTitle: $("ctxRole").value.trim(),
        context: $("ctxPurpose").value.trim(),
        importantDetails: ctx.importantDetails || [],
        emailType: ctx.emailType || "other",
        requestedSubject: ctx.requestedSubject || null,
        resumeRequested: Boolean(ctx.resumeRequested),
        sourceType: ctx.sourceType || "clipboard",
        userNote: $("ctxNote").value.trim(),
        senderName: $("nameAsk").hidden ? "" : $("askName").value.trim(),
        saveSenderName: !$("nameAsk").hidden && $("askNameSave").checked,
    };
}

/** Returns { field, message } when the details aren't enough to write an email, else null. */
export function detailsProblem(details) {
    if (details.recipientEmail && !EMAIL_RE.test(details.recipientEmail)) {
        return { field: $("ctxRecipient"), message: "The recipient email address doesn't look valid." };
    }
    if (!details.context && !details.jobTitle && !details.companyName && !details.userNote) {
        return { field: $("ctxPurpose"), message: "What is the purpose of this email? Add a sentence so I know what to write." };
    }
    return null;
}

export function initReview() {
    for (const id of ["ctxRecipient", "ctxCompany", "ctxRole", "ctxPurpose"]) {
        $(id).addEventListener("input", () => {
            if ($(id).value.trim()) {
                $(id).classList.remove("needs-attention");
                const hint = $(`${id}Hint`);
                if (hint.classList.contains("missing")) setHint(id, "");
            }
        });
    }
    $("ctxRecipient").addEventListener("input", () => {
        const typed = $("ctxRecipient").value.trim().toLowerCase();
        document.querySelectorAll('input[name="recipientChoice"]').forEach((radio) => {
            radio.checked = radio.value === typed;
        });
    });
}
