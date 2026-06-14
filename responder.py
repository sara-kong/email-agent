from openai import OpenAI
from style_profiler import get_example_emails

client = OpenAI()


def _build_examples_block(user_id) -> str:
    examples = get_example_emails(user_id)
    if not examples:
        return ""

    examples_text = "\n\n---\n\n".join(
        f"Subject: {ex.get('subject', '')}\n{ex.get('body', '')}"
        for ex in examples
    )
    return f"""
HERE ARE EXAMPLES OF EMAILS I'VE ACTUALLY WRITTEN — match this exact voice:
{examples_text}
"""


def generate_reply(user_id, email_text, thread_summary, memory_context, style_prompt=""):
    if not style_prompt:
        style_prompt = "Write in a clear, direct, and natural tone."

    examples_block = _build_examples_block(user_id)

    prompt = f"""
You are an intelligent email assistant replying on behalf of the user.
You are replying inside an ongoing conversation.

WRITING STYLE (match this voice exactly):
{style_prompt}
{examples_block}
THREAD CONTEXT:
{thread_summary}

LONG-TERM RELATIONSHIP MEMORY:
{memory_context}

NEW EMAIL:
{email_text}

Write a reply in the user's own voice, as described above and demonstrated in the examples.
Requirements:
- acknowledge previous discussion if relevant
- avoid repeating prior points
- continue conversation naturally
- be concise
- match the tone, greeting style, and sign-off described in the writing style and shown in the examples
"""
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )
    return response.choices[0].message.content
