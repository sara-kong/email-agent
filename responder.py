from openai import OpenAI

client = OpenAI()


def generate_reply(email_text, thread_summary, memory_context):

    prompt = f"""
You are an intelligent email assistant.

You are replying inside an ongoing conversation.

THREAD CONTEXT:
{thread_summary}

LONG-TERM RELATIONSHIP MEMORY:
{memory_context}

NEW EMAIL:
{email_text}

Write a professional, context-aware reply.

Requirements:
- acknowledge previous discussion
- avoid repeating prior points
- continue conversation naturally
- be concise
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
