# 📧 Email Recruiter - Quick Start Guide

## ⚡ 30 Second Setup

1. **Install**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run**
   ```bash
   python app.py
   ```

3. **Open**
   ```
   http://localhost:5000
   ```

---

## 📝 What to do next (in the app)

### Step 1: Enter Your Gmail
- Email: `your-email@gmail.com`
- Password: Your 16-char **App Password** (see below)

### Step 2: Write Your Email
- **Subject**: What's your email about?
- **Message**: Your email text

### Step 3: Upload CSV
- Simple file with recruiter emails
- Format: email,name (see example below)

### Step 4: Upload Resume (Optional)
- PDF or Word file
- Will be attached to every email

### Step 5: Click "Send Emails"
- Done! ✓

---

## 🔑 Gmail App Password (Super Easy)

1. Go to **myaccount.google.com**
2. Click **Security** on left
3. Turn on **2-Step Verification** (if off)
4. Find **App Passwords** (search for it)
5. Select **Mail** + **Windows**
6. Copy the **16 characters** it shows
7. Paste into the app

**That's it!** No complex steps. Just 2-Step Verification + App Password.

## Sign in with Google Option

The app also has a **Sign in with Google** tab. To make that button work, create Gmail API OAuth credentials in Google Cloud Console and use this redirect URL:

```text
http://127.0.0.1:5000/auth/google/callback
```

Then set:

```bash
set GOOGLE_CLIENT_ID=your-client-id
set GOOGLE_CLIENT_SECRET=your-client-secret
set FLASK_SECRET_KEY=change-this-dev-secret
```

After that, restart Flask and click **Sign in with Google** in the app.

---

## 📋 CSV File Example

Create a file named `recruiters.csv`:

```
email,name
john@company.com,John
sarah@startup.io,Sarah
alex@google.com,Alex
```

**That's all you need!** Just email and name.

---

## ✨ Features

✓ **Clean UI** - Beautiful, modern design  
✓ **Simple** - No complex steps  
✓ **Fast** - Send to 100s of recruiters in minutes  
✓ **Optional Resume** - Attach your resume or skip it  
✓ **Error Handling** - Clear messages if something goes wrong  

---

## ❌ Common Issues

### "Gmail authentication failed"
- Make sure you're using **App Password**, not regular password
- 16 characters with spaces

### "No valid emails in CSV"
- Check your CSV has "email" column
- Make sure emails have @ symbol

### "Connection error"
- Make sure Flask is running (`python app.py`)
- Check you're visiting `http://localhost:5000`

---

## 🎯 Done!

Send to 10 emails? 100 emails? 1000 emails? It works for all!

**Just go to http://localhost:5000 and start sending!** 🚀
