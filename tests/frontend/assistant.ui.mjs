// Frontend tests for Apply Rocket. The backend is mocked with page.route(), so these test the browser
// code in isolation. Run with:  node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/assistant.ui.mjs

const PNG_1PX = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64",
);

const PROFILE = {
    fullName: "Saif Siddiqui", email: "", phone: "", linkedinUrl: "", portfolioUrl: "", headline: "",
    skills: [], experience: "Data analyst intern", resume: { filename: "Saif_Siddiqui_Resume.pdf", size: 1000, uploadedAt: "2026-09-29T10:00:00Z" },
};

const CONTEXT = {
    sourceType: "screenshot", recipientEmail: "careers@example.com", suggestedRecipient: null,
    needsRecipientConfirmation: false,
    candidateEmails: [{ email: "careers@example.com", verified: true, noReply: false, suggested: false }],
    recipientName: "Sarah Khan", companyName: "ABC Technologies", jobTitle: "Data Analyst", emailType: "job_application",
    context: "Recruiter requested the user's resume for the Data Analyst position.", importantDetails: ["Deadline: 15 October"],
    requestedSubject: null, resumeRequested: true, extractedText: "Please send your resume to careers@example.com",
    confidence: { recipientEmail: 1, companyName: 0.9, jobTitle: 0.9 }, missing: [], warnings: [], analysis: "ai",
};

const DRAFT = {
    subject: "Application for Data Analyst - Saif Siddiqui",
    body: "Hello Sarah,\n\nI'd like to apply for the Data Analyst position at ABC Technologies.\n\nBest regards,\nSaif Siddiqui",
    attachResume: true, mode: "ai", warnings: [],
};

const CONNECTED = { connected: true, method: "app_password", account: "me@gmail.com", googleConfigured: false };
const DISCONNECTED = { connected: false, method: null, account: null, googleConfigured: false };

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

const json = (body, status = 200, delay = 0) => ({ status, body, delay });

