# 📧 ReachOut — Complete Customization & Setup Guide

## 🎯 Project Overview
A powerful bulk email sender that automatically sends personalized emails with resume attachments to recruiters via Gmail.

---

## 📁 File-by-File Customization Guide

### 1️⃣ **app.py** — Flask Backend
**What it does:** Handles CSV parsing, Gmail SMTP connection, and email sending logic.

#### Key Features to Modify:
```python
# Change these settings for different behavior:

# 1. Port number (currently 5000)
if __name__ == "__main__":
    app.run(debug=True, port=5000)  # Change 5000 to any port like 8080

# 2. Resume attachment (currently optional)
# To make resume MANDATORY, change:
if not resume_file:
    return jsonify({"success": False, "error": "Resume is required."})

# 3. Email rate limiting (add delay between sends)
import time
time.sleep(1)  # Add 1-second delay between each email

# 4. Custom email column names
# Currently accepts: email, recruiter email, recruiter_email, mail
# Add more: email_address, recipient_email, contact_email
```

#### Common Modifications:

**A. Add Email Delay (to avoid Gmail spam flagging)**
```python
# In the email sending loop, add:
import time
time.sleep(2)  # 2-second delay between emails
```

**B. Add Logging to Track Sent Emails**
```python
# Track to a file
with open('email_log.txt', 'a') as log:
    log.write(f"{recruiter_email} - Sent at {timestamp}\n")
```

**C. Add CC/BCC Field**
```python
# In the form, users can add themselves as CC
msg["Cc"] = request.form.get("cc_email", "")
```

---

### 2️⃣ **index.html** — Web Interface
**What it does:** Beautiful frontend for uploading CSV, composing emails, and uploading resume.

#### Customization Prompts:

**A. Change App Title & Branding**
```html
<!-- Line 4: Change title -->
<title>YOUR_NAME — Bulk Recruiter Mailer</title>

<!-- Update header -->
<h1>YourName's ReachOut</h1>
<header p>Send your resume to 100s of recruiters in minutes</header p>
```

**B. Add Custom Color Scheme**
```css
:root {
  --accent: #7fff6e;    /* Neon green */
  --accent2: #5ce4f5;   /* Cyan */
  --danger: #ff5c5c;    /* Red */
}
/* Change these hex codes to your brand colors */
```

**C. Add Email Templates (Pre-written Messages)**
```html
<!-- Add before the textarea -->
<select id="template" onchange="loadTemplate()">
  <option value="">-- Select Template --</option>
  <option value="generic">Generic</option>
  <option value="startup">Startup Focus</option>
  <option value="corporate">Corporate</option>
</select>
```

**D. Add Progress Bar**
```html
<!-- After sending starts -->
<div class="progress">
  <div class="progress-bar" style="width: 45%"></div>
</div>
<p>45 of 100 emails sent...</p>
```

---

### 3️⃣ **requirements.txt** — Dependencies
**What it does:** Lists all Python packages needed to run the app.

#### Current Dependencies:
```
flask>=3.0.0
```

#### Why This Might Fail:
- Missing `email` library (built-in, no install needed)
- Missing `csv` library (built-in, no install needed)

#### Optional Additions:
```
flask>=3.0.0
python-dotenv==1.0.0        # For storing Gmail password securely
schedule==1.2.0             # For scheduling emails
openpyxl==3.1.0             # To support Excel (.xlsx) files
```

#### To Use Dotenv for Security:
```python
# In app.py, add:
from dotenv import load_dotenv
import os

load_dotenv()
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
```

Then create `.env` file:
```
GMAIL_PASSWORD=your_16_character_app_password
```

---

### 4️⃣ **sample_recruiters.csv** — Data File
**What it does:** Example file showing the CSV format users should follow.

#### Current Format:
```csv
email,name
recruiter@company.com,John Doe
hiring@startup.io,Sarah
tech@bigcorp.com,Alex
```

#### Variations Users Can Use:

**With Subject Line Customization:**
```csv
email,name,company,position
recruiter@company.com,John Doe,TechCorp,HR Manager
hiring@startup.io,Sarah Smith,StartupXYZ,Recruiter
```

**With Personalization:**
```csv
email,name,company,role
recruiter@apple.com,John,Apple,Senior Recruiter
hiring@google.com,Sarah,Google,Talent Manager
```

**With Salary Info (for filtering):**
```csv
email,name,company,salary_range
recruiter@company.com,John,TechCorp,100k-150k
hiring@startup.io,Sarah,StartupXYZ,80k-120k
```

---

### 5️⃣ **README.md** — Documentation
**What it does:** Setup and usage instructions for users.

#### Information to Update:
- Your name/company
- Specific Gmail setup requirements
- Custom CSV format if modified
- Troubleshooting tips

---

## 🚀 Step-by-Step Running Instructions

### **Step 1: Install Python Dependencies**
```powershell
cd c:\Users\hp\Downloads\files
pip install -r requirements.txt
```
✅ **Expected Output:**
```
Successfully installed flask-3.0.0
```

### **Step 2: Get Gmail App Password**
1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** (left sidebar)
3. Enable **2-Step Verification** (if not already enabled)
4. Search for **App Passwords**
5. Select "Mail" and "Windows Computer"
6. Generate and **copy the 16-character password**
7. **Keep this secure!**

### **Step 3: Start the Flask Server**
```powershell
python app.py
```
✅ **Expected Output:**
```
* Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

### **Step 4: Open in Browser**
- Visit: `http://localhost:5000`
- Or: `http://127.0.0.1:5000`

