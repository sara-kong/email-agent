import math
from datetime import datetime, timezone

from db import db_cursor

# Half-life-style exponential decay applied to semantic search scores.
# Emails older than ~6 months should rarely surface unless very semantically relevant.
DEFAULT_DECAY_DAYS = 90


# ==============================
# SAVE EMAIL
# ==============================
def save_email(
    user_id,
    gmail_id,
    thread_id,
    sender,
    subject,
    snippet,
    email_text,
    embedding,
    label,
    action,
    score,
    summary,
    draft_status="none",
    draft_text=None,
    draft_gmail_id=None
):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO emails (
                user_id, gmail_id, thread_id, sender, subject, snippet,
                full_text, embedding, category, action, importance, summary,
                draft_status, draft_text, draft_gmail_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, gmail_id) DO NOTHING
        """, (
            user_id, gmail_id, thread_id, sender, subject, snippet,
            email_text, embedding, label, action, score, summary,
            draft_status, draft_text, draft_gmail_id
        ))


# ==============================
# DEDUP CHECK
# ==============================
def email_exists(user_id, gmail_id):
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM emails WHERE user_id = %s AND gmail_id = %s",
            (user_id, gmail_id)
        )
        return cur.fetchone() is not None


# ==============================
# GET ALL CONTACT-LIKE DATA
# ==============================
def get_all_contacts(user_id):
    with db_cursor() as cur:
        cur.execute("""
            SELECT sender, COUNT(*) as freq
            FROM emails
            WHERE user_id = %s
            GROUP BY sender
            ORDER BY freq DESC
        """, (user_id,))
        return cur.fetchall()


# ==============================
# GET THREAD (CRITICAL FOR YOUR OS)
# ==============================
def get_thread(user_id, thread_id):
    with db_cursor() as cur:
        cur.execute("""
            SELECT sender, subject, snippet, full_text
            FROM emails
            WHERE user_id = %s AND thread_id = %s
            ORDER BY id ASC
        """, (user_id, thread_id))
        return cur.fetchall()


# ==============================
# SHARED SIMILARITY HELPER
# ==============================
def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-8)


# ==============================
# BASIC SEMANTIC SEARCH (SAFE VERSION)
# ==============================
def semantic_search(user_id, embedding, limit=5, decay_days=DEFAULT_DECAY_DAYS):
    """
    Ranks by cosine_similarity * decay_factor, where
    decay_factor = exp(-days_since_email / decay_days). Emails without a
    known created_at are not penalized, since their age is unknown.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT full_text, embedding, created_at
            FROM emails
            WHERE user_id = %s AND embedding IS NOT NULL
        """, (user_id,))
        rows = cur.fetchall()

    now = datetime.now(timezone.utc)
    scored = []

    for text, emb, created_at in rows:
        try:
            similarity = cosine_similarity(embedding, emb)

            decay_factor = 1.0
            if created_at:
                days_since = (now - created_at).total_seconds() / 86400
                decay_factor = math.exp(-days_since / decay_days)

            score = similarity * decay_factor
            scored.append((score, text))
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])

    return [x[1] for x in scored[:limit]]


# ==============================
# THREAD-BASED MEMORY SEARCH (KEY UPGRADE)
# ==============================
def semantic_search_thread(user_id, thread_id, embedding, limit=3):
    with db_cursor() as cur:
        cur.execute("""
            SELECT full_text, embedding
            FROM emails
            WHERE user_id = %s AND thread_id = %s AND embedding IS NOT NULL
        """, (user_id, thread_id))
        rows = cur.fetchall()

    scored = []
    for text, emb in rows:
        try:
            score = cosine_similarity(embedding, emb)
            scored.append((score, text))
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])
    return [x[1] for x in scored[:limit]]


def upsert_contact(user_id, email, received=True):
    with db_cursor(commit=True) as cur:
        if received:
            cur.execute("""
                INSERT INTO contacts (user_id, email, emails_received, last_contact_date)
                VALUES (%s, %s, 1, now())
                ON CONFLICT (user_id, email) DO UPDATE SET
                    emails_received = contacts.emails_received + 1,
                    last_contact_date = now()
            """, (user_id, email))
        else:
            cur.execute("""
                INSERT INTO contacts (user_id, email, emails_sent, last_contact_date)
                VALUES (%s, %s, 1, now())
                ON CONFLICT (user_id, email) DO UPDATE SET
                    emails_sent = contacts.emails_sent + 1,
                    last_contact_date = now()
            """, (user_id, email))


def upsert_thread(user_id, thread_id, subject, sender, snippet):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO threads (
                user_id, gmail_thread_id, subject, participants,
                message_count, last_message_snippet
            )
            VALUES (%s, %s, %s, %s, 1, %s)
            ON CONFLICT (user_id, gmail_thread_id) DO UPDATE SET
                message_count = threads.message_count + 1,
                last_message_snippet = excluded.last_message_snippet,
                last_updated = now()
        """, (user_id, thread_id, subject, sender, snippet))


def get_thread_summary(user_id, thread_id):
    with db_cursor() as cur:
        cur.execute(
            "SELECT summary FROM thread_summaries WHERE user_id = %s AND thread_id = %s",
            (user_id, thread_id)
        )
        row = cur.fetchone()
        return row[0] if row else ""


def save_thread_summary(user_id, thread_id, summary):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO thread_summaries (user_id, thread_id, summary)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, thread_id) DO UPDATE SET
                summary = excluded.summary,
                updated_at = now()
        """, (user_id, thread_id, summary))


def update_sender(user_id, sender, is_important):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO senders (user_id, sender, email_count, important_count)
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (user_id, sender) DO UPDATE SET
                email_count = senders.email_count + 1,
                important_count = senders.important_count + CASE WHEN %s THEN 1 ELSE 0 END,
                last_seen = now()
        """, (user_id, sender, 1 if is_important else 0, is_important))


def get_recent_emails_from_sender(user_id, sender, limit=5):
    with db_cursor() as cur:
        cur.execute("""
            SELECT full_text FROM emails
            WHERE user_id = %s AND sender ILIKE %s
            ORDER BY id DESC LIMIT %s
        """, (user_id, f"%{sender}%", limit))
        return [r[0] for r in cur.fetchall()]
