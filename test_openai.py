from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_email_reply(email_text):
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You write concise, natural email replies. Avoid sounding like AI."
            },
            {
                "role": "user",
                "content": f"Write a reply to this email:\n\n{email_text}"
            }
        ]
    )

    return response.choices[0].message.content


# 👇 THIS is where you test Step 2
email = "Can you meet tomorrow at 3pm to discuss the project?"
print(generate_email_reply(email))
