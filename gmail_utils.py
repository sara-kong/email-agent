from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os
import pickle

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
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.pkl", "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


def fetch_emails(service, max_results=50, max_pages=10, start_page_token=None):

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
