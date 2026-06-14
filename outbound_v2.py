from openai import OpenAI

client = OpenAI()


def _build_examples_block(user_id) -> str:
    try:
        from style_profiler import get_example_emails
        examples = get_example_emails(user_id)
    except Exception:
        examples = []

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


def generate_outreach_email(user_id, contact: tuple, campaign_prompt: str, style_prompt: str = "") -> str:
    """
    contact: (id, name, email, company, role, notes_or_summary)
    """
    _, name, email, company, role, notes = contact

    if not style_prompt:
        # Fallback: try to load from style_profiler
        try:
            from style_profiler import get_style_prompt
            style_prompt = get_style_prompt(user_id)
        except Exception:
            style_prompt = "Write in a clear, direct, natural tone."

    examples_block = _build_examples_block(user_id)

    prompt = f"""You are writing a highly personalized outbound email on behalf of a creator/freelancer.

CAMPAIGN INSTRUCTIONS:
{campaign_prompt}

RECIPIENT:
Name: {name or email}
Email: {email}
Company: {company or "Unknown"}
Role: {role or "Unknown"}
Notes / Context: {notes or "No additional context"}

WRITING STYLE (match this voice exactly):
{style_prompt}
{examples_block}
Write:
- Concise, specific email (no generic templates)
- Natural tone that sounds like the sender, not AI, and consistent with the examples above
- Reference something specific about the recipient if possible
- Clear ask or next step at the end
- Subject line on the first line formatted as: Subject: [subject here]
- Then a blank line
- Then the email body

Do not write "Dear" or use formal language unless that fits the style.
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


def run_outbound_demo(user_id):
    from contact_intelligence import get_top_contacts

    contacts_data = get_top_contacts(user_id, limit=5)
    campaign_prompt = input("\nDescribe the outreach campaign:\n\n")

    try:
        from style_profiler import get_style_prompt
        style_prompt = get_style_prompt(user_id)
    except Exception:
        style_prompt = ""

    print(f"\nFound {len(contacts_data)} contacts\n")
    for c in contacts_data:
        contact_tuple = (
            c.get("id"), c.get("name", ""), c.get("email"),
            c.get("company", ""), c.get("role", ""), c.get("ai_summary", "")
        )
        email = generate_outreach_email(user_id, contact_tuple, campaign_prompt, style_prompt)
        print("\n================ OUTBOUND EMAIL ================\n")
        print(email)
        print("\n================================================\n")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    run_outbound_demo(os.getenv("DEMO_USER_ID"))
