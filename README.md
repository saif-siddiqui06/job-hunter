# 📧 Email Recruiter

Send your resume to 100s of recruiters instantly. Simple, fast, and easy to use.

## 🚀 Quick Start

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Optional: Enable Sign in with Google
Create OAuth credentials in Google Cloud Console and add this redirect URL:

```
http://127.0.0.1:5000/auth/google/callback
```

Then set these environment variables before running the app:

```bash
set GOOGLE_CLIENT_ID=your-client-id
set GOOGLE_CLIENT_SECRET=your-client-secret
set FLASK_SECRET_KEY=change-this-dev-secret
```

If you skip this, the app still works with the guided Gmail App Password option.

### 3. Run
```bash
python app.py
```

### 4. Open
```
http://localhost:5000
```

---

## 📝 What You Need

1. **Gmail Account** - Your email and a 16-character Gmail App Password
2. **CSV File** - List of recruiter emails (format: email,name)
3. **Resume** - PDF or Word file (optional)
4. **Subject & Message** - Your email text

---

## 💡 How to Get Gmail App Password

1. Go to **myaccount.google.com**
2. Click **Security** (left sidebar)
3. Enable **2-Step Verification** (if not already)
4. Find **App Passwords** → Select "Mail" and "Windows"
5. Copy the **16-character password**

---

## 📋 CSV Format

Create a CSV file with email addresses:

```csv
email,name
john@company.com,John Doe
sarah@startup.io,Sarah Smith
```

That's it! Just email and name columns.

---

## 🔐 Gmail App Password Setup

You CANNOT use your regular Gmail password. You need an **App Password**:

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Security → 2-Step Verification (must be ON)
3. Security → App Passwords
4. Generate one for "Mail" → copy the 16-character code
5. Paste it into the app's "App Password" field

---

## ⚙️ How It Works

1. User uploads CSV with recruiter emails
2. User uploads resume (PDF/DOC)
3. User enters email subject + body
4. Flask backend connects to Gmail via SSL (port 465)
5. Sends one email per recruiter — all with resume attached
6. Returns success/failure count per email

---

## ⚠️ Tips

- **Daily limit**: Gmail allows ~500 emails/day for free accounts
- **Avoid spam**: Write a genuine, personalized email body
- **Test first**: Try with 2-3 emails before sending to 1000
- **Rate limiting**: For 1000+ emails, consider adding a `time.sleep(1)` between sends