### **Step 5: Fill the Form**
1. **Sender Email:** your-email@gmail.com
2. **App Password:** Paste the 16-character password
3. **Email Subject:** "Exciting Opportunity - Software Engineer"
4. **Email Body:** Write your message
5. **Upload CSV:** Select your recruiter list
6. **Upload Resume:** Select your PDF/DOC resume
7. Click **Send Emails**

### **Step 6: Monitor Results**
- ✅ Green = Emails sent successfully
- ❌ Red = Failed (check error message)
- Count displays: "Sent: 45 | Failed: 2"

---

## 🛠 Modification Examples

### Example 1: Add Multiple Email Templates

**File: index.html**
```html
<!-- Add after body textarea -->
<div class="template-buttons">
  <button onclick="insertTemplate('generic')">Template: Generic</button>
  <button onclick="insertTemplate('startup')">Template: Startup</button>
  <button onclick="insertTemplate('corporate')">Template: Corporate</button>
</div>

<script>
function insertTemplate(type) {
  const templates = {
    generic: "Hi [Name],\n\nI'm interested in opportunities...",
    startup: "Hey [Name],\n\nI'm excited about [Company]'s mission...",
    corporate: "Dear [Name],\n\nWith my experience in..."
  };
  document.getElementById('body').value = templates[type];
}
</script>
```

### Example 2: Add Email Scheduling

**File: app.py** (add at top)
```python
import schedule
import threading
import time

def schedule_emails(emails_list, delay_minutes=1):
    """Send emails with X minute delay between each"""
    for i, email in enumerate(emails_list):
        schedule.every(i * delay_minutes).minutes.do(send_email, email)
```

### Example 3: Save Sent Emails Log

**File: app.py** (add in send_emails function)
```python
import datetime

# After successful send:
with open('sent_emails.csv', 'a') as f:
    f.write(f"{recruiter_email},{datetime.datetime.now()}\n")
```

---

## ⚠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| **"Authentication failed"** | Use App Password, NOT regular Gmail password |
| **"CSV column not found"** | Ensure column is named "email" (case-insensitive) |
| **Port already in use** | Change port: `app.run(debug=True, port=8080)` |
| **"ModuleNotFoundError: flask"** | Run `pip install -r requirements.txt` |
| **Emails marked as spam** | Add delay between sends: `time.sleep(2)` |
| **"Connection timeout"** | Check internet, Gmail may have blocked login |

---

## 📊 Scaling to Large Lists

**Gmail Limits:**
- Free accounts: ~500 emails/day
- Google Workspace: ~1500 emails/day

**For 1000+ Emails:**
1. Split CSV into 2-3 smaller lists
2. Send on different days
3. Add delay: `time.sleep(3)` between emails
4. Consider Google Workspace or alternative SMTP service

---

## 🔐 Security Best Practices

✅ **DO:**
- Use App Password (not regular password)
- Store `.env` file with sensitive data
- Don't commit `.env` to Git
- Use HTTPS in production

❌ **DON'T:**
- Hardcode Gmail password in app.py
- Share app password in emails/messages
- Send identical emails (adds spam signals)
- Send to invalid emails

---

## 📝 Example Complete Modified app.py Section

```python
import os
import csv
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

# Configuration
EMAIL_DELAY = 2  # 2-second delay between emails
LOG_FILE = "email_log.csv"

@app.route("/send-emails", methods=["POST"])
def send_emails():
    try:
        sender_email = request.form.get("sender_email", "").strip()
        app_password = request.form.get("app_password", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()

        if not all([sender_email, app_password, subject, body]):
            return jsonify({"success": False, "error": "All fields are required."}), 400

        csv_file = request.files.get("csv_file")
        if not csv_file:
            return jsonify({"success": False, "error": "CSV file is required."}), 400

        csv_content = csv_file.read().decode("utf-8")
        reader = csv.DictReader(csv_content.splitlines())

        recruiter_emails = []
        for row in reader:
            normalized = {k.strip().lower(): v.strip() for k, v in row.items()}
            email_val = normalized.get("email") or normalized.get("recruiter email")
            if email_val and "@" in email_val:
                recruiter_emails.append(email_val)

        if not recruiter_emails:
            return jsonify({"success": False, "error": "No valid emails in CSV."}), 400

        resume_file = request.files.get("resume")
        resume_data = None
        resume_filename = "resume.pdf"
        if resume_file:
            resume_data = resume_file.read()
            resume_filename = resume_file.filename

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, app_password)

        sent = []
        failed = []

        for i, recruiter_email in enumerate(recruiter_emails):
            try:
                msg = MIMEMultipart()
                msg["From"] = sender_email
                msg["To"] = recruiter_email
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                if resume_data:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(resume_data)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{resume_filename}"')
                    msg.attach(part)

                server.sendmail(sender_email, recruiter_email, msg.as_string())
                sent.append(recruiter_email)

                # Log the sent email
                with open(LOG_FILE, 'a') as log:
                    log.write(f"{recruiter_email},{datetime.now()}\n")

                # Delay to avoid spam flagging
                if i < len(recruiter_emails) - 1:
                    time.sleep(EMAIL_DELAY)

            except Exception as e:
                failed.append({"email": recruiter_email, "error": str(e)})

        server.quit()

        return jsonify({
            "success": True,
            "sent_count": len(sent),
            "failed_count": len(failed),
            "sent": sent,
            "failed": failed
        })

    except smtplib.SMTPAuthenticationError:
        return jsonify({"success": False, "error": "Gmail auth failed. Use App Password."}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

---

## ✨ Next Steps

1. **Customize sample_recruiters.csv** with your actual recruiter list
2. **Get your Gmail App Password**
3. **Run `python app.py`**
4. **Visit http://localhost:5000**
5. **Send your first batch!**

Questions? Check the Troubleshooting section above.
