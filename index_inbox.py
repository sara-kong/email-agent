import json

from gmail_utils import (
    get_gmail_service,
    fetch_emails
)

from embeddings import create_embedding

from memory import (
    save_email,
    email_exists
)

from state_manager import (
    load_state,
    save_state
)

def index_inbox():

    service = get_gmail_service()

    state = load_state()

    start_page_token = state.get(
        "next_page_token"
    )

    emails, next_page_token = fetch_emails(
        service,
        max_results=50,
        max_pages=10,
        start_page_token=start_page_token
    )

    print(f"Found {len(emails)} emails")

    indexed = 0
    skipped = 0

    for email in emails:

        gmail_id = email["id"]
        print("EMAIL KEYS:", email.keys())
        print("THREAD ID:", email.get("threadId"))

        # ==============================
        # DEDUP
        # ==============================

     #  if email_exists(gmail_id):

     #      skipped += 1
     #      print("⏭ Already indexed")

     #      continue

        # ==============================
        # FETCH FULL EMAIL
        # ==============================

        msg_data = service.users().messages().get(
            userId="me",
            id=gmail_id,
            format="full"
        ).execute()

        print(msg_data.keys())

        thread_id = msg_data.get(
            "threadId",
            ""
        )

        payload = msg_data.get(
            "payload",
            {}
        )

        headers = payload.get(
            "headers",
            []
        )

        sender = ""
        subject = ""

        for header in headers:

            if header["name"] == "From":
                sender = header["value"]

            elif header["name"] == "Subject":
                subject = header["value"]

        snippet = msg_data.get(
            "snippet",
            ""
        )

        email_text = f"""
From: {sender}
Subject: {subject}

{snippet}
"""

        # ==============================
        # CREATE EMBEDDING
        # ==============================

        embedding = create_embedding(
            email_text
        )

        embedding_json = json.dumps(
            embedding
        )

        # ==============================
        # SAVE
        # ==============================

        save_email(
            gmail_id,
            thread_id,
            sender,
            subject,
            snippet,
            email_text,
            embedding_json,
            "historical",
            "indexed",
            "0",
            ""
        )

        cursor.execute("""
        INSERT OR IGNORE INTO threads (
            gmail_thread_id,
            subject,
            participants,
            last_message_snippet
        )
        VALUES (?, ?, ?, ?)
        """, (
            thread_id,
            subject,
            sender,
            snippet
        ))

        cursor.execute("""
        UPDATE threads
        SET last_message_snippet = ?
        WHERE gmail_thread_id = ?
        """, (
            snippet,
            thread_id
        ))

        indexed += 1

        print(f"✔ Indexed: {subject}")

        save_state(next_page_token)

    print("\n============================")
    print(f"Indexed: {indexed}")
    print(f"Skipped: {skipped}")
    print("============================")

if __name__ == "__main__":
    index_inbox()
