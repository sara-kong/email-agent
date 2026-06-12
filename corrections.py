import sqlite3
import json
import re
from typing import Optional

from memory import cosine_similarity

DB_PATH = "memory.db"

# A sender domain needs this many corrections to the SAME category before
# it's treated as a high-confidence prior (and can skip the GPT call).
SENDER_PATTERN_MIN_COUNT = 3

# Default number of past corrections to inject as few-shot examples.
FEW_SHOT_LIMIT = 8


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_corrections_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id            TEXT,
            sender              TEXT,
            sender_domain       TEXT,
            original_category   TEXT,
            corrected_category  TEXT,
            original_action     TEXT,
            corrected_action    TEXT,
            email_text          TEXT,
            embedding           TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("✔ Corrections table initialized")


def init_sender_patterns_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sender_patterns (
            sender_domain       TEXT PRIMARY KEY,
            typical_category    TEXT,
            typical_action      TEXT,
            correction_count    INTEGER DEFAULT 0,
            last_updated        TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("✔ Sender patterns table initialized")


def extract_domain(sender: str) -> str:
    """Pull the domain out of a sender header like 'Name <user@domain.com>'."""
    match = re.search(r'@([\w.-]+)', sender or "")
    return match.group(1).lower() if match else (sender or "").lower()


def log_correction(
    gmail_id: str,
    sender: str,
    original_category: str,
    corrected_category: str,
    original_action: str,
    corrected_action: str,
    email_text: str,
    embedding_json: Optional[str] = None,
):
    """Record a user correction to an email's classification for future few-shot examples."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO corrections (
            gmail_id, sender, sender_domain,
            original_category, corrected_category,
            original_action, corrected_action,
            email_text, embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        gmail_id, sender, extract_domain(sender),
        original_category, corrected_category,
        original_action, corrected_action,
        email_text, embedding_json
    ))
    conn.commit()
    conn.close()

    update_sender_pattern(extract_domain(sender), corrected_category, corrected_action)


def update_sender_pattern(sender_domain: str, category: str, action: str):
    """
    Track what category/action a sender domain is typically corrected to.
    If the new correction matches the existing pattern, reinforce it
    (increment correction_count). If it disagrees, the user has changed
    their mind about this domain — start the count over with the new value.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM sender_patterns WHERE sender_domain = ?", (sender_domain,))
    row = c.fetchone()

    if row and row["typical_category"] == category:
        c.execute("""
            UPDATE sender_patterns
            SET correction_count = correction_count + 1,
                typical_action = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE sender_domain = ?
        """, (action, sender_domain))
    else:
        c.execute("""
            INSERT INTO sender_patterns (sender_domain, typical_category, typical_action, correction_count, last_updated)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(sender_domain) DO UPDATE SET
                typical_category = excluded.typical_category,
                typical_action = excluded.typical_action,
                correction_count = 1,
                last_updated = CURRENT_TIMESTAMP
        """, (sender_domain, category, action))

    conn.commit()
    conn.close()


def get_sender_pattern(sender: str) -> Optional[dict]:
    """Return the learned correction pattern for this sender's domain, if any."""
    domain = extract_domain(sender)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM sender_patterns WHERE sender_domain = ?", (domain,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_high_confidence_pattern(sender: str, min_count: int = SENDER_PATTERN_MIN_COUNT) -> Optional[dict]:
    """Return the sender pattern only if it's been confirmed enough times to trust as a strong prior."""
    pattern = get_sender_pattern(sender)
    if pattern and pattern["correction_count"] >= min_count:
        return pattern
    return None


def get_relevant_corrections(sender: str = None, embedding: list = None, limit: int = FEW_SHOT_LIMIT) -> list[dict]:
    """
    Pull past corrections to use as few-shot classification examples, preferring:
      1. Corrections from the same sender domain (most recent first)
      2. Then, to fill remaining slots, corrections ranked by semantic
         similarity to the email being classified (if an embedding is given)
    Returns [] if no corrections have been logged yet.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM corrections ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

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
                if not r.get("embedding"):
                    continue
                try:
                    emb = json.loads(r["embedding"])
                    scored.append((cosine_similarity(embedding, emb), r))
                except Exception:
                    continue
            scored.sort(reverse=True, key=lambda x: x[0])
            selected += [r for _, r in scored[:slots_left]]
        else:
            selected += remaining[:slots_left]

    return selected[:limit]


if __name__ == "__main__":
    init_corrections_table()
    init_sender_patterns_table()
