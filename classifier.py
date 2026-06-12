import json
import re
from openai import OpenAI
from corrections import get_high_confidence_pattern, get_relevant_corrections

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


def classify_email(email_text, sender=None, embedding=None):

    # 1. Sender-pattern short-circuit: if this sender's domain has been
    #    corrected to the same category enough times, trust it and skip GPT.
    if sender:
        pattern = get_high_confidence_pattern(sender)
        if pattern:
            category = pattern["typical_category"]
            defaults = PATTERN_DEFAULTS.get(category, PATTERN_DEFAULTS["unknown"])
            return {
                "label": category,
                "importance_score": defaults["importance_score"],
                "sender_trust": defaults["sender_trust"],
                "reason": (
                    f"Learned pattern: emails from this sender have been "
                    f"corrected to '{category}' {pattern['correction_count']} times"
                ),
                "suggested_action": pattern["typical_action"],
            }

    # 2. Few-shot examples from past corrections (falls back to [] if none exist)
    examples = get_relevant_corrections(sender=sender, embedding=embedding)

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
        return json.loads(cleaned)

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
