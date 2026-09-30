# Hosting Apply Rocket on Render

The repo includes a Render Blueprint (`render.yaml`) that runs the Flask app with gunicorn, on a persistent disk, behind HTTPS.

## Deploy (about 10 minutes)

1. Sign in at https://render.com with the GitHub account that owns this repo.
2. Click **New +** → **Blueprint**, pick this repository, and choose the `render-deploy` branch if asked.
3. Render asks for two values:
   - `GEMINI_API_KEY`: your Gemini key (free at https://aistudio.google.com).
   - `SIGNUP_CODE`: any invite code you choose, e.g. `rocket-7412`. Only people who know it can create an account.
4. Click **Apply**. The first build takes a few minutes. When it's live, you get a URL like `https://apply-rocket.onrender.com`.

## Use it

1. Open the URL → **Create account** → username, password and the invite code.
2. Send your friend the URL and the invite code. They create their own account.
3. Each person clicks **Connect Gmail** and connects with their own Gmail App Password.

Each account has its own profile, resume, Gmail connection and history. Nobody can see anyone else's.

## What it costs

`render.yaml` uses the **Starter** plan with a 1 GB disk (about $7/month plus $0.25/GB for the disk). The disk keeps accounts and history across restarts and deploys, and paid instances can send Gmail over SMTP.

To try it for free, change `plan: starter` to `plan: free` and delete the `disk:` block. Everything then resets whenever Render restarts the app (at least on every deploy and after idle periods), and Render's free tier may block Gmail SMTP.

## Updating

Push to the `render-deploy` branch and Render redeploys automatically. Data on the disk is kept.

## Notes

- Run a single instance (the blueprint sets `--workers 1`). Accounts, history and rate limits are kept in files and memory on that instance.
- Your first account automatically takes over any data from earlier single-user use on that machine. On a fresh Render disk there is none.
- Google sign-in is optional. To use it, add `https://<your-app>.onrender.com/auth/google/callback` as a redirect URI in Google Cloud and set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in the Render dashboard.
