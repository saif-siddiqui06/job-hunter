import csv
import io
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


EMAIL_COLUMNS = ("email", "Email", "EMAIL", "e-mail", "E-mail")


def extract_recipients(uploaded_file):
    csv_content = uploaded_file.getvalue().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(csv_content))

    if not reader.fieldnames:
        return []

    recipients = []
    for row in reader:
        if not row:
            continue

        email_value = next((row.get(column) for column in EMAIL_COLUMNS if row.get(column)), None)
        if not email_value:
            email_value = next(iter(row.values()), "")

        email_value = email_value.strip()
        if "@" in email_value:
            recipients.append(email_value)

    return recipients


def normalize_app_password(password):
    return "".join(password.split())


def build_message(sender, recipient, subject, message, resume_data=None, resume_name="resume.pdf"):
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(message, "plain"))

    if resume_data:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(resume_data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=resume_name)
        msg.attach(part)

    return msg


def send_emails(sender, password, recipients, subject, message, resume_file):
    resume_data = resume_file.getvalue() if resume_file else None
    resume_name = resume_file.name if resume_file else "resume.pdf"
    sent = 0
    failed = 0

    progress_bar = st.progress(0)
    status = st.empty()
    result_box = st.empty()

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender, normalize_app_password(password))

        for index, recipient in enumerate(recipients, start=1):
            try:
                msg = build_message(sender, recipient, subject, message, resume_data, resume_name)
                server.sendmail(sender, recipient, msg.as_string())
                sent += 1
                status.info(f"Sent to {recipient}")
            except Exception as exc:
                failed += 1
                status.warning(f"Failed for {recipient}: {exc}")

            progress_bar.progress(index / len(recipients))

    if failed:
        result_box.warning(f"Done. Sent {sent} of {len(recipients)} emails. Failed: {failed}.")
    else:
        result_box.success(f"Done. Sent all {sent} emails.")


st.set_page_config(page_title="Apply Rocket", page_icon="AR", layout="wide")

st.title("Apply Rocket")
st.caption("Send a focused recruiter outreach batch from your Gmail account.")

with st.sidebar:
    st.header("Gmail setup")
    st.markdown(
        "Use a Gmail App Password, not your normal Gmail password. "
        "Turn on 2-Step Verification in your Google Account, then create an App Password for Mail."
    )
    st.link_button("Open Google Security", "https://myaccount.google.com/security")
    st.link_button("Open App Passwords", "https://myaccount.google.com/apppasswords")

with st.form("email_form"):
    col_a, col_b = st.columns(2)
    with col_a:
        sender = st.text_input("Your Gmail", placeholder="you@gmail.com")
    with col_b:
        password = st.text_input("Gmail App Password", type="password", placeholder="xxxx xxxx xxxx xxxx")

    subject = st.text_input("Subject", placeholder="Software Engineer - Open to Opportunities")
    message = st.text_area(
        "Message",
        height=180,
        placeholder=(
            "Hi,\n\n"
            "I am a developer interested in opportunities with your team. "
            "I have attached my resume and would love to connect.\n\n"
            "Best,\nYour Name"
        ),
    )

    csv_file = st.file_uploader("Recruiter CSV", type=["csv"])
    resume_file = st.file_uploader("Resume", type=["pdf", "doc", "docx"])
    submitted = st.form_submit_button("Send Emails", type="primary")

if submitted:
    if not all([sender, password, subject, message, csv_file]):
        st.error("Please complete all required fields and upload a recruiter CSV.")
        st.stop()

    try:
        recipients = extract_recipients(csv_file)
    except UnicodeDecodeError:
        st.error("Could not read CSV. Please upload a UTF-8 CSV file.")
        st.stop()

    if not recipients:
        st.error("No valid emails found in the CSV.")
        st.stop()

    try:
        send_emails(sender.strip(), password, recipients, subject.strip(), message.strip(), resume_file)
    except smtplib.SMTPAuthenticationError:
        st.error(
            "Gmail authentication failed. Use a 16-character Gmail App Password, "
            "not your normal Gmail password. Spaces are removed automatically."
        )
    except Exception as exc:
        st.error(f"Could not send emails: {exc}")
