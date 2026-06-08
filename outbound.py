from openai import OpenAI

from memory import get_all_contacts

client = OpenAI()

with open("style_examples.txt", "r") as f:

    STYLE_EXAMPLES = f.read()

def generate_outreach_email(contact, campaign_prompt):

    name = contact[1]
    email = contact[2]
    company = contact[3]
    role = contact[4]
    notes = contact[5]

    prompt = f"""
You are writing a highly personalized outbound email.

CAMPAIGN INSTRUCTIONS:
{campaign_prompt}

RECIPIENT:
Name: {name}
Email: {email}
Company: {company}
Role: {role}
Notes: {notes}

CONTACT CONTEXT:
{notes}

WRITING STYLE EXAMPLES:
{STYLE_EXAMPLES}

Write:
- concise email
- natural tone
- specific to the person
- no generic templates
- human sounding
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


def run_outbound_demo():

    contacts = get_all_contacts()

    campaign_prompt = input(
    "\nDescribe the outreach campaign:\n\n"
)

    print(f"\nFound {len(contacts)} contacts\n")

    for contact in contacts[:5]:

        email = generate_outreach_email(contact, campaign_prompt)

        print("\n================ OUTBOUND EMAIL ================\n")
        print(email)
        print("\n================================================\n")


if __name__ == "__main__":
    run_outbound_demo()
