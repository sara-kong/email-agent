import os
import pickle
from dotenv import load_dotenv
from openai import OpenAI
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# ----------------------------
# ENV + OPENAI
# ----------------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ----------------------------
# GMAIL AUTH
# ----------------------------
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]
def gmail_auth():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)

# ----------------------------
# AI REPLY GENERATOR
# ----------------------------
def generate_email_reply(email_text):
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You write concise, natural email replies."
            },
            {
                "role": "user",
                "content": f"Write a reply to this email:\n\n{email_text}"
            }
        ]
    )

    return response.choices[0].message.content

# ----------------------------
# CREATE GMAIL DRAFT
# ----------------------------
def create_draft(service, to_email, subject, body):
    message = {
        "message": {
            "raw": base64_encode_email(to_email, subject, body)
        }
    }

    service.users().drafts().create(
        userId="me",
        body=message
    ).execute()

# Gmail requires base64 encoded raw email format
import base64
def base64_encode_email(to, subject, body):
    email_text = f"""To: {to}
Subject: Re: {subject}
Content-Type: text/plain; charset="UTF-8"

{body}
"""

    encoded = base64.urlsafe_b64encode(email_text.encode("utf-8")).decode("utf-8")
    return encoded

# ----------------------------
# PROCESS EMAILS → AI → DRAFTS
# ----------------------------
def process_emails(service):
    results = service.users().messages().list(
        userId="me",
        maxResults=5
    ).execute()

    messages = results.get("messages", [])

    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="full"
        ).execute()

        payload = msg_data["payload"]
        headers = payload["headers"]

        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")

        snippet = msg_data.get("snippet", "")

        email_text = f"""
From: {sender}
Subject: {subject}
Message: {snippet}
"""

        reply = generate_email_reply(email_text)

        print("\n================ EMAIL =================")
        print(email_text)

        print("\n================ AI DRAFT =================")
        print(reply)

        # CREATE DRAFT IN GMAIL
        create_draft(service, sender, subject, reply)

        print("\n✔ Draft created in Gmail")

# ----------------------------
# MAIN
# ----------------------------
def main():
    service = gmail_auth()
    process_emails(service)

if __name__ == "__main__":
    main()
