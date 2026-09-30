// End-to-end flow against the real backend started with `python tests/e2e_server.py 5055`
// (real routes, validation, extraction merge, drafting, idempotency, history and batch send;
// fake AI model, fake Gmail). Restart the server before each run: it keeps state in memory.
//   node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/e2e.flow.mjs

const PDF = Buffer.from("%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n");

/** Draws a small "screenshot" in the page and returns its PNG bytes. */
async function renderScreenshot(page) {
    const bytes = await page.evaluate(async () => {
        const canvas = Object.assign(document.createElement("canvas"), { width: 420, height: 90 });
        const context = canvas.getContext("2d");
        context.fillStyle = "#fff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#000";
        context.font = "16px sans-serif";
        context.fillText("Please send your resume to careers@example.com", 10, 45);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
        return [...new Uint8Array(await blob.arrayBuffer())];
    });
    return Buffer.from(bytes);
}

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

export default async function run(page) {
    const base = new URL(page.url()).origin;
    const steps = [];
    const step = (name) => steps.push(name);
    page.setDefaultTimeout(15000);
    page.on("dialog", (dialog) => dialog.accept()); // batch confirmation
    await page.context().route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
    await page.goto(base, { waitUntil: "domcontentloaded" });

    const value = (selector) => page.locator(selector).inputValue();
    const text = (selector) => page.locator(selector).innerText();
    const sent = () => page.evaluate(() => fetch("/__e2e/sent").then((r) => r.json()));

    try {
        // ---- 0. Sign-up with an invite code ------------------------------------------------
        assert(new URL(page.url()).pathname === "/login", "not redirected to sign-in");
        await page.click('label:has(input[name="authMode"][value="signup"])');
        await page.locator("#inviteField").waitFor();
        await page.fill("#username", "saif");
        await page.fill("#password", "password123");
        await page.fill("#inviteCode", "wrong-code");
        await page.click("#authSubmit");
        await page.locator("#authNotice", { hasText: "invite code" }).waitFor();
        await page.fill("#inviteCode", "e2e-invite");
        await page.click("#authSubmit");
        await page.waitForURL(`${base}/`);
        await page.waitForFunction(() => document.getElementById("gmailAccount").textContent !== "Checking…");
        assert((await text("#accountName")) === "saif", "signed-in user not shown");
        step("sign-up: wrong invite code rejected, right one creates the account and signs in");

        assert((await text("#gmailTitle")) === "Gmail not connected", "should start disconnected");

        // ---- 1. Pasted text -> email -> connect Gmail -> send ------------------------------
        await page.click('[data-example="recruiter"]');
        await page.click("#analyzeBtn");
        await page.locator("#workspace").waitFor();
        assert((await value("#ctxRecipient")) === "careers@example.com", "text: recipient not extracted");
        assert((await value("#ctxRole")) === "Data Analyst" && (await value("#ctxCompany")) === "ABC Technologies", "text: role/company");
        assert(await page.locator("#nameAsk").isVisible(), "text: signature name not asked for");
        step("example message analyzed: recipient, company and role found; signature name requested");

        await page.fill("#askName", "Saif Siddiqui");
        await page.click("#generateBtn");
        await page.locator("#mailForm").waitFor();
        const body = await value("#mailBody");
        assert(body.startsWith("Hello Sarah,") && body.endsWith("Best regards,\nSaif Siddiqui"), `text: body/signature wrong: ${body}`);
        assert(!(await page.locator("#nameAsk").isVisible()), "text: name question still shown");
        assert((await text("#draftWarnings")).includes("none is on file"), "text: missing-resume warning absent");
        step("email written from the profile; name saved; missing-resume warning shown");

        await page.setInputFiles("#composeResumeInput", { name: "Saif_Siddiqui_Resume.pdf", mimeType: "application/pdf", buffer: PDF });
        await page.waitForFunction(() => document.getElementById("attachResume").checked);
        await page.click("#sendMailBtn");
        await page.locator("#gmailDialog[open]").waitFor();
        assert((await sent()).length === 0, "sent before Gmail was connected");
        step("Send without Gmail opened Connect Gmail and sent nothing");

        await page.fill("#apEmail", "e2e.sender@gmail.com");
        await page.fill("#apPassword", "wrong wrong wrong");
        await page.click("#apConnectBtn");
        await page.locator("#apNotice", { hasText: "rejected" }).waitFor();
        await page.fill("#apPassword", "abcd efgh ijkl mnop");
        await page.click("#apConnectBtn");
        await page.waitForFunction(() => !document.getElementById("gmailDialog").open);
        assert((await text("#gmailAccount")) === "e2e.sender@gmail.com", "sidebar not updated after connecting");
        assert((await text("#mailFrom")).includes("e2e.sender@gmail.com"), "From line not updated");
        step("wrong App Password rejected, correct one connected; sidebar and From updated");

        await page.click("#sendMailBtn");
        await page.locator("#composeNotice.success").waitFor();
        let log = await sent();
        assert(log.length === 1 && log[0].to === "careers@example.com" && log[0].attachments[0] === "Saif_Siddiqui_Resume.pdf", "text: not sent with resume");
        step("email sent with the resume attached");

        // ---- 2. Screenshot, two addresses, failure then retry -------------------------------
        await page.click("#newEmailBtn");
        await page.locator("#inputCard").waitFor();
        await page.setInputFiles("#shotInput", { name: "recruiter.png", mimeType: "image/png", buffer: await renderScreenshot(page) });
        await page.click("#analyzeBtn");
        await page.locator("#recipientChooser").waitFor();
        assert((await value("#ctxRecipient")) === "", "shot: recipient chosen silently");
        await page.locator(".chooser-option", { hasText: "careers@example.com" }).click();
        await page.click("#generateBtn");
        await page.locator("#mailForm").waitFor();
        await page.click('#styleGroup label:has(input[value="concise"])');
        await page.click("#regenerateBtn");
        await page.waitForFunction(() => document.getElementById("mailBody").value.includes("concise version"));
        step("screenshot: user picked 1 of 2 addresses; rewritten in concise tone");

        const subject = await value("#mailSubject");
        await page.fill("#mailSubject", `${subject} FAIL`);
        await page.click("#sendMailBtn");
        await page.locator("#composeNotice.error").waitFor();
        assert((await value("#mailSubject")).endsWith("FAIL"), "shot: email lost after failure");
        await page.fill("#mailSubject", subject);
        await page.click("#sendMailBtn");
        await page.locator("#composeNotice.success").waitFor();
        log = await sent();
        assert(log.length === 2 && log[1].subject === subject, "shot: retry not sent exactly once");
        step("send failure kept the email; retry sent once");

        // ---- 3. History ---------------------------------------------------------------------
        await page.click('.nav-item[data-view="history"]');
        await page.waitForFunction(() => document.getElementById("statSent").textContent === "2");
        const history = (await page.evaluate(() => fetch("/api/list-activities").then((r) => r.json()))).activities;
        assert(history.length === 2 && history.every((r) => r.status === "sent"), "history: wrong entries");
        assert(history[1].attachment.filename === "Saif_Siddiqui_Resume.pdf" && history[0].source_type === "screenshot", "history: metadata");
        await page.locator(".history-row").first().click();
        await page.locator("#historyDialog[open]").waitFor();
        assert((await text("#historyDialogMeta")).includes("careers@example.com"), "history: detail missing");
        await page.keyboard.press("Escape");
        step("history: 2 sent emails with source, attachment and a working detail view");

        // ---- 4. Batch send ----------------------------------------------------------------
        await page.click('.nav-item[data-view="batch"]');
        await page.fill("#subject", "Open to Data Analyst roles");
        await page.fill("#message", "Hi,\n\nI'm exploring Data Analyst roles and would love to connect.\n\nBest,\nSaif");
        await page.setInputFiles("#csvFile", { name: "recruiters.csv", mimeType: "text/csv", buffer: Buffer.from("email,name\na@example.com,A\nb@example.com,B\n") });
        await page.locator("#csvPreview").waitFor();
        await page.click("#sendBtn");
        await page.locator("#result.success").waitFor();
        assert((await text("#result")).includes("2 of 2 emails sent"), "batch: wrong result");
        log = await sent();
        assert(log.filter((entry) => entry.batch).length === 2, "batch: emails not sent");
        step("batch sent to 2 recipients with the connected Gmail");

        // ---- 5. Log out -------------------------------------------------------------------
        await page.click("#logoutBtn");
        await page.waitForURL(`${base}/login`);
        const blocked = await page.evaluate(() => fetch("/api/list-activities").then((r) => r.status));
        assert(blocked === 401, "data still reachable after logging out");
        step("log out returns to sign-in and locks the data");

        return { ok: true, steps };
    } catch (error) {
        return { ok: false, failedAfter: steps, error: error.message.split("\n")[0] };
    }
}
