import json
from gmail_utils import get_gmail_service, fetch_emails
from classifier import classify_email
from responder import generate_reply
from draft_creator import create_draft
from summarizer import summarize_thread
from embeddings import create_embedding

from memory import (
    save_email,
    email_exists,
    save_contact,
    get_thread_summary,
    save_thread_summary,
    semantic_search,
    get_recent_emails_from_sender,
    update_sender,
    cursor
)


def main():

    # ==============================
    # GMAIL AUTH
    # ==============================

    service = get_gmail_service()

    # ==============================
    # FETCH EMAILS
    # ==============================

    emails, _ = fetch_emails(
        service,
        max_results=3
    )

    print(f"Fetched {len(emails)} emails")

    # ==============================
    # MAIN LOOP
    # ==============================

    for email in emails:

        gmail_id = email["id"]

        # ==============================
        # DEDUP CHECK
        # ==============================

        if email_exists(gmail_id):

            print("⏭ Skipping already processed email")
            continue

        # ==============================
        # FETCH FULL EMAIL
        # ==============================

        msg_data = service.users().messages().get(
            userId="me",
            id=gmail_id,
            format="full"
        ).execute()

        thread_id = msg_data.get("threadId", "")

        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])

        sender = ""
        subject = ""

        for header in headers:

            if header["name"] == "From":
                sender = header["value"]

            elif header["name"] == "Subject":
                subject = header["value"]

        save_contact(
            name=sender,
            email=sender,
            company="",
            role="",
            notes="auto-imported from inbox"
        )
        snippet = msg_data.get("snippet", "")

        email_text = f"""
From: {sender}
Subject: {subject}

{snippet}
"""

        embedding = create_embedding(
            email_text
        )        
        
        embedding_json = json.dumps(
            embedding
        )

        print("\n================ EMAIL ================\n")
        print(email_text)

        # ==============================
        # CLASSIFICATION
        # ==============================

        classification = classify_email(email_text, sender=sender, embedding=embedding)

        label = classification.get(
            "label",
            "unknown"
        )

        importance_score = classification.get(
            "importance_score",
            0
        )

        sender_trust = classification.get(
            "sender_trust",
            "low"
        )

        reason = classification.get(
            "reason",
            ""
        )

        action = classification.get(
            "suggested_action",
            "ignore"
        )

        print("\n============= CLASSIFICATION =============")
        print(classification)

        # ==============================
        # SENDER LEARNING
        # ==============================

        update_sender(
            sender,
            label == "important"
        )

        cursor.execute("""
        SELECT email_count, important_count
        FROM senders
        WHERE sender = ?
        """, (sender,))

        row = cursor.fetchone()

        trust_score = 0.0

        if row:

            email_count, important_count = row

            trust_score = (
                important_count / max(email_count, 1)
            )

        final_score = importance_score

        if trust_score > 0.7:
            final_score += 15

        elif trust_score < 0.3:
            final_score -= 15

        print("\n=========== INBOX SCORE ===========")
        print("Trust score:", trust_score)
        print("Final score:", final_score)
        print("Reason:", reason)

        # ==============================
        # THREAD MEMORY
        # ==============================

        existing_summary = get_thread_summary(
            thread_id
        )

        updated_summary = summarize_thread(
            existing_summary,
            email_text
        )

        save_thread_summary(
            thread_id,
            updated_summary
        )

        print("\n=========== THREAD MEMORY ===========")
        print(updated_summary)

        # ==============================
        # ROUTING
        # ==============================

        if action == "ignore":

            print("⏭ Ignoring email")

            save_email(
                gmail_id,
                thread_id,
                sender,
                subject,
                snippet,
                email_text,
                embedding_json,
                label,
                action,
                str(final_score),
                updated_summary
            )

            continue

        elif action == "summarize":

            print("🧠 Summary only")

            save_email(
                gmail_id,
                thread_id,
                sender,
                subject,
                snippet,
                email_text,
                embedding_json,
                label,
                action,
                str(final_score),
                updated_summary
            )

            continue

        elif action == "archive":

            print("📥 Archive action")

            save_email(
                gmail_id,
                thread_id,
                sender,
                subject,
                snippet,
                email_text,
                embedding_json,
                label,
                action,
                str(final_score),
                updated_summary
            )

            continue

        elif action == "reply":

            past_emails = semantic_search(
                embedding,
                limit=3
            )

            print("\n========= SEMANTIC MEMORIES =========\n")

            for i, memory in enumerate(past_emails):

                print(f"\nMEMORY {i+1}:\n")
                print(memory[:1000])

            print("\n=====================================\n")
            memory_context = "\n\n".join(
                past_emails
            )

            reply = generate_reply(
                email_text,
                updated_summary,
                memory_context
            )

            print("\n================ AI DRAFT ================\n")
            print(reply)

            create_draft(
                service,
                sender,
                subject,
                reply
            )

            save_email(
                gmail_id,
                thread_id,
                sender,
                subject,
                snippet,
                email_text,
                embedding_json,
                label,
                action,
                str(final_score),
                updated_summary
            )

            print("✔ Draft created + memory updated")

        else:

            print("⚠ Unknown action")

            save_email(
                gmail_id,
                thread_id,
                sender,
                subject,
                snippet,
                email_text,
                embedding_json,
                label,
                action,
                str(final_score),
                updated_summary
            )


if __name__ == "__main__":
    main()
