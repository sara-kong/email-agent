import json
import re
import sqlite3
from typing import Optional
from openai import OpenAI

DB_PATH = "memory.db"
client = OpenAI()


# ──────────────────────────────────────────────
# SCHEMA
# ──────────────────────────────────────────────

def init_style_table():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS style_profile (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_json    TEXT NOT NULL,
            sample_count    INTEGER DEFAULT 0,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Store individual sent email samples for future re-analysis
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id    TEXT UNIQUE,
            body        TEXT,
            to_email    TEXT,
            subject     TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# FETCH SENT EMAILS FROM GMAIL
# ──────────────────────────────────────────────

def fetch_sent_emails(service, max_results: int = 50) -> list[dict]:
    """Pull from the user's SENT label."""
    results = service.users().messages().list(
        userId="me",
        labelIds=["SENT"],
        maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    sent_emails = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me",
            id=msg_ref["id"],
            format="full"
        ).execute()

        payload = msg.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

        body = _extract_body(payload)
        if not body or len(body.strip()) < 30:
            continue

        sent_emails.append({
            "gmail_id": msg["id"],
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "body": body.strip()
        })

    return sent_emails


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail payload."""
    import base64

    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    return ""


# ──────────────────────────────────────────────
# STYLE ANALYSIS
# ──────────────────────────────────────────────

def analyze_style(email_samples: list[str]) -> dict:
    """
    Send a batch of the user's sent emails to GPT and extract
    a structured style profile as JSON.
    """
    sample_text = "\n\n---\n\n".join(email_samples[:20])  # cap at 20 to avoid token overflow

    prompt = f"""You are analyzing someone's personal email writing style to help an AI assistant replicate it.

Below are {len(email_samples[:20])} emails this person actually wrote and sent.

EMAILS:
{sample_text}

Analyze these and return a JSON object with exactly these keys:

{{
  "tone": "describe overall tone in 1-2 sentences (e.g. casual but professional, warm, direct)",
  "avg_length": "short | medium | long",
  "greeting_style": "how they typically open emails",
  "sign_off_style": "how they typically end/sign emails",
  "punctuation_habits": "observations about comma use, em-dashes, ellipses, etc.",
  "uses_emoji": true or false,
  "uses_bullet_points": true or false,
  "vocabulary_level": "simple | intermediate | advanced",
  "common_phrases": ["list", "of", "up to 8 phrases or words they use often"],
  "things_to_avoid": ["patterns", "that are NOT in their style"],
  "example_opening_lines": ["2-3 example opening lines in their style"],
  "system_prompt_snippet": "A 3-4 sentence instruction block (starting with 'Write in a style that...') that captures their voice for use in AI prompts."
}}

Return only valid JSON. No explanation, no markdown.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"system_prompt_snippet": "Write in a clear, direct, natural tone.", "error": "parse_failed"}


# ──────────────────────────────────────────────
# SAVE / LOAD PROFILE
# ──────────────────────────────────────────────

def save_style_profile(profile: dict, sample_count: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM style_profile")  # single-row table
    c.execute("""
        INSERT INTO style_profile (profile_json, sample_count, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (json.dumps(profile), sample_count))
    conn.commit()
    conn.close()


def load_style_profile() -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM style_profile ORDER BY updated_at DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row["profile_json"])
    return None


def get_style_prompt() -> str:
    """
    Returns the system-prompt snippet to inject into generation calls.
    Falls back to a sensible default if profile hasn't been built yet.
    """
    profile = load_style_profile()
    if profile:
        return profile.get(
            "system_prompt_snippet",
            "Write in a clear, direct, and natural tone that sounds human."
        )
    return "Write in a clear, direct, and natural tone that sounds human."


def save_sent_sample(gmail_id: str, body: str, to_email: str, subject: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO sent_samples (gmail_id, body, to_email, subject)
        VALUES (?, ?, ?, ?)
    """, (gmail_id, body, to_email, subject))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# MAIN: BUILD PROFILE
# ──────────────────────────────────────────────

def build_style_profile(service, max_samples: int = 50):
    """
    Full pipeline: fetch sent → analyze → save.
    Call this once on onboarding and periodically to keep it fresh.
    """
    print(f"📥 Fetching up to {max_samples} sent emails...")
    sent = fetch_sent_emails(service, max_results=max_samples)
    print(f"   Found {len(sent)} valid samples")

    if not sent:
        print("⚠ No sent emails found. Style profile not built.")
        return None

    # Persist samples for future re-analysis
    for s in sent:
        save_sent_sample(s["gmail_id"], s["body"], s["to"], s["subject"])

    bodies = [s["body"] for s in sent]
    print("🧠 Analyzing writing style...")
    profile = analyze_style(bodies)

    save_style_profile(profile, sample_count=len(sent))
    print(f"✔ Style profile saved ({len(sent)} samples)")
    print(f"\n📝 Your voice:\n{profile.get('system_prompt_snippet', '')}\n")
    return profile


if __name__ == "__main__":
    init_style_table()
    from gmail_utils import get_gmail_service
    service = get_gmail_service()
    build_style_profile(service)
