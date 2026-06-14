import json
from datetime import datetime, timezone
from openai import OpenAI
from typing import Optional

from corrections import get_sender_pattern
from db import db_cursor

client = OpenAI()

CONTACT_TYPES = ["brand", "peer", "creator", "agency", "fan", "business", "personal", "unknown"]

RELATIONSHIP_TYPES = ["new", "dormant", "active_correspondence", "one_way_inbound"]

# Newsletters/marketing senders are capped here regardless of frequency.
MARKETING_SCORE_CAP = 15.0
MARKETING_MIN_CORRECTIONS = 3

# Days since last contact before a relationship is considered dormant.
DORMANT_AFTER_DAYS = 180

# Days since first contact within which a relationship is still "new",
# regardless of how many emails have gone back and forth.
NEW_WITHIN_DAYS = 14


# ──────────────────────────────────────────────
# SCHEMA
# ──────────────────────────────────────────────

def init_contact_intelligence_tables():
    """No-op — table is created by supabase/schema.sql."""
    pass


# ──────────────────────────────────────────────
# UPSERT / UPDATE
# ──────────────────────────────────────────────

def upsert_contact_profile(
    user_id: str,
    email: str,
    name: str = "",
    company: str = "",
    role: str = "",
    received: bool = True
):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO contact_profiles (
                user_id, email, name, company, role,
                emails_received, emails_sent,
                first_contact_date, last_contact_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (user_id, email) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE contact_profiles.name END,
                company = CASE WHEN excluded.company != '' THEN excluded.company ELSE contact_profiles.company END,
                role = CASE WHEN excluded.role != '' THEN excluded.role ELSE contact_profiles.role END,
                emails_received = contact_profiles.emails_received + CASE WHEN %s THEN 1 ELSE 0 END,
                emails_sent = contact_profiles.emails_sent + CASE WHEN %s THEN 0 ELSE 1 END,
                last_contact_date = now(),
                updated_at = now()
        """, (
            user_id, email, name, company, role,
            1 if received else 0,
            0 if received else 1,
            received, received
        ))


def set_vip(user_id: str, email: str, reason: str = ""):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE contact_profiles
            SET is_vip = true, vip_reason = %s, updated_at = now()
            WHERE user_id = %s AND email = %s
        """, (reason, user_id, email))


def set_contact_type(user_id: str, email: str, contact_type: str):
    if contact_type not in CONTACT_TYPES:
        raise ValueError(f"contact_type must be one of {CONTACT_TYPES}")
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE contact_profiles
            SET contact_type = %s, updated_at = now()
            WHERE user_id = %s AND email = %s
        """, (contact_type, user_id, email))


def update_ai_summary(user_id: str, email: str, summary: str):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE contact_profiles
            SET ai_summary = %s, updated_at = now()
            WHERE user_id = %s AND email = %s
        """, (summary, user_id, email))


# ──────────────────────────────────────────────
# RELATIONSHIP SCORE
# ──────────────────────────────────────────────

def classify_relationship_type(row: dict) -> str:
    """
    Classify a contact into one of RELATIONSHIP_TYPES based on
    interaction counts and recency:
      - "new": just started exchanging emails, not enough history yet
      - "dormant": no contact in a long time
      - "active_correspondence": ongoing two-way exchange
      - "one_way_inbound": one-directional (usually they email you, no reply)
    """
    received = row["emails_received"] or 0
    sent = row["emails_sent"] or 0
    total = received + sent

    if total == 0:
        return "new"

    now = datetime.now(timezone.utc)

    if row["first_contact_date"]:
        try:
            if (now - row["first_contact_date"]).days <= NEW_WITHIN_DAYS:
                return "new"
        except Exception:
            pass

    if row["last_contact_date"]:
        try:
            if (now - row["last_contact_date"]).days > DORMANT_AFTER_DAYS:
                return "dormant"
        except Exception:
            pass

    if received > 0 and sent > 0:
        return "active_correspondence"

    return "one_way_inbound"


