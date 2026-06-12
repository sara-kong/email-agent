from openai import OpenAI
client = OpenAI()


def generate_reply(email_text, thread_summary, memory_context, style_prompt=""):
    if not style_prompt:
        style_prompt = "Write in a clear, direct, and natural tone."

    prompt = f"""
You are an intelligent email assistant replying on behalf of the user.
You are replying inside an ongoing conversation.

WRITING STYLE (match this voice exactly):
{style_prompt}

THREAD CONTEXT:
{thread_summary}

LONG-TERM RELATIONSHIP MEMORY:
{memory_context}

NEW EMAIL:
{email_text}

Write a reply in the user's own voice, as described above.
Requirements:
- acknowledge previous discussion if relevant
- avoid repeating prior points
- continue conversation naturally
- be concise
- match the tone, greeting style, and sign-off described in the writing style
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
    return response.choices[0].message.content
