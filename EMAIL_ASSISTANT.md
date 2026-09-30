# AI Email Assistant

Turn a screenshot or pasted text (recruiter message, LinkedIn DM, job post, email) into a ready-to-send email:

```text
Screenshot / pasted text -> extract details -> you confirm -> AI writes subject + body -> you edit -> Send -> history
```

Nothing is ever sent automatically. The email only goes out when you click **Send email** in the preview.

It's the **Compose** page of the Flask app. The app also has **History**, **Batch send** and **Profile** pages.

## Setup

1. Create a file named `.env` in the project folder. It's git-ignored, and real environment variables override it:
   ```text
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your-key        # free: https://aistudio.google.com -> Get API key
   ```
2. Install and run:
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
3. Open http://127.0.0.1:5000, click **Connect Gmail** in the sidebar, and fill in your **Profile**.

The session secret is generated on first run and saved in `.flask_secret` (git-ignored), so restarts don't disconnect Gmail. Set `FLASK_SECRET_KEY` to use your own.

### AI provider

The app talks to models through one provider interface (`services/ai.py`), so you can switch providers without code changes. Keys are read from the server environment and are never sent to the browser.

| Variable | Default | Notes |
|---|---|---|
| `AI_PROVIDER` | `auto` | `auto`, `gemini`, `openai`, `ollama` or `none` (no AI; rule-based extraction and a template draft). |
| `AI_API_KEY` / `AI_MODEL` | | Key/model for the provider named in `AI_PROVIDER`, as an alternative to the specific variables below. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | `gemini-flash-latest` | **Recommended.** Free tier, reads screenshots, structured JSON output. |
| `GEMINI_FALLBACK_MODEL` | `gemini-flash-lite-latest` | Used automatically when the main model is busy (429/503). |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | `gpt-5-mini` | Paid. Reads screenshots. `OPENAI_BASE_URL` for compatible APIs. |
| `OLLAMA_URL`, `OLLAMA_MODEL` | `http://localhost:11434`, `llama3.1` | Local and private. Text only unless `OLLAMA_VISION_MODEL` (e.g. `llama3.2-vision`) is set. |
| `TESSERACT_CMD` | auto-detected | Optional OCR. Install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) for independent verification of addresses read from screenshots. |

In `auto` mode the order is Gemini, then Ollama, then OpenAI, skipping any that aren't configured. Ollama only counts as configured when an `OLLAMA_*` variable is set. **If `OPENAI_API_KEY` is set in your environment, `auto` will use it (paid) whenever Gemini isn't configured or fails.** Set `AI_PROVIDER=gemini` to prevent that.

Privacy: screenshots and text are sent to the provider you configure. Gemini's free tier may use prompts to improve Google's products. Use `ollama` or `none` for fully local processing.

If no model is available the assistant still works in basic mode: rule-based extraction from pasted text or OCR text, and a plain template draft, clearly labelled so you review it.

### Gmail

Click **Connect Gmail** in the sidebar. Compose and Batch send both use the connection:

1. **App Password** (works right away). Turn on 2-Step Verification, create an App Password at https://myaccount.google.com/apppasswords, then paste it into the dialog. The app checks it with Gmail before saving, so a wrong password fails immediately instead of at send time.
2. **Google sign-in** (optional). Create an OAuth "Web application" client in Google Cloud Console, enable the Gmail API, add `http://127.0.0.1:5000/auth/google/callback` as a redirect URI, and set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. Only the `gmail.send` scope is requested. If it isn't set up, the dialog says so instead of showing an error.

Connections are stored on this computer in `.gmail_tokens.json` (git-ignored). The browser only holds a random session id, and the password never goes back to the browser.

## Using it