def compute_relationship_score(user_id: str, email: str) -> float:
    """
    Score = weighted combo of:
      - Bidirectionality (they email you AND you email them) — weighted heaviest
      - Total interactions (sent + received)
      - Recency (higher if contacted in last 30/90 days)
    Returns 0.0–100.0, capped low for known newsletter/marketing senders.
    """
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM contact_profiles WHERE user_id = %s AND email = %s",
            (user_id, email)
        )
        row = cur.fetchone()

    if not row:
        return 0.0

    received = row["emails_received"] or 0
    sent = row["emails_sent"] or 0
    total = received + sent

    # Bidirectionality score (0-40) — the strongest signal of a real relationship
    bidir_score = 40.0 if (received > 0 and sent > 0) else 0.0

    # Frequency score (0-30)
    freq_score = min(total * 2, 30)

    # Recency score (0-30)
    recency_score = 0.0
    if row["last_contact_date"]:
        try:
            days_ago = (datetime.now(timezone.utc) - row["last_contact_date"]).days
            if days_ago <= 7:
                recency_score = 30
            elif days_ago <= 30:
                recency_score = 22
            elif days_ago <= 90:
                recency_score = 11
            elif days_ago <= 180:
                recency_score = 4
        except Exception:
            pass

    score = round(bidir_score + freq_score + recency_score, 1)

    # Newsletter/marketing senders are capped regardless of how often they email,
    # detected via repeated user corrections to "marketing" for this domain.
    pattern = get_sender_pattern(user_id, email)
    if (
        pattern
        and pattern["typical_category"] == "marketing"
        and pattern["correction_count"] >= MARKETING_MIN_CORRECTIONS
    ):
        score = min(score, MARKETING_SCORE_CAP)

    relationship_type = classify_relationship_type(row)

    # Persist the updated score and relationship type
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE contact_profiles SET relationship_score = %s, relationship_type = %s WHERE user_id = %s AND email = %s",
            (score, relationship_type, user_id, email)
        )

    return score


def refresh_all_scores(user_id: str):
    """Recompute relationship scores for all contacts. Run periodically."""
    with db_cursor() as cur:
        cur.execute("SELECT email FROM contact_profiles WHERE user_id = %s", (user_id,))
        emails = [r[0] for r in cur.fetchall()]

    for email in emails:
        compute_relationship_score(user_id, email)

    print(f"✔ Refreshed scores for {len(emails)} contacts")


# ──────────────────────────────────────────────
# AI CONTACT CATEGORIZATION
# ──────────────────────────────────────────────

def ai_categorize_contact(user_id: str, email: str, recent_emails: list[str]) -> dict:
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
        update_ai_summary(user_id, email, result.get("summary", ""))
        if result.get("type") in CONTACT_TYPES:
            set_contact_type(user_id, email, result["type"])
        return result
    except Exception:
        return {"type": "unknown", "summary": "Could not categorize."}


# ──────────────────────────────────────────────
# QUERIES
# ──────────────────────────────────────────────

def get_contact(user_id: str, email: str) -> Optional[dict]:
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM contact_profiles WHERE user_id = %s AND email ILIKE %s",
            (user_id, f"%{email}%")
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_top_contacts(user_id: str, limit: int = 20, by: str = "relationship_score") -> list[dict]:
    valid = ["relationship_score", "emails_received", "emails_sent", "last_contact_date"]
    order_col = by if by in valid else "relationship_score"
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            f"SELECT * FROM contact_profiles WHERE user_id = %s ORDER BY {order_col} DESC LIMIT %s",
            (user_id, limit)
        )
        return [dict(r) for r in cur.fetchall()]


def get_contacts_by_type(user_id: str, contact_type: str) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM contact_profiles WHERE user_id = %s AND contact_type = %s ORDER BY relationship_score DESC",
            (user_id, contact_type)
        )
        return [dict(r) for r in cur.fetchall()]


def get_vip_contacts(user_id: str) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM contact_profiles WHERE user_id = %s AND is_vip = true ORDER BY relationship_score DESC",
            (user_id,)
        )
        return [dict(r) for r in cur.fetchall()]


def search_contacts(user_id: str, query: str) -> list[dict]:
    q = f"%{query}%"
    with db_cursor(dict_rows=True) as cur:
        cur.execute("""
            SELECT * FROM contact_profiles
            WHERE user_id = %s
              AND (email ILIKE %s OR name ILIKE %s OR company ILIKE %s OR ai_summary ILIKE %s)
            ORDER BY relationship_score DESC
            LIMIT 20
        """, (user_id, q, q, q, q))
        return [dict(r) for r in cur.fetchall()]
