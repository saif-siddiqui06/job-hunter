// Minimal runner for the browser tests in this folder.
//
//   npm install --no-save playwright && npx playwright install chromium
//   python tests/e2e_server.py 5055            # in another terminal
//   node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/assistant.ui.mjs
//   node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/e2e.flow.mjs
//
// Each test file default-exports `async (page) => result`; the runner exits non-zero on failure.
import path from "node:path";
import { pathToFileURL } from "node:url";

const [url, file] = process.argv.slice(2);
if (!url || !file) {
    console.error("Usage: node tests/frontend/run.mjs <app-url> <test-file.mjs>");
    process.exit(2);
}

let chromium;
try {
    ({ chromium } = await import("playwright"));
} catch {
    console.error("Playwright is not installed. Run: npm install --no-save playwright && npx playwright install chromium");
    process.exit(2);
}

const test = (await import(pathToFileURL(path.resolve(file)).href)).default;
const browser = await chromium.launch();
try {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const result = await test(page);
    console.log(JSON.stringify(result, null, 2));
    const failed = result.ok === false || result.failed > 0;
    process.exitCode = failed ? 1 : 0;
} finally {
    await browser.close();
}
