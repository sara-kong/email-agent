from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os
import pickle
import base64
import re

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

def get_gmail_service():
    creds = None
    if os.path.exists("token.pkl"):
        with open("token.pkl", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.pkl", "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


def extract_body(payload: dict) -> str:
    """Recursively extract plain text body from a Gmail message payload."""
    body = ""

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    elif mime_type == "text/html" and not body:
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            body = re.sub(r'<[^>]+>', ' ', html)
            body = re.sub(r'\s+', ' ', body).strip()

    elif "parts" in payload:
        for part in payload["parts"]:
            result = extract_body(part)
            if result:
                body = result
                break

    return body.strip()


def clean_body(text: str, max_chars: int = 3000) -> str:
    """Clean up extracted email body — remove excessive whitespace and truncate."""
    if not text:
        return ""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()
    return text[:max_chars]


def fetch_emails(service, max_results=50, max_pages=10, start_page_token=None):
    """Returns list of message ID dicts and next page token."""
    all_messages = []
    response = service.users().messages().list(
        userId="me",
        maxResults=max_results,
        pageToken=start_page_token
    ).execute()

    messages = response.get("messages", [])
    all_messages.extend(messages)
    next_page_token = response.get("nextPageToken")

    page_count = 0
    while next_page_token and page_count < max_pages:
        page_count += 1
        response = service.users().messages().list(
            userId="me",
            pageToken=next_page_token,
            maxResults=max_results
        ).execute()
        messages = response.get("messages", [])
        all_messages.extend(messages)
        next_page_token = response.get("nextPageToken")

    return all_messages, next_page_token


def fetch_full_email(service, gmail_id: str) -> dict:
    """
    Fetch a single email with full body extracted.
    Returns a clean dict with all the fields we need.
    """
    msg = service.users().messages().get(
        userId="me",
        id=gmail_id,
        format="full"
    ).execute()

    payload = msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

    sender = headers.get("From", "")
    subject = headers.get("Subject", "")
    date = headers.get("Date", "")
    to = headers.get("To", "")
    thread_id = msg.get("threadId", "")
    snippet = msg.get("snippet", "")

    raw_body = extract_body(payload)
    full_body = clean_body(raw_body) if raw_body else snippet

    email_text = f"From: {sender}\nTo: {to}\nDate: {date}\nSubject: {subject}\n\n{full_body}"

    return {
        "gmail_id": gmail_id,
        "thread_id": thread_id,
        "sender": sender,
        "to": to,
        "subject": subject,
        "date": date,
        "snippet": snippet,
        "full_body": full_body,
        "email_text": email_text,
    }


def fetch_thread(service, thread_id: str) -> list[dict]:
    """
    Fetch all messages in a thread, returned as a list of clean dicts.
    Useful for reply drafting with full conversation context.
    """
    thread = service.users().threads().get(
        userId="me",
        id=thread_id,
        format="full"
    ).execute()

    messages = []
    for msg in thread.get("messages", []):
        payload = msg.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        raw_body = extract_body(payload)
        full_body = clean_body(raw_body) if raw_body else msg.get("snippet", "")
        messages.append({
            "gmail_id": msg["id"],
            "thread_id": thread_id,
            "sender": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "full_body": full_body,
        })

    return messages


if __name__ == "__main__":
    service = get_gmail_service()
    print("Gmail connected:", service.users().getProfile(userId="me").execute()["emailAddress"])
