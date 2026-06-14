import re
from typing import Optional

from memory import cosine_similarity
from db import db_cursor

# A sender domain needs this many corrections to the SAME category before
# it's treated as a high-confidence prior (and can skip the GPT call).
SENDER_PATTERN_MIN_COUNT = 3

# Default number of past corrections to inject as few-shot examples.
FEW_SHOT_LIMIT = 8


def init_corrections_table():
    """No-op — table is created by supabase/schema.sql."""
    pass


def init_sender_patterns_table():
    """No-op — table is created by supabase/schema.sql."""
    pass


def extract_domain(sender: str) -> str:
    """Pull the domain out of a sender header like 'Name <user@domain.com>'."""
    match = re.search(r'@([\w.-]+)', sender or "")
    return match.group(1).lower() if match else (sender or "").lower()


def log_correction(
    user_id: str,
    gmail_id: str,
    sender: str,
    original_category: str,
    corrected_category: str,
    original_action: str,
    corrected_action: str,
    email_text: str,
    embedding: Optional[list] = None,
):
    """Record a user correction to an email's classification for future few-shot examples."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO corrections (
                user_id, gmail_id, sender, sender_domain,
                original_category, corrected_category,
                original_action, corrected_action,
                email_text, embedding
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, gmail_id, sender, extract_domain(sender),
            original_category, corrected_category,
            original_action, corrected_action,
            email_text, embedding
        ))

    update_sender_pattern(user_id, extract_domain(sender), corrected_category, corrected_action)


def update_sender_pattern(user_id: str, sender_domain: str, category: str, action: str):
    """
    Track what category/action a sender domain is typically corrected to.
    If the new correction matches the existing pattern, reinforce it
    (increment correction_count). If it disagrees, the user has changed
    their mind about this domain — start the count over with the new value.
    """
    with db_cursor(commit=True, dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM sender_patterns WHERE user_id = %s AND sender_domain = %s",
            (user_id, sender_domain)
        )
        row = cur.fetchone()

        if row and row["typical_category"] == category:
            cur.execute("""
                UPDATE sender_patterns
                SET correction_count = correction_count + 1,
                    typical_action = %s,
                    last_updated = now()
                WHERE user_id = %s AND sender_domain = %s
            """, (action, user_id, sender_domain))
        else:
            cur.execute("""
                INSERT INTO sender_patterns (user_id, sender_domain, typical_category, typical_action, correction_count, last_updated)
                VALUES (%s, %s, %s, %s, 1, now())
                ON CONFLICT (user_id, sender_domain) DO UPDATE SET
                    typical_category = excluded.typical_category,
                    typical_action = excluded.typical_action,
                    correction_count = 1,
                    last_updated = now()
            """, (user_id, sender_domain, category, action))


def get_sender_pattern(user_id: str, sender: str) -> Optional[dict]:
    """Return the learned correction pattern for this sender's domain, if any."""
    domain = extract_domain(sender)
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM sender_patterns WHERE user_id = %s AND sender_domain = %s",
            (user_id, domain)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_high_confidence_pattern(user_id: str, sender: str, min_count: int = SENDER_PATTERN_MIN_COUNT) -> Optional[dict]:
    """Return the sender pattern only if it's been confirmed enough times to trust as a strong prior."""
    pattern = get_sender_pattern(user_id, sender)
    if pattern and pattern["correction_count"] >= min_count:
        return pattern
    return None


def get_relevant_corrections(user_id: str, sender: str = None, embedding: list = None, limit: int = FEW_SHOT_LIMIT) -> list[dict]:
    """
    Pull past corrections to use as few-shot classification examples, preferring:
      1. Corrections from the same sender domain (most recent first)
      2. Then, to fill remaining slots, corrections ranked by semantic
         similarity to the email being classified (if an embedding is given)
    Returns [] if no corrections have been logged yet.
    """
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM corrections WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return []

    domain = extract_domain(sender) if sender else None
    domain_matches = [r for r in rows if domain and r["sender_domain"] == domain]
    domain_match_ids = {r["id"] for r in domain_matches}
    remaining = [r for r in rows if r["id"] not in domain_match_ids]

    selected = domain_matches[:limit]

    if len(selected) < limit and remaining:
        slots_left = limit - len(selected)
        if embedding:
            scored = []
            for r in remaining:
                if r.get("embedding") is None:
                    continue
                try:
                    scored.append((cosine_similarity(embedding, r["embedding"]), r))
                except Exception:
                    continue
            scored.sort(reverse=True, key=lambda x: x[0])
            selected += [r for _, r in scored[:slots_left]]
        else:
            selected += remaining[:slots_left]

    return selected[:limit]
