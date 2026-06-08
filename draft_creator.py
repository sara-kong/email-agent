def create_draft(service, sender, subject, body):

    message = {
        "message": {
            "threadId": None,
            "raw": None
        }
    }

    import base64

    email_text = f"""To: {sender}
Subject: Re: {subject}

{body}
"""

    raw_message = base64.urlsafe_b64encode(email_text.encode("utf-8")).decode("utf-8")

    message["message"]["raw"] = raw_message

    service.users().drafts().create(
        userId="me",
        body=message
    ).execute()

    print("✔ Draft created in Gmail")