1. **Source.** Paste text into the box, or drop, browse or **Ctrl+V** a screenshot (Snipping Tool works). With a screenshot attached, any text you type becomes your note. Use the example chips to see it work.
2. **Details.** Check what was extracted. Fields that couldn't be found are left empty with a question instead of being guessed. If several addresses were found, you pick the recipient; nothing is preselected. Addresses read only by the AI from an image are flagged for a spelling check.
3. **Email.** The draft appears next to the details. Edit anything, change the tone or length and click **Rewrite** (the screenshot isn't re-read), tick or untick the resume, then click **Send**. If Gmail isn't connected, Send opens Connect Gmail and your email stays put.

Fill in **Your profile** once (name, contact links, skills, experience or resume text, resume file). The AI may only use facts from your profile and the content you gave it. The signature and contact lines are added from the profile, never generated. After drafting, the app flags links, numbers, years or percentages that don't appear in your profile or the source.

## Architecture

```text
static/index.html, assistant/   app shell + ES modules (vanilla JS, no build step): shell (navigation), input,
                                review, composer, gmail (connect dialog), history, batch, profile, setup
email_assistant.py              Flask blueprint: HTTP layer, validation, rate limits, idempotent send
services/extraction.py          OCR + regex + model -> EmailContext, verification and fallbacks
services/drafting.py            prompt, signature, claim checks, template fallback
services/ai.py                  provider abstraction (Gemini / OpenAI / Ollama over HTTPS)
services/gmail.py               server-side OAuth token store, message builder, send + error mapping
services/profile.py, uploads.py profile + resume storage, the single upload policy
services/history.py, storage.py activity.json (email history), locked atomic JSON writes
```

| Endpoint | Purpose |
|---|---|
| `POST /api/email-assistant/extract` | multipart `screenshot` or JSON `{text}`, returns the normalized `EmailContext` |
| `POST /api/email-assistant/draft` | confirmed details + `style`/`length`/`historyId`, returns `{subject, body, attachResume, warnings}` |
| `POST /api/email-assistant/send` | final email + `Idempotency-Key` header; re-validates everything server-side |
| `GET/PUT /api/profile`, `POST/DELETE /api/profile/resume` | profile and resume |
| `POST /api/gmail/app-password` | verify an App Password with Gmail and remember the connection |
| `GET /api/list-activities`, `PATCH /api/update-activity/<id>` | email history (`draft`, `sent`, `failed`) |

Data files (all git-ignored): `activity.json`, `profile.json`, `uploads/resume/`, `.gmail_tokens.json`, `.flask_secret`, `.env`. Set `APP_DATA_DIR` to store them elsewhere. Screenshots are never stored; only the extracted details are kept.

## Security

- Uploads are checked by extension, declared type, magic bytes, a real image decode, file size (5 MB) and pixel count (decompression-bomb guard). Resumes must be real PDF/DOCX files; stored names are generated server-side.
- Screenshot or pasted content is fenced in randomly named `untrusted_*` tags and the prompts forbid following instructions inside it. A model-proposed recipient is only accepted if the address literally appears in the pasted or OCR text. Text that looks like instructions to an AI triggers a visible warning.
- Every mutating `/api/*` call requires an `X-Requested-With` header (CSRF guard), and the session cookie is `HttpOnly` + `SameSite=Lax`.
- Send validates a single recipient, a subject with no line breaks (no header injection), body length and the resume file on the server. Per-email idempotency means a double click or retry never sends twice.
- Rate limits: 20 AI requests per minute, 20 sends per hour, and 5 Gmail connection attempts per 10 minutes per client.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests                       # 96 backend tests (extraction, AI, drafting, send, Gmail connect, profile, batch sender)

# Browser tests (Playwright):
npm install --no-save playwright && npx playwright install chromium
python tests/e2e_server.py 5055              # real app with a fake AI model and fake Gmail
node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/assistant.ui.mjs   # 23 UI tests, API mocked
node tests/frontend/run.mjs http://127.0.0.1:5055 tests/frontend/e2e.flow.mjs       # full flow through the backend
```

Restart `e2e_server.py` before each E2E run, because it keeps state for the life of the process.

## Known limitations

- Single-user local app: there is no login, and anyone who can reach the server can use it. Don't expose it publicly as-is.
- Rate limits and in-flight send tracking are in memory (one process). History keeps the latest 50 entries.
- Without Tesseract, addresses in screenshots are read only by the vision model. They're flagged for a spelling check, but can't be independently verified.
- DOCX resumes can be attached, but only PDF text is extracted into the profile automatically.
- The Streamlit entrypoint (`streamlit_app.py`) is the batch sender only.
