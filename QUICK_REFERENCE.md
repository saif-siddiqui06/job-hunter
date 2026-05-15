# 🎯 Quick Modification Checklist

## File-by-File Prompts for Customization

### ✅ app.py — Backend Logic

**Prompt 1: Add Email Delay (avoid spam)**
- Where: Line 86-87 (in email sending loop)
- Add: `time.sleep(2)` after each email send
- Why: Gmail flags rapid-fire emails as spam

**Prompt 2: Add Logging**
- Where: Line 87 (after successful send)
- Add: Append to `email_log.csv` with timestamp
- Why: Track which emails were sent when

**Prompt 3: Make Resume Mandatory**
- Where: Line 62 (resume validation)
- Change: Allow None to require file
- Why: Ensure resume always attached

**Prompt 4: Change Port Number**
- Where: Line 110 (at bottom)
- Change: `port=5000` to `port=8080`
- Why: If 5000 already in use

**Prompt 5: Add Custom SMTP**
- Where: Line 77 (Gmail server)
- Change: `smtp.gmail.com` to your SMTP server
- Why: Use Outlook, Yahoo, or custom domain

---

### ✅ index.html — Web Interface

**Prompt 1: Customize Title**
- Where: Line 4 `<title>` tag
- Change: "ReachOut" to "YourName Mailer"
- Why: Personalize for your brand

**Prompt 2: Change Colors**
- Where: Lines 10-17 (`:root` CSS variables)
- Change: `--accent: #7fff6e` to any hex color
- Why: Match your brand colors

**Prompt 3: Add Email Templates**
- Where: After `<textarea>` (around line 150)
- Add: Dropdown with pre-written templates
- Why: Save time with common messages

**Prompt 4: Add CC Field**
- Where: Main form section
- Add: `<input name="cc_email">`
- Why: Users send themselves copy

**Prompt 5: Add Progress Indicator**
- Where: After form submission
- Add: Progress bar showing sent/total
- Why: User feedback during sending

**Prompt 6: Add Help Tooltip**
- Where: Near each input field
- Add: `<span class="help">?</span>`
- Why: Guide users through fields

---

### ✅ requirements.txt — Dependencies

**Prompt 1: Add Security (Store password safely)**
```
python-dotenv==1.0.0
```

**Prompt 2: Add Excel Support**
```
openpyxl==3.1.0
pandas==2.0.0
```

**Prompt 3: Add Email Scheduling**
```
schedule==1.2.0
APScheduler==3.10.0
```

**Prompt 4: Add Database (Track sent emails)**
```
sqlalchemy==2.0.0
```

---

### ✅ sample_recruiters.csv — Data Format

**Prompt 1: Minimal Format (CURRENT)**
```csv
email
recruiter@company.com
hiring@startup.io
```

**Prompt 2: With Names**
```csv
email,name
recruiter@company.com,John Doe
hiring@startup.io,Sarah Smith
```

**Prompt 3: With Company**
```csv
email,name,company
recruiter@company.com,John,TechCorp
hiring@startup.io,Sarah,StartupXYZ
```

**Prompt 4: With Personalization Tags**
```csv
email,name,company,position
recruiter@apple.com,John,Apple,Senior Recruiter
hiring@google.com,Sarah,Google,Tech Lead
```

---

## 🚀 Quick Start (3 Steps)

### Step 1: Install
```powershell
pip install -r requirements.txt
```

### Step 2: Run
```powershell
python app.py
```

### Step 3: Visit
```
http://localhost:5000
```

---

## 📋 Pre-Running Checklist

- [ ] Python 3.8+ installed
- [ ] requirements.txt has flask
- [ ] sample_recruiters.csv has emails
- [ ] Gmail account created
- [ ] 2-Step Verification enabled on Gmail
- [ ] App Password generated (16 characters)
- [ ] index.html in static/ folder
- [ ] app.py in root folder

---

## 🔧 Common Modifications Done in 5 Minutes

### Add Delay Between Emails
```python
# In app.py, line 87, add:
import time
time.sleep(2)  # Wait 2 seconds between emails
```

### Change App Title
```html
<!-- In index.html, line 4, change: -->
<title>My Recruiter Mailer</title>
```

### Change Color Scheme
```css
/* In index.html, lines 10-17, change: */
--accent: #FF6B6B;      /* Red */
--accent2: #4ECDC4;     /* Teal */
```

### Add CC Field to HTML
```html
<!-- After sender_email input, add: -->
<input type="email" name="cc_email" placeholder="CC yourself (optional)">
```

### Make Resume Required
```python
# In app.py, line 62, change:
if not resume_file:
    return jsonify({"success": False, "error": "Resume required!"})
```

---

## ❌ Common Mistakes to Avoid

| Mistake | Fix |
|---------|-----|
| Using regular Gmail password | Use 16-char App Password |
| CSV column named "Email_Address" | Must be "email" (lowercase) |
| Resume in .doc format | Use .pdf or .docx |
| Port 5000 already in use | Change to port 8080 |
| Sending 1000 emails at once | Split into 500/day, add delay |
| Forgetting 2-Step Verification | Enable it before creating App Password |
| Static folder missing | Create static/ folder, put index.html inside |

---

## 📞 Troubleshooting

**Problem: "ModuleNotFoundError: flask"**
```powershell
pip install -r requirements.txt
```

**Problem: "Cannot assign requested address"**
```python
# In app.py, change:
app.run(debug=True, host='127.0.0.1', port=5000)
```

**Problem: Emails going to spam**
- Add delay: `time.sleep(3)`
- Personalize subject line
- Add unsubscribe link

**Problem: "Gmail authentication failed"**
- Verify App Password (not regular password)
- Copy exact 16 characters
- Check 2-Step Verification is on

---

## 📊 Performance Settings

For different email list sizes:

### 10-50 emails
- No delay needed
- Single run: 1 minute

### 50-200 emails
- Add 1-2 second delay
- Run time: ~3-5 minutes

### 200-500 emails
- Add 2-3 second delay
- Split into multiple runs
- Total time: ~1-2 hours

### 500+ emails
- Use Google Workspace account
- Add 3-5 second delay
- Spread across 2-3 days

---

## 🎨 Design Customization Quick Links

**Change Theme:**
Edit these colors in index.html (lines 10-17):
- `--bg: #0d0d0f` — Background
- `--accent: #7fff6e` — Main color
- `--accent2: #5ce4f5` — Secondary color
- `--danger: #ff5c5c` — Error color

**Change Fonts:**
Edit Google Fonts link (line 7):
```html
family=Syne:wght@400;700;800&family=DM+Mono
```

**Change Layout:**
Edit `.container` max-width (line 48):
```css
max-width: 720px;  /* Change to 900px for wider */
```

---

## 💡 Advanced Modifications

### Add Database Logging
```python
import sqlite3
db = sqlite3.connect('emails.db')
# Save sent emails to database for history
```

### Add Email Templates
```javascript
templates = {
  'startup': 'Hi [Name], excited about [Company]...',
  'corporate': 'Dear [Name], my experience in...'
}
```

### Add Scheduled Sending
```python
import schedule
schedule.every(5).minutes.do(send_batch)
```

### Add SMS Notification
```python
from twilio.rest import Client
# Alert when all emails sent
```

---

**Ready to customize?** Pick one prompt from above and modify that section of the code!
