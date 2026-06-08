import base64
from email.mime.text import MIMEText

def create_draft(service, to, subject, message_text):

    message = MIMEText(message_text)

    message["to"] = to
    message["subject"] = f"Re: {subject}"

    raw_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    body = {
        "message": {
            "raw": raw_message
        }
    }

    draft = service.users().drafts().create(
        userId="me",
        body=body
    ).execute()

    print("✔ Draft created")
