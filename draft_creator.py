import base64
from datetime import datetime, timedelta, timezone

# Only auto-generate a draft for emails received within this window. Prevents
# a cold start (or a restart after downtime) from mass-drafting an entire
# backlog of old, un-ingested inbox emails.
DRAFT_BACKLOG_HOURS = 48


def within_draft_window(internal_date_ms, hours=DRAFT_BACKLOG_HOURS) -> bool:
    """internal_date_ms: Gmail's internalDate field (epoch ms, as string or int)."""
    if not internal_date_ms:
        return True
    try:
        received_at = datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        return True
    return datetime.now(timezone.utc) - received_at <= timedelta(hours=hours)


def _build_raw_message(sender, subject, body):
    email_text = f"""To: {sender}
Subject: Re: {subject}

{body}
"""
    return base64.urlsafe_b64encode(email_text.encode("utf-8")).decode("utf-8")


def create_draft(service, sender, subject, body):
    """Create a Gmail draft. Returns the created draft dict (includes 'id')."""
    raw_message = _build_raw_message(sender, subject, body)

    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw_message}}
    ).execute()

    print("✔ Draft created in Gmail")
    return draft


def update_draft(service, draft_id, sender, subject, body):
    """Replace the contents of an existing Gmail draft. Returns the updated draft dict."""
    raw_message = _build_raw_message(sender, subject, body)

    return service.users().drafts().update(
        userId="me",
        id=draft_id,
        body={"message": {"raw": raw_message}}
    ).execute()


def send_draft(service, draft_id):
    """Send an existing Gmail draft. Returns the sent message dict."""
    return service.users().drafts().send(
        userId="me",
        body={"id": draft_id}
    ).execute()


def generate_and_create_draft(user_id, service, sender, subject, email_text, thread_summary, embedding):
    """
    Generate a reply in the user's voice (using memory + style examples) and
    save it as a Gmail draft. Returns (reply_text, draft_id).
    """
    from responder import generate_reply
    from memory import semantic_search
    from style_profiler import get_style_prompt

    past_emails = semantic_search(user_id, embedding, limit=3)
    memory_context = "\n\n".join(past_emails)
    style_prompt = get_style_prompt(user_id)

    reply_text = generate_reply(user_id, email_text, thread_summary, memory_context, style_prompt)
    draft = create_draft(service, sender, subject, reply_text)

    return reply_text, draft.get("id")
