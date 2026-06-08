from outbound import generate_outreach_email


def collect_contacts():

    contacts = []

    print("\nPaste contacts.")
    print("Format:")
    print("Name, email, notes")
    print("Type DONE when finished.\n")

    while True:

        line = input()

        if line.strip().upper() == "DONE":
            break

        try:

            parts = line.split(",", 2)

            name = parts[0].strip()
            email = parts[1].strip()

            notes = ""

            if len(parts) > 2:
                notes = parts[2].strip()

            contact = (
                None,       # id placeholder
                name,
                email,
                "",         # company
                "",         # role
                notes
            )

            contacts.append(contact)

        except:

            print("Invalid format. Use: Name,email")

    return contacts


def main():

    contacts = collect_contacts()

    campaign_prompt = input(
        "\nDescribe the campaign:\n\n"
    )

    for contact in contacts:

        email = generate_outreach_email(
            contact,
            campaign_prompt
        )

        print("\n====================================")
        print(f"TO: {contact[2]}")
        print("====================================\n")

        print(email)

        print("\n====================================\n")


if __name__ == "__main__":

    main()