export default async function run(page) {
    const base = new URL(page.url()).origin;
    const results = [];
    let calls = [];
    page.setDefaultTimeout(10000);
    // Web fonts are cosmetic; don't let a slow network stall page loads.
    await page.context().route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());

    async function setup(overrides = {}, hash = "") {
        calls = [];
        const handlers = {
            "GET /api/auth/me": json({ success: true, username: "tester", signupCodeRequired: false }),
            "GET /api/profile": json({ success: true, profile: PROFILE }),
            "GET /api/list-activities": json({ success: true, activities: [] }),
            "GET /auth/status": json(CONNECTED),
            "POST /api/email-assistant/extract": json({ success: true, context: CONTEXT }),
            "POST /api/email-assistant/draft": json({ success: true, historyId: "h1", draft: DRAFT }),
            "POST /api/email-assistant/send": json({ success: true, historyId: "h1", sentAt: "2026-09-29T10:05:00Z" }),
            "PUT /api/profile": (request) => json({ success: true, profile: { ...PROFILE, ...JSON.parse(request.postData()) } }),
            ...overrides,
        };
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await page.context().route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
        await page.route(
            (url) => url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/") || url.pathname === "/send",
            async (route) => {
                const request = route.request();
                const key = `${request.method()} ${new URL(request.url()).pathname}`;
                const isJson = (request.headers()["content-type"] || "").includes("application/json");
                calls.push({ key, headers: request.headers(), body: isJson ? JSON.parse(request.postData()) : null });
                const handler = handlers[key];
                const response = typeof handler === "function" ? handler(request, calls) : handler;
                if (!response) return route.fulfill({ status: 404, json: { success: false, error: `not mocked: ${key}` } });
                if (response.delay) await new Promise((resolve) => setTimeout(resolve, response.delay));
                const body = typeof response.body === "string" ? response.body : JSON.stringify(response.body);
                await route.fulfill({ status: response.status, contentType: response.contentType || "application/json", body });
            },
        );
        // Going via about:blank forces a real load; a hash-only change would keep the previous test's page state.
        await page.goto("about:blank");
        // The app shell is loaded directly; sign-in is covered by e2e.flow.mjs against the real backend.
        await page.goto(`${base}/static/index.html${hash}`, { waitUntil: "domcontentloaded" });
        await page.waitForFunction(() => document.getElementById("gmailAccount").textContent !== "Checking…");
    }

    const called = (key) => calls.filter((call) => call.key === key);
    const visible = (selector) => page.locator(selector).isVisible();
    const text = (selector) => page.locator(selector).innerText();
    const value = (selector) => page.locator(selector).inputValue();
    const uploadScreenshot = () => page.setInputFiles("#shotInput", { name: "recruiter.png", mimeType: "image/png", buffer: PNG_1PX });

    async function toEmail() {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#workspace").waitFor();
        await page.click("#generateBtn");
        await page.locator("#mailForm").waitFor();
    }

    async function test(name, body, overrides, hash) {
        try {
            await setup(overrides, hash);
            await body();
            results.push({ name, ok: true });
        } catch (error) {
            results.push({ name, ok: false, error: error.message.split("\n")[0] });
        }
    }

    // ---- Shell & setup ------------------------------------------------------------

    await test("sidebar navigation switches views", async () => {
        assert(await visible("#view-compose"), "compose not the default view");
        await page.click('.nav-item[data-view="history"]');
        await page.locator("#view-history").waitFor();
        assert(!(await visible("#view-compose")), "compose still visible");
        assert((await page.getAttribute('.nav-item[data-view="history"]', "aria-current")) === "page", "active nav not marked");
        await page.click('.nav-item[data-view="profile"]');
        await page.locator("#view-profile").waitFor();
        assert((await value("#pfName")) === "Saif Siddiqui", "profile not loaded into the form");
    });

    await test("setup checklist reflects Gmail and profile state", async () => {
        assert((await text("#setupCount")) === "1 of 3 done", `unexpected count ${await text("#setupCount")}`);
        assert(await page.locator("#setupResume.done").count() === 1, "resume step not done");
        assert(await page.locator("#setupGmail.done").count() === 0, "gmail step marked done while disconnected");
        assert((await text("#gmailTitle")) === "Gmail not connected", "sidebar status wrong");
    }, { "GET /api/profile": json({ success: true, profile: { ...PROFILE, experience: "" } }), "GET /auth/status": json(DISCONNECTED) });

    await test("Google sign-in problems come back as a friendly message", async () => {
        await page.locator(".toast", { hasText: "isn't set up on this computer" }).waitFor();
        assert(await page.locator("#gmailDialog[open]").count() === 1, "connect dialog not offered");
        assert(!(await page.url()).includes("google_auth"), "query string not cleaned up");
    }, { "GET /auth/status": json(DISCONNECTED) }, "?google_auth=missing_config");

    await test("Connect Gmail verifies the App Password and updates the status", async () => {
        let connected = false;
        await setup({
            "GET /auth/status": () => json(connected ? CONNECTED : DISCONNECTED),
            "POST /api/gmail/app-password": (request) => {
                const body = JSON.parse(request.postData());
                if (body.appPassword.replace(/\s/g, "") !== "abcdefghijklmnop") return json({ success: false, error: "Gmail rejected that App Password." }, 401);
                connected = true;
                return json({ success: true, connection: { method: "app_password", account: "me@gmail.com" } });
            },
        });
        await page.click("#gmailManageBtn");
        await page.fill("#apEmail", "me@gmail.com");
        await page.fill("#apPassword", "wrong password xx");
        await page.click("#apConnectBtn");
        await page.locator("#apNotice", { hasText: "rejected" }).waitFor();
        await page.fill("#apPassword", "abcd efgh ijkl mnop");
        await page.click("#apConnectBtn");
        await page.waitForFunction(() => !document.getElementById("gmailDialog").open);
        assert((await text("#gmailTitle")) === "Gmail connected" && (await text("#gmailAccount")) === "me@gmail.com", "status not updated");
        assert(called("POST /api/gmail/app-password")[1].headers["x-requested-with"] === "ApplyRocket", "CSRF header missing");
    }, {});

    // ---- Source input ----------------------------------------------------------------

    await test("screenshot shows a preview and can be removed", async () => {
        await uploadScreenshot();
        assert(await visible("#shotPreview"), "preview not shown");
        assert((await text("#shotName")).includes("recruiter.png"), "file name not shown");
        assert((await page.getAttribute("#shotImage", "src")).startsWith("blob:"), "image preview missing");
        await page.click("#shotRemove");
        assert(!(await visible("#shotPreview")), "preview not removed");
    });

    await test("rejects a non-image file and an image over 5 MB", async () => {
        await page.setInputFiles("#shotInput", { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
        assert((await text("#inputNotice")).includes("Please upload a valid image"), "no invalid-image message");
        await page.setInputFiles("#shotInput", { name: "big.png", mimeType: "image/png", buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
        assert((await text("#inputNotice")).includes("maximum allowed size"), "no size message");
        assert(!(await visible("#shotPreview")), "preview shown for an invalid file");
    });

    await test("pasting an image from the clipboard loads it as the screenshot", async () => {
        await page.evaluate(async (bytes) => {
            const data = new DataTransfer();
            data.items.add(new File([new Uint8Array(bytes)], "image.png", { type: "image/png" }));
            document.body.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true }));
        }, [...PNG_1PX]);
        assert(await visible("#shotPreview"), "pasted image not previewed");
        assert((await text("#shotName")).startsWith("pasted-screenshot.png") || (await text("#shotName")).startsWith("image.png"), "pasted file not named");
    });

    await test("example chips fill the box and empty input is caught", async () => {
        await page.click("#analyzeBtn");
        assert((await text("#inputNotice")).includes("Paste a message"), "empty input not caught");
        await page.click('[data-example="jobpost"]');
        assert((await value("#pasteInput")).includes("Backend Developer"), "example not filled");
    });

    await test("shows a loading state while analyzing", async () => {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        const button = page.locator("#analyzeBtn");
        assert(await button.isDisabled(), "analyze button not disabled");
        assert((await button.innerText()).includes("Reading screenshot"), "no loading label");
        assert((await page.getAttribute("#inputCard", "aria-busy")) === "true", "not marked busy");
        await page.locator("#workspace").waitFor();
    }, { "POST /api/email-assistant/extract": json({ success: true, context: CONTEXT }, 200, 700) });

    await test("extraction failure stays on the source step with the error", async () => {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#inputNotice").waitFor();
        assert((await text("#inputNotice")).includes("We couldn't read this screenshot"), "error not shown");
        assert(!(await visible("#workspace")), "moved on despite failure");
        assert(await page.locator("#analyzeBtn").isEnabled(), "analyze left disabled");
    }, { "POST /api/email-assistant/extract": json({ success: false, error: "We couldn't read this screenshot. Try a clearer image." }, 422) });

    // ---- Details ------------------------------------------------------------------------

    await test("pasted text is analyzed and the details are shown", async () => {
        await page.fill("#pasteInput", "Please send your resume to careers@example.com for the Data Analyst role.");
        await page.keyboard.press("Control+Enter");
        await page.locator("#workspace").waitFor();
        assert(called("POST /api/email-assistant/extract")[0].body.text.includes("careers@example.com"), "text not sent");
        assert((await value("#ctxRecipient")) === "careers@example.com", "recipient not filled");
        assert((await value("#ctxCompany")) === "ABC Technologies" && (await value("#ctxRole")) === "Data Analyst", "company/role not filled");
        assert((await text("#analysisPill")) === "Read by AI", "analysis badge missing");
        assert(await visible("#mailEmpty"), "email pane should wait for Write my email");
        await page.click("#sourcePeek");
        assert(await visible("#inputCard"), "Change source does not go back");
    });

    await test("a screenshot plus typed text uses the text as the note", async () => {
        await page.fill("#pasteInput", "Mention I can join immediately");
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#workspace").waitFor();
        assert((await value("#ctxNote")) === "Mention I can join immediately", "note not carried over");
    });

    await test("multiple addresses require the user to choose", async () => {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#recipientChooser").waitFor();
        assert((await text("#chooserTitle")).includes("Multiple email addresses found"), "no chooser title");
        assert((await value("#ctxRecipient")) === "", "recipient was pre-filled");
        await page.locator(".chooser-option", { hasText: "careers@example.com" }).click();
        assert((await value("#ctxRecipient")) === "careers@example.com", "choice not applied");
    }, {
        "POST /api/email-assistant/extract": json({ success: true, context: {
            ...CONTEXT, recipientEmail: null, needsRecipientConfirmation: true, suggestedRecipient: "careers@example.com",
            candidateEmails: [
                { email: "hr@example.com", verified: true, noReply: false, suggested: false },
                { email: "careers@example.com", verified: true, noReply: false, suggested: true },
            ],
            missing: ["recipientEmail"],
        } }),
    });

    await test("missing email, company and role are asked for, not invented", async () => {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#workspace").waitFor();
        assert((await text("#ctxRecipientHint")).includes("No email address was found in this screenshot"), "no missing-recipient prompt");
        assert((await text("#ctxRoleHint")).includes("couldn't determine the exact job title"), "no missing-role prompt");
        assert((await value("#ctxCompany")) === "", "company invented");
        await page.fill("#ctxRecipient", "manual@example.com");
        await page.click("#generateBtn");
        await page.locator("#mailForm").waitFor();
        assert((await value("#mailTo")) === "manual@example.com", "manual recipient not used");
    }, {
        "POST /api/email-assistant/extract": json({ success: true, context: {
            ...CONTEXT, recipientEmail: null, candidateEmails: [], companyName: null, jobTitle: null, recipientName: null,
            missing: ["recipientEmail", "jobTitle", "companyName"],
        } }),
    });

    await test("missing signature name is asked for, saved, then hidden", async () => {
        await uploadScreenshot();
        await page.click("#analyzeBtn");
        await page.locator("#nameAsk").waitFor();
        await page.fill("#askName", "Saif Siddiqui");
        await page.click("#generateBtn");
        await page.locator("#mailForm").waitFor();
        assert(called("PUT /api/profile")[0].body.fullName === "Saif Siddiqui", "name not saved");
        assert(called("POST /api/email-assistant/draft")[0].body.senderName === "Saif Siddiqui", "name not used for the draft");
        assert(!(await visible("#nameAsk")), "question still shown after saving");
    }, { "GET /api/profile": json({ success: true, profile: { ...PROFILE, fullName: "" } }) });

    // ---- Email -----------------------------------------------------------------------------

    await test("email is previewed, editable, and rewritten on request", async () => {
        await toEmail();
        assert((await value("#mailSubject")) === DRAFT.subject, "subject not shown");
        assert(await page.locator("#attachResume").isChecked(), "resume not attached");
        assert((await text("#attachmentName")).includes("Saif_Siddiqui_Resume.pdf"), "attachment name missing");
        assert((await text("#mailFrom")).includes("me@gmail.com"), "From line missing");
        assert((await text("#mailStatus")) === "Draft", "status pill missing");

        await page.fill("#mailBody", "My own edited text");
        page.once("dialog", (dialog) => dialog.dismiss());
        await page.click("#regenerateBtn");
        assert((await value("#mailBody")) === "My own edited text", "edits lost after cancelling");
        assert(called("POST /api/email-assistant/draft").length === 1, "rewrote despite cancel");

        await page.click('#styleGroup label:has(input[value="concise"])');
        await page.click('#lengthGroup label:has(input[value="medium"])');
        page.once("dialog", (dialog) => dialog.accept());
        await page.click("#regenerateBtn");
        await page.waitForFunction(() => document.getElementById("mailBody").value.includes("concise"));
        const rewrite = called("POST /api/email-assistant/draft")[1].body;
        assert(rewrite.style === "concise" && rewrite.length === "medium", "tone/length not sent");
        assert(rewrite.historyId === "h1", "rewrite did not reuse the draft record");
        assert(called("POST /api/email-assistant/extract").length === 1, "screenshot was re-read");
    }, {
        "POST /api/email-assistant/draft": (_request, all) => json({
            success: true, historyId: "h1",
            draft: all.filter((c) => c.key === "POST /api/email-assistant/draft").length > 1 ? { ...DRAFT, body: "Hello Sarah,\n\nA concise version." } : DRAFT,
        }),
    });

    await test("send posts the edited email once and locks the composer", async () => {
        await toEmail();
        await page.fill("#mailBody", "Edited body before sending");
        await page.locator("#sendMailBtn").dblclick();
        await page.locator("#composeNotice.success").waitFor();
        const sends = called("POST /api/email-assistant/send");
        assert(sends.length === 1, `expected 1 send, got ${sends.length}`);
        const { body, headers } = sends[0];
        assert(body.body === "Edited body before sending" && body.to === "careers@example.com", "edited draft not sent");
        assert(body.attachResume === true && body.historyId === "h1" && !("auth" in body), "wrong send payload");
        assert(headers["idempotency-key"] && headers["idempotency-key"].length >= 8, "no idempotency key");
        assert((await text("#sendMailBtn")) === "Sent" && (await page.locator("#sendMailBtn").isDisabled()), "send not locked");
        assert((await text("#mailStatus")) === "Sent", "status pill not updated");
        assert(await page.locator("#mailBody").getAttribute("readonly") !== null, "still editable after send");
    }, { "POST /api/email-assistant/send": json({ success: true, historyId: "h1", sentAt: "2026-09-29T10:05:00Z" }, 200, 400) });

    await test("send failure keeps the email and retries with the same request id", async () => {
        await toEmail();
        await page.fill("#mailSubject", "My edited subject");
        await page.click("#sendMailBtn");
        await page.locator("#composeNotice.error").waitFor();
        assert((await text("#composeNotice")).includes("Gmail is not responding"), "failure not explained");
        assert((await value("#mailSubject")) === "My edited subject", "email lost");
        assert((await text("#mailStatus")) === "Not sent", "status not marked");
        assert(await page.locator("#sendMailBtn").isEnabled(), "cannot retry");
        await page.click("#sendMailBtn");
        await page.locator("#composeNotice.error").waitFor();
        const [first, second] = called("POST /api/email-assistant/send");
        assert(first.headers["idempotency-key"] === second.headers["idempotency-key"], "retry changed the request id");
    }, { "POST /api/email-assistant/send": json({ success: false, error: "Gmail is not responding right now. Your draft is saved; try again shortly.", code: "send_failed", historyId: "h1" }, 502) });

    await test("sending without Gmail opens Connect Gmail instead", async () => {
        await toEmail();
        await page.click("#sendMailBtn");
        await page.locator("#gmailDialog[open]").waitFor();
        assert((await text("#composeNotice")).includes("Connect Gmail first"), "no explanation");
        assert(called("POST /api/email-assistant/send").length === 0, "sent without Gmail");
        assert((await value("#mailSubject")) === DRAFT.subject, "email lost");
    }, { "GET /auth/status": json(DISCONNECTED) });

    await test("invalid recipient is caught before sending", async () => {
        await toEmail();
        await page.fill("#mailTo", "not-an-email");
        await page.click("#sendMailBtn");
        assert((await text("#composeNotice")).includes("isn't valid"), "invalid recipient accepted");
        assert(called("POST /api/email-assistant/send").length === 0, "sent to invalid recipient");
    });

    // ---- History & batch --------------------------------------------------------------------

    const HISTORY = [
        { id: "d1", status: "draft", recipient: "hr@acme.com", subject: '<img src=x onerror="window.__xss=1">', body: "Saved body", company: "Acme", role: "Engineer", created_at: "2026-09-29T10:00:00Z", updated_at: "2026-09-29T10:00:00Z" },
        { id: "s1", status: "sent", recipient: "jobs@globex.com", subject: "Application for Analyst", body: "Sent body", company: "Globex", role: "Analyst", created_at: "2026-09-28T10:00:00Z", sent_at: new Date().toISOString() },
        { id: "f1", status: "failed", recipient: "x@initech.com", subject: "Failed one", body: "Body", error: "Gmail is not responding", created_at: "2026-09-27T10:00:00Z" },
    ];

    await test("history shows stats, filters, search, and renders text safely", async () => {
        await page.locator(".history-row").first().waitFor();
        assert((await text("#statSent")) === "1" && (await text("#statDraft")) === "1" && (await text("#statFailed")) === "1", "stats wrong");
        assert((await text("#navHistoryCount")) === "2", "unsent badge wrong");
        assert((await page.locator("#activityList img").count()) === 0 && !(await page.evaluate(() => window.__xss)), "HTML injected");
        await page.click('#historyFilter label:has(input[value="sent"])');
        assert((await page.locator(".history-row").count()) === 1, "filter not applied");
        await page.click('#historyFilter label:has(input[value="all"])');
        await page.fill("#historySearch", "initech");
        assert((await page.locator(".history-row").count()) === 1, "search not applied");
    }, { "GET /api/list-activities": json({ success: true, activities: HISTORY }) }, "#history");

    await test("history detail reopens a draft in Compose", async () => {
        await page.locator(".history-row").first().click();
        await page.locator("#historyDialog[open]").waitFor();
        assert((await text("#historyDialogBody")) === "Saved body", "detail body missing");
        await page.locator("#historyDialogActions .btn", { hasText: "Open in Compose" }).click();
        await page.locator("#mailForm").waitFor();
        assert(await visible("#view-compose"), "did not switch to Compose");
        assert((await value("#mailTo")) === "hr@acme.com" && (await value("#mailBody")) === "Saved body", "draft not reopened");
    }, { "GET /api/list-activities": json({ success: true, activities: HISTORY }) }, "#history");

    await test("batch previews CSV recipients and needs Gmail before sending", async () => {
        await page.fill("#subject", "Hello");
        await page.fill("#message", "Hi there");
        await page.setInputFiles("#csvFile", { name: "list.csv", mimeType: "text/csv", buffer: Buffer.from("name,email\nA,a@x.com\nB,b@y.com\nC,c@z.com\n") });
        await page.locator("#csvPreview").waitFor();
        assert((await text("#csvPreview")).includes("Sending to 3 recipients"), "recipients not previewed");
        assert((await text("#sendBtn")) === "Send to 3 recipients", "send label not updated");
        await page.click("#sendBtn");
        await page.locator("#gmailDialog[open]").waitFor();
        assert(called("POST /send").length === 0, "sent without Gmail");
    }, { "GET /auth/status": json(DISCONNECTED) }, "#batch");

    await page.unrouteAll({ behavior: "ignoreErrors" });
    const failed = results.filter((result) => !result.ok);
    return { passed: results.length - failed.length, failed: failed.length, results: failed.length ? results : results.map((r) => r.name) };
}
