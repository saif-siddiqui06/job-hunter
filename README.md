# Apply Rocket

Apply Rocket helps you send recruiter outreach emails from Gmail with a recruiter CSV and an optional resume attachment.

The repository includes two entrypoints:

- `streamlit_app.py` - use this for Streamlit Community Cloud hosting.
- `app.py` - optional Flask version for local/API-style use.

## Run Locally With Streamlit

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The Streamlit app uses Gmail SMTP with a Gmail App Password. Do not use your normal Gmail password.

## CSV Format

Create a CSV with an email column:

```csv
email,name
john@company.com,John Doe
sarah@startup.io,Sarah Smith
```

The app also accepts common variants like `Email`, `EMAIL`, `e-mail`, and `E-mail`.

## Gmail App Password

1. Open your Google Account Security page.
2. Turn on 2-Step Verification.
3. Open App Passwords.
4. Create an app password for Mail.
5. Paste the 16-character app password into the app.

Spaces are removed automatically.

## Deploy On Streamlit Community Cloud

1. Push this repository to GitHub.
2. Open https://share.streamlit.io/ and sign in with GitHub.
3. Choose the repository.
4. Set the main file path to:

```text
streamlit_app.py
```

5. Deploy the app.

No Streamlit secrets are required for the default Gmail App Password flow because the sender enters the Gmail address and app password in the app UI at send time.

## Optional Flask App

For the Flask version:

```bash
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://localhost:5000
```

The Flask Google OAuth option requires environment variables:

```bash
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
FLASK_SECRET_KEY=change-this-secret
PUBLIC_BASE_URL=https://your-public-domain
GOOGLE_REDIRECT_URI=https://your-public-domain/auth/google/callback
```

## Safety Notes

- Test with one or two emails before sending a larger batch.
- Gmail free accounts have daily sending limits.
- Keep outreach personal and relevant to avoid spam reports.
- Never commit Gmail passwords, app passwords, OAuth secrets, or `.streamlit/secrets.toml`.
