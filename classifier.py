import json
import os
import re
from openai import OpenAI
from dotenv import load_dotenv
from corrections import get_high_confidence_pattern, get_relevant_corrections

load_dotenv()

client = OpenAI()

# Default scoring applied when a high-confidence sender pattern short-circuits
# the GPT call entirely.
PATTERN_DEFAULTS = {
    "important": {"importance_score": 60, "sender_trust": "high"},
    "marketing": {"importance_score": 5, "sender_trust": "low"},
    "spam": {"importance_score": 0, "sender_trust": "low"},
    "social": {"importance_score": 15, "sender_trust": "medium"},
    "unknown": {"importance_score": 0, "sender_trust": "low"},
}

# How much of each example email to show in the few-shot prompt.
EXAMPLE_SNIPPET_CHARS = 600

# The inbox owner's own address — never "reply" to an email that's a copy of
# something the user themselves sent.
USER_EMAIL = os.getenv("USER_EMAIL", "").lower()

# Senders matching this are automated/no-reply systems (notifications,
# invitations, calendar confirmations, surveys, mailers, etc.) — these should
# never be classified as "reply", regardless of what the model says.
AUTOMATED_SENDER_PATTERN = re.compile(
    r"no-?reply|do-?not-?reply|notifications?@|invitations?@|alerts?@|"
    r"calendar@|calendar-server|automated|mailer|updates?@|news(letter)?@",
    re.IGNORECASE,
)


def _apply_action_safeguards(result: dict, sender: str | None) -> dict:
    """
    Deterministic backstop on top of the model's `suggested_action`: emails
    from the user's own address or from automated/no-reply senders should
    never be marked "reply" (and therefore never trigger an auto-draft),
    even if the model gets it wrong.
    """
    if result.get("suggested_action") != "reply" or not sender:
        return result

    sender_lower = sender.lower()

    if USER_EMAIL and USER_EMAIL in sender_lower:
        result["suggested_action"] = "archive"
        result["reason"] = (
            (result.get("reason", "") + " ").strip()
            + " [auto: sender is the user's own address — no reply needed]"
        ).strip()
    elif AUTOMATED_SENDER_PATTERN.search(sender_lower):
        result["suggested_action"] = "archive"
        result["reason"] = (
            (result.get("reason", "") + " ").strip()
            + " [auto: automated/no-reply sender — no reply needed]"
        ).strip()

    return result


def classify_email(user_id, email_text, sender=None, embedding=None):

    # 1. Sender-pattern short-circuit: if this sender's domain has been
    #    corrected to the same category enough times, trust it and skip GPT.
    if sender:
        pattern = get_high_confidence_pattern(user_id, sender)
        if pattern:
            category = pattern["typical_category"]
            defaults = PATTERN_DEFAULTS.get(category, PATTERN_DEFAULTS["unknown"])
            return _apply_action_safeguards({
                "label": category,
                "importance_score": defaults["importance_score"],
                "sender_trust": defaults["sender_trust"],
                "reason": (
                    f"Learned pattern: emails from this sender have been "
                    f"corrected to '{category}' {pattern['correction_count']} times"
                ),
                "suggested_action": pattern["typical_action"],
            }, sender)

    # 2. Few-shot examples from past corrections (falls back to [] if none exist)
    examples = get_relevant_corrections(user_id, sender=sender, embedding=embedding)

    few_shot_block = ""
    if examples:
        examples_text = "\n\n".join(
            f"EMAIL:\n{(ex['email_text'] or '')[:EXAMPLE_SNIPPET_CHARS]}\n"
            f"→ category: {ex['corrected_category']}, action: {ex['corrected_action']}"
            for ex in examples
        )
        few_shot_block = f"""
Here's how the user has classified similar emails before:

{examples_text}

Use these examples to guide your classification, especially for similar senders or email types.
"""

    prompt = """
You are an inbox intelligence system.
""" + few_shot_block + """
Classify this email and return ONLY valid JSON.

EMAIL:
""" + email_text + """

Guidance for suggested_action — be conservative with "reply":

- "reply": ONLY for messages from a real person, written specifically to the
  user, that genuinely expect or invite a personal response (a question, a
  request, an ongoing back-and-forth conversation). A reply draft will be
  auto-generated and saved, so over-using this is costly — when in doubt,
  do NOT use "reply".
- Do NOT use "reply" for:
    - automated notifications, system alerts, or no-reply senders
      (e.g. notifications@, no-reply@, invitations@, calendar confirmations)
    - newsletters, surveys, feedback requests, marketing/promo emails
    - receipts, shipping/delivery updates, registration/event confirmations
    - emails that are just a copy of something the user themselves sent
  These should be "archive", "ignore", or "summarize" instead.
- "summarize": long threads or newsletters worth a digest, but no reply needed.
- "archive": informational, no action needed.
- "ignore": spam or irrelevant.

Return format:

{
  "label": "important | marketing | spam | social | unknown",
  "importance_score": 0,
  "sender_trust": "low | medium | high",
  "reason": "short explanation",
  "suggested_action": "reply | ignore | archive | summarize"
}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    content = response.choices[0].message.content

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return _apply_action_safeguards(json.loads(cleaned), sender)

    except Exception:

        print("⚠ CLASSIFIER JSON ERROR")
        print(content)

        return {
            "label": "unknown",
            "importance_score": 0,
            "sender_trust": "low",
            "reason": "parse failure",
            "suggested_action": "ignore"
        }
