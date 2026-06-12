import sqlite3
import json
from datetime import datetime, timedelta
from openai import OpenAI
from typing import Optional

DB_PATH = "memory.db"
client = OpenAI()

CONTACT_TYPES = ["brand", "peer", "creator", "agency", "fan", "business", "personal", "unknown"]


# ──────────────────────────────────────────────
# SCHEMA
# ──────────────────────────────────────────────

def init_contact_intelligence_tables():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Enhanced contacts table (extends the existing one)
    c.execute("""
        CREATE TABLE IF NOT EXISTS contact_profiles (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            email               TEXT UNIQUE NOT NULL,
            name                TEXT DEFAULT '',
            company             TEXT DEFAULT '',
            role                TEXT DEFAULT '',
            contact_type        TEXT DEFAULT 'unknown',
            -- brand | peer | creator | agency | fan | business | personal | unknown

            emails_received     INTEGER DEFAULT 0,
            emails_sent         INTEGER DEFAULT 0,
            threads_shared      INTEGER DEFAULT 0,
            first_contact_date  TEXT,
            last_contact_date   TEXT,

            relationship_score  REAL DEFAULT 0.0,
            -- 0-100: based on frequency, recency, reply rate
            is_vip              INTEGER DEFAULT 0,
            vip_reason          TEXT DEFAULT '',

            ai_summary          TEXT DEFAULT '',
            -- AI-generated 1-2 sentence context: "Brand manager at X, reached out about..."

            tags                TEXT DEFAULT '[]',
            -- JSON list of custom tags

            notes               TEXT DEFAULT '',
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("✔ Contact intelligence tables initialized")


# ──────────────────────────────────────────────
# UPSERT / UPDATE
# ──────────────────────────────────────────────

def upsert_contact_profile(
    email: str,
    name: str = "",
    company: str = "",
    role: str = "",
    received: bool = True
):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    now = datetime.utcnow().isoformat()

    c.execute("""
        INSERT INTO contact_profiles (
            email, name, company, role,
            emails_received, emails_sent,
            first_contact_date, last_contact_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            name = CASE WHEN excluded.name != '' THEN excluded.name ELSE contact_profiles.name END,
            company = CASE WHEN excluded.company != '' THEN excluded.company ELSE contact_profiles.company END,
            role = CASE WHEN excluded.role != '' THEN excluded.role ELSE contact_profiles.role END,
            emails_received = contact_profiles.emails_received + CASE WHEN ? THEN 1 ELSE 0 END,
            emails_sent = contact_profiles.emails_sent + CASE WHEN ? THEN 0 ELSE 1 END,
            last_contact_date = ?,
            updated_at = ?
    """, (
        email, name, company, role,
        1 if received else 0,
        0 if received else 1,
        now, now,
        # ON CONFLICT params:
        received, received,
        now, now
    ))

    conn.commit()
    conn.close()


def set_vip(email: str, reason: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE contact_profiles
        SET is_vip = 1, vip_reason = ?, updated_at = CURRENT_TIMESTAMP
        WHERE email = ?
    """, (reason, email))
    conn.commit()
    conn.close()


def set_contact_type(email: str, contact_type: str):
    if contact_type not in CONTACT_TYPES:
        raise ValueError(f"contact_type must be one of {CONTACT_TYPES}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE contact_profiles
        SET contact_type = ?, updated_at = CURRENT_TIMESTAMP
        WHERE email = ?
    """, (contact_type, email))
    conn.commit()
    conn.close()


def update_ai_summary(email: str, summary: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE contact_profiles
        SET ai_summary = ?, updated_at = CURRENT_TIMESTAMP
        WHERE email = ?
    """, (summary, email))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# RELATIONSHIP SCORE
# ──────────────────────────────────────────────

def compute_relationship_score(email: str) -> float:
    """
    Score = weighted combo of:
      - Total interactions (sent + received)
      - Recency (higher if contacted in last 30/90 days)
      - Bidirectionality (they email you AND you email them)
    Returns 0.0–100.0
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contact_profiles WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()

    if not row:
        return 0.0

    received = row["emails_received"] or 0
    sent = row["emails_sent"] or 0
    total = received + sent

    # Frequency score (0-40)
    freq_score = min(total * 2, 40)

    # Recency score (0-40)
    recency_score = 0.0
    if row["last_contact_date"]:
        try:
            last = datetime.fromisoformat(row["last_contact_date"])
            days_ago = (datetime.utcnow() - last).days
            if days_ago <= 7:
                recency_score = 40
            elif days_ago <= 30:
                recency_score = 30
            elif days_ago <= 90:
                recency_score = 15
            elif days_ago <= 180:
                recency_score = 5
        except Exception:
            pass

    # Bidirectionality score (0-20)
    bidir_score = 20.0 if (received > 0 and sent > 0) else 0.0

    score = round(freq_score + recency_score + bidir_score, 1)

    # Persist the updated score
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE contact_profiles SET relationship_score = ? WHERE email = ?",
        (score, email)
    )
    conn.commit()
    conn.close()

    return score


def refresh_all_scores():
    """Recompute relationship scores for all contacts. Run periodically."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT email FROM contact_profiles")
    emails = [r["email"] for r in c.fetchall()]
    conn.close()

    for email in emails:
        compute_relationship_score(email)

    print(f"✔ Refreshed scores for {len(emails)} contacts")


# ──────────────────────────────────────────────
# AI CONTACT CATEGORIZATION
# ──────────────────────────────────────────────

def ai_categorize_contact(email: str, recent_emails: list[str]) -> dict:
    """
    Given a few recent emails from/to a contact, ask GPT to classify them
    and write a short summary. Returns {"type": ..., "summary": ...}
    """
    if not recent_emails:
        return {"type": "unknown", "summary": "No email history available."}

    sample = "\n---\n".join(recent_emails[:5])

    prompt = f"""You're helping categorize an email contact for a creator/freelancer.

Contact email: {email}

Recent emails:
{sample}

Return a JSON object with:
{{
  "type": one of ["brand", "peer", "creator", "agency", "fan", "business", "personal", "unknown"],
  "summary": "1-2 sentence description of who this person appears to be and why they're emailing"
}}

Return only JSON. No markdown.
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "")
    try:
        result = json.loads(raw)
        update_ai_summary(email, result.get("summary", ""))
        if result.get("type") in CONTACT_TYPES:
            set_contact_type(email, result["type"])
        return result
    except Exception:
        return {"type": "unknown", "summary": "Could not categorize."}


# ──────────────────────────────────────────────
# QUERIES
# ──────────────────────────────────────────────

def get_contact(email: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contact_profiles WHERE email LIKE ?", (f"%{email}%",))
    row = c.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        return d
    return None


def get_top_contacts(limit: int = 20, by: str = "relationship_score") -> list[dict]:
    valid = ["relationship_score", "emails_received", "emails_sent", "last_contact_date"]
    order_col = by if by in valid else "relationship_score"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(f"SELECT * FROM contact_profiles ORDER BY {order_col} DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contacts_by_type(contact_type: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contact_profiles WHERE contact_type = ? ORDER BY relationship_score DESC", (contact_type,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_vip_contacts() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM contact_profiles WHERE is_vip = 1 ORDER BY relationship_score DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_contacts(query: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    q = f"%{query}%"
    c.execute("""
        SELECT * FROM contact_profiles
        WHERE email LIKE ? OR name LIKE ? OR company LIKE ? OR ai_summary LIKE ?
        ORDER BY relationship_score DESC
        LIMIT 20
    """, (q, q, q, q))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_contact_intelligence_tables()
    refresh_all_scores()
