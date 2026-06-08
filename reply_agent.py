from ai_utils import client

def generate_reply(email_text):

    prompt = f"""
You are a professional email assistant.

Write a concise and thoughtful email reply.

Email:
{email_text}
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
