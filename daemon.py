import time
import threading
import logging
from datetime import datetime

from db import db_cursor
from auth import get_gmail_service_for_user
from gmail_utils import fetch_emails
from classifier import classify_email
from draft_creator import generate_and_create_draft, within_draft_window
from summarizer import summarize_thread
from embeddings import create_embedding
from memory import (
    save_email, email_exists, upsert_thread,
    get_thread_summary, save_thread_summary,
    update_sender
)
from campaign_tracker import check_if_campaign_reply, init_campaign_tables
from contact_intelligence import upsert_contact_profile, init_contact_intelligence_tables
from style_profiler import init_style_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAEMON] %(message)s"
)
log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # how often to check for new mail (5 min)
MAX_PER_POLL = 10            # max emails to process per cycle

_running = False
_thread = None


def get_active_user_ids() -> list[str]:
    """All users who have connected Gmail (have a row in oauth_tokens)."""
    with db_cursor() as cur:
        cur.execute("SELECT user_id FROM oauth_tokens")
        return [str(r[0]) for r in cur.fetchall()]


def process_single_email(user_id: str, service, gmail_id: str, event_callback=None):
    """
    Full processing pipeline for one email.
    event_callback(dict) — optional hook for WebSocket broadcast.
    """
    if email_exists(user_id, gmail_id):
        return

    msg_data = service.users().messages().get(
        userId="me", id=gmail_id, format="full"
    ).execute()

    thread_id = msg_data.get("threadId", "")
    payload = msg_data.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

    sender = headers.get("From", "")
    subject = headers.get("Subject", "")
    snippet = msg_data.get("snippet", "")
    email_text = f"From: {sender}\nSubject: {subject}\n\n{snippet}"

    # Embed + classify
    embedding = create_embedding(email_text)
    classification = classify_email(user_id, email_text, sender=sender, embedding=embedding)
    label = classification.get("label", "unknown")
    action = classification.get("suggested_action", "ignore")
    importance_score = classification.get("importance_score", 0)

    # Thread memory
    existing_summary = get_thread_summary(user_id, thread_id)
    updated_summary = summarize_thread(existing_summary, email_text)
    save_thread_summary(user_id, thread_id, updated_summary)

    # Sender trust update
    update_sender(user_id, sender, label == "important")

    # Campaign reply detection
    campaign_match = check_if_campaign_reply(user_id, sender, gmail_id)
    if campaign_match:
        log.info(f"🎯 Campaign reply detected from {sender} — campaign: {campaign_match['campaign_name']}")

    # Reply generation (only for reply-worthy emails, and only for emails
    # received recently — avoids mass-drafting an old backlog on cold start)
    draft_status = "none"
    draft_text = None
    draft_gmail_id = None
    if action == "reply" and within_draft_window(msg_data.get("internalDate")):
        draft_text, draft_gmail_id = generate_and_create_draft(
            user_id, service, sender, subject, email_text, updated_summary, embedding
        )
        draft_status = "ready"
        log.info(f"✉ Draft created for: {subject[:50]}")

    # Persist
    save_email(
        user_id, gmail_id, thread_id, sender, subject, snippet,
        email_text, embedding,
        label, action, str(importance_score), updated_summary,
        draft_status=draft_status, draft_text=draft_text, draft_gmail_id=draft_gmail_id
    )

    # Update contact profile
    upsert_contact_profile(user_id, email=sender, name=sender, received=True)
    upsert_thread(user_id, thread_id, subject, sender, snippet)

    event = {
        "event": "new_email",
        "user_id": user_id,
        "gmail_id": gmail_id,
        "sender": sender,
        "subject": subject,
        "label": label,
        "action": action,
        "draft_status": draft_status,
        "campaign_reply": campaign_match is not None,
        "timestamp": datetime.utcnow().isoformat()
    }

    if event_callback:
        event_callback(event)
    else:
        log.info(f"📧 Processed: [{label}] {subject[:60]}")

    return event


def poll_once(user_id: str, service, event_callback=None) -> int:
    """Run one poll cycle for a single user. Returns number of new emails processed."""
    emails, _ = fetch_emails(service, max_results=MAX_PER_POLL)
    processed = 0

    for email in emails:
        try:
            result = process_single_email(user_id, service, email["id"], event_callback)
            if result:
                processed += 1
        except Exception as e:
            log.error(f"Error processing {email['id']} for user {user_id}: {e}")

    return processed


def _daemon_loop(event_callback=None):
    global _running
    log.info(f"🚀 Daemon started — polling every {POLL_INTERVAL_SECONDS}s")

    while _running:
        try:
            user_ids = get_active_user_ids()
            for user_id in user_ids:
                try:
                    service = get_gmail_service_for_user(user_id)
                    n = poll_once(user_id, service, event_callback)
                    if n > 0:
                        log.info(f"✔ [{user_id}] Processed {n} new emails")
                except Exception as e:
                    log.error(f"Poll error for user {user_id}: {e}")
        except Exception as e:
            log.error(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)

    log.info("🛑 Daemon stopped")


def start_daemon(event_callback=None):
    """Start the daemon in a background thread."""
    global _running, _thread

    if _running:
        log.warning("Daemon already running")
        return

    init_campaign_tables()
    init_contact_intelligence_tables()
    init_style_table()

    _running = True
    _thread = threading.Thread(
        target=_daemon_loop,
        args=(event_callback,),
        daemon=True
    )
    _thread.start()
    return _thread


def stop_daemon():
    global _running
    _running = False
    log.info("Daemon stop requested")


if __name__ == "__main__":
    start_daemon()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_daemon()
        print("\nDaemon stopped.")
