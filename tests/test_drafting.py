import io

from conftest import APP_HEADERS, make_pdf
from services import ai, history
from services.drafting import DraftInput, generate_draft, strip_signoff, unsupported_claims

DRAFT = "/api/email-assistant/draft"
PROFILE = {
    "fullName": "Saif Siddiqui",
    "phone": "+91 98765 43210",
    "linkedinUrl": "https://linkedin.com/in/saif",
    "headline": "Data analyst with 3 years of SQL and Power BI",
    "skills": ["SQL", "Python", "Power BI"],
    "experience": "Data Analyst at Acme (2022-2025). Built Power BI dashboards.",
}


def context(**overrides):
    base = {
        "recipientEmail": "careers@example.com",
        "recipientName": "Sarah Khan",
        "companyName": "ABC Technologies",
        "jobTitle": "Data Analyst",
        "emailType": "job_application",
        "context": "The recruiter asked the user to send their resume for the Data Analyst position.",
        "importantDetails": ["Deadline: 15 October"],
        "resumeRequested": True,
        "sourceType": "screenshot",
    }
    base.update(overrides)
    return base


def save_profile(client, **fields):
    response = client.put("/api/profile", json={**PROFILE, **fields}, headers=APP_HEADERS)
    assert response.status_code == 200, response.get_json()


def upload_resume(client):
    data = {"resume": (io.BytesIO(make_pdf()), "Saif_Siddiqui_Resume.pdf", "application/pdf")}
    response = client.post("/api/profile/resume", data=data, headers=APP_HEADERS, content_type="multipart/form-data")
    assert response.status_code == 200, response.get_json()


def test_valid_context_generates_structured_draft(client, fake_ai):
    save_profile(client)
    upload_resume(client)
    fake_ai.queue({
        "subject": "Application for Data Analyst - Saif Siddiqui",
        "body": "Hello Sarah,\n\nI'd like to apply for the Data Analyst position at ABC Technologies. I have 3 years of SQL and Power BI experience.\n\nI've attached my resume.\n\nBest regards,\nSaif",
        "attach_resume": True,
    })
    response = client.post(DRAFT, json=context(), headers=APP_HEADERS)
    assert response.status_code == 200
    data = response.get_json()
    draft = data["draft"]
    assert draft["mode"] == "ai"
    assert draft["subject"] == "Application for Data Analyst - Saif Siddiqui"
    assert draft["attachResume"] is True
    # The model's own sign-off is replaced by the profile-based signature.
    assert draft["body"].endswith("Best regards,\nSaif Siddiqui\n+91 98765 43210\nlinkedin.com/in/saif")
    assert draft["body"].count("Best regards") == 1
    assert draft["warnings"] == []

    prompt = fake_ai.requests[0].prompt
    assert "Saif Siddiqui" in prompt and "Power BI" in prompt  # profile is used
    assert "<untrusted_" in prompt  # extracted context is fenced as untrusted
    assert "Style: Professional" in prompt and "60-110 words" in prompt

    record = history.get_activity(data["historyId"])
    assert record["status"] == "draft"
    assert (record["recipient"], record["company"], record["role"], record["source_type"]) == (
        "careers@example.com", "ABC Technologies", "Data Analyst", "screenshot",
    )


def test_regenerate_updates_the_same_history_record(client, fake_ai):
    save_profile(client)
    fake_ai.queue(
        {"subject": "First", "body": "Hello Sarah,\n\nFirst version.", "attach_resume": False},
        {"subject": "Second", "body": "Hello Sarah,\n\nSecond version.", "attach_resume": False},
    )
    first = client.post(DRAFT, json=context(), headers=APP_HEADERS).get_json()
    second = client.post(DRAFT, json={**context(), "historyId": first["historyId"], "style": "concise", "length": "medium"}, headers=APP_HEADERS).get_json()
    assert second["historyId"] == first["historyId"]
    assert len(history.list_activities()) == 1
    assert history.get_activity(first["historyId"])["subject"] == "Second"
    assert "Concise" in fake_ai.requests[1].prompt and "110-170 words" in fake_ai.requests[1].prompt


