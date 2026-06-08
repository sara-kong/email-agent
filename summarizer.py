from openai import OpenAI

client = OpenAI()


def summarize_thread(existing_summary, new_email):

    prompt = f"""
You are maintaining memory for an email assistant.

Below is the EXISTING thread summary:

{existing_summary}

Below is the NEW email:

{new_email}

Update the thread summary concisely.

Keep:
- important context
- decisions
- people
- meeting details
- action items

Return ONLY the updated summary.
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
