import json
import re
from typing import Optional
from openai import OpenAI
from psycopg2.extras import Json

from db import db_cursor

client = OpenAI()


# ──────────────────────────────────────────────
# SCHEMA
# ──────────────────────────────────────────────

def init_style_table():
    """No-op — tables are created by supabase/schema.sql."""
    pass


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
# EXAMPLE EMAILS (raw few-shot samples)
# ──────────────────────────────────────────────

# How many raw sent emails to store/inject as few-shot examples.
EXAMPLE_EMAIL_COUNT = 5

def anonymize_recipient_name(body: str, to_header: str) -> str:
    """Replace the recipient's first name (from the 'To' header display name,
    if present) with '[Name]' wherever it appears in the body."""
    match = re.match(r'^\s*"?([^"<]+?)"?\s*<', to_header or "")
    if not match:
        return body

    full_name = match.group(1).strip()
    if not full_name:
        return body

    first_name = full_name.split()[0]
    if len(first_name) <= 1:
        return body

    return re.sub(r'\b' + re.escape(first_name) + r'\b', '[Name]', body, flags=re.IGNORECASE)


def select_example_emails(sent: list[dict], limit: int = EXAMPLE_EMAIL_COUNT) -> list[dict]:
    """
    Pick a handful of representative sent emails to use as raw few-shot
    examples, anonymizing the recipient's name in each.
    """
    candidates = [s for s in sent if 80 <= len(s.get("body", "")) <= 2000]
    candidates.sort(key=lambda s: len(s["body"]), reverse=True)

    examples = []
    for s in candidates[:limit]:
        examples.append({
            "subject": s.get("subject", ""),
            "body": anonymize_recipient_name(s["body"], s.get("to", s.get("to_email", ""))),
        })
    return examples


# ──────────────────────────────────────────────
# SAVE / LOAD PROFILE
# ──────────────────────────────────────────────

def save_style_profile(user_id: str, profile: dict, sample_count: int, example_emails: Optional[list] = None):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM style_profile WHERE user_id = %s", (user_id,))
        cur.execute("""
            INSERT INTO style_profile (user_id, profile_json, sample_count, example_emails, updated_at)
            VALUES (%s, %s, %s, %s, now())
        """, (user_id, Json(profile), sample_count, Json(example_emails or [])))


def get_example_emails(user_id: str, limit: int = EXAMPLE_EMAIL_COUNT) -> list[dict]:
    """Return raw example sent emails [{subject, body}, ...] for few-shot prompts."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT example_emails FROM style_profile WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        )
        row = cur.fetchone()

    if not row or not row[0]:
        return []

    return row[0][:limit]


def load_style_profile(user_id: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT profile_json FROM style_profile WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def get_style_prompt(user_id: str) -> str:
    """
    Returns the system-prompt snippet to inject into generation calls.
    Falls back to a sensible default if profile hasn't been built yet.
    """
    profile = load_style_profile(user_id)
    if profile:
        return profile.get(
            "system_prompt_snippet",
            "Write in a clear, direct, and natural tone that sounds human."
        )
    return "Write in a clear, direct, and natural tone that sounds human."


def save_sent_sample(user_id: str, gmail_id: str, body: str, to_email: str, subject: str):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO sent_samples (user_id, gmail_id, body, to_email, subject)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, gmail_id) DO NOTHING
        """, (user_id, gmail_id, body, to_email, subject))


# ──────────────────────────────────────────────
# MAIN: BUILD PROFILE
# ──────────────────────────────────────────────

def build_style_profile(user_id: str, service, max_samples: int = 50):
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
        save_sent_sample(user_id, s["gmail_id"], s["body"], s["to"], s["subject"])

    bodies = [s["body"] for s in sent]
    print("🧠 Analyzing writing style...")
    profile = analyze_style(bodies)

    examples = select_example_emails(sent)
    save_style_profile(user_id, profile, sample_count=len(sent), example_emails=examples)
    print(f"✔ Style profile saved ({len(sent)} samples, {len(examples)} few-shot examples)")
    print(f"\n📝 Your voice:\n{profile.get('system_prompt_snippet', '')}\n")
    return profile


def rebuild_example_emails_from_samples(user_id: str, limit: int = EXAMPLE_EMAIL_COUNT) -> list[dict]:
    """
    Re-select few-shot example emails from already-fetched sent_samples,
    without hitting the Gmail API. Preserves the existing style profile
    and sample_count, only refreshing example_emails.
    """
    with db_cursor(dict_rows=True) as cur:
        cur.execute("SELECT body, to_email, subject FROM sent_samples WHERE user_id = %s", (user_id,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT profile_json, sample_count FROM style_profile WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        )
        profile_row = cur.fetchone()

    sent = [{"body": r["body"], "to": r["to_email"], "subject": r["subject"]} for r in rows]
    examples = select_example_emails(sent, limit=limit)

    profile = profile_row["profile_json"] if profile_row else {}
    sample_count = profile_row["sample_count"] if profile_row else len(sent)

    save_style_profile(user_id, profile, sample_count=sample_count, example_emails=examples)
    return examples