def test_requested_subject_is_used_exactly(client, fake_ai):
    save_profile(client)
    fake_ai.queue({"subject": "Something else", "body": "Hello,\n\nBody.", "attach_resume": True})
    draft = client.post(DRAFT, json=context(requestedSubject="DA-2291 Application"), headers=APP_HEADERS).get_json()["draft"]
    assert draft["subject"] == "DA-2291 Application"


def test_hallucinated_claims_are_flagged(client, fake_ai):
    save_profile(client)
    fake_ai.queue({
        "subject": "Application",
        "body": "Hello Sarah,\n\nWith 7 years of experience I improved revenue by 40%. See https://my-fake-portfolio.dev and call +1 555 010 9999.",
        "attach_resume": False,
    })
    draft = client.post(DRAFT, json=context(), headers=APP_HEADERS).get_json()["draft"]
    assert len(draft["warnings"]) == 1
    warning = draft["warnings"][0]
    for claim in ("7 years", "40%", "my-fake-portfolio.dev", "+1 555 010 9999"):
        assert claim in warning


def test_unsupported_claims_accepts_facts_from_profile():
    trusted = "Data analyst with 3 years of SQL. linkedin.com/in/saif +91 98765 43210"
    body = "I have 3 years of SQL. Profile: https://linkedin.com/in/saif, phone +91 98765 43210."
    assert unsupported_claims(body, trusted) == []


def test_strip_signoff_keeps_content():
    assert strip_signoff("Hello,\n\nThank you for your time.\n\nBest regards,\nSaif") == "Hello,\n\nThank you for your time."
    assert strip_signoff("Hello,\n\nNo sign-off here.") == "Hello,\n\nNo sign-off here."


def test_provider_failure_falls_back_to_template(client, fake_ai):
    save_profile(client)
    fake_ai.queue(ai.AIUnavailable("AI generation is temporarily unavailable."))
    draft = client.post(DRAFT, json=context(), headers=APP_HEADERS).get_json()["draft"]
    assert draft["mode"] == "template"
    assert "temporarily unavailable" in draft["warnings"][0]
    assert draft["body"].startswith("Hello Sarah,\n\nI'd like to apply for the Data Analyst position at ABC Technologies.")
    assert draft["subject"] == "Application for Data Analyst - Saif Siddiqui"


def test_missing_job_title_is_not_invented():
    data = DraftInput(companyName="ABC Technologies", emailType="job_application", context="Apply for a job.")
    draft = generate_draft(data, PROFILE, attach_available=False)
    assert "the open position at ABC Technologies" in draft.body
    assert "[" not in draft.body


def test_missing_company_is_not_invented():
    data = DraftInput(jobTitle="Data Analyst", emailType="job_application", context="Apply.")
    draft = generate_draft(data, PROFILE, attach_available=False)
    assert "Data Analyst position." in draft.body
    assert " at " not in draft.body.split("\n\n")[1]


def test_missing_recipient_still_drafts(client):
    save_profile(client)
    response = client.post(DRAFT, json=context(recipientEmail="", recipientName=""), headers=APP_HEADERS)
    assert response.status_code == 200
    assert response.get_json()["draft"]["body"].startswith("Hello Hiring Team,")


def test_missing_name_is_reported_not_invented():
    draft = generate_draft(DraftInput(jobTitle="Data Analyst", context="Apply."), {}, attach_available=False)
    assert draft.body.endswith("Best regards,")
    assert any("Your name isn't set" in warning for warning in draft.warnings)


def test_sender_name_override_is_used():
    draft = generate_draft(DraftInput(jobTitle="Data Analyst", context="Apply.", senderName="S. Siddiqui"), {}, attach_available=False)
    assert draft.body.endswith("Best regards,\nS. Siddiqui")


def test_thank_you_note_does_not_attach_resume():
    draft = generate_draft(DraftInput(emailType="thank_you", jobTitle="Data Analyst", context="Thank the recruiter."), PROFILE, attach_available=True)
    assert draft.attachResume is False


def test_draft_validation(client):
    response = client.post(DRAFT, json={"recipientEmail": "not-an-email", "context": "x"}, headers=APP_HEADERS)
    assert response.status_code == 400
    response = client.post(DRAFT, json={"recipientEmail": "a@b.com"}, headers=APP_HEADERS)
    assert response.status_code == 400
    assert "what this email is about" in response.get_json()["error"]
