import json
from openai import OpenAI

client = OpenAI()


def classify_email(email_text):

    prompt = """
You are an inbox intelligence system.

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

    try:
        return json.loads(content)

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
