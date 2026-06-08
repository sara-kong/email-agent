async function getContacts() {
  const res = await fetch(
    "http://127.0.0.1:8000/contacts",
    {
      cache: "no-store"
    }
  );

  return res.json();
}

export default async function ContactsPage() {
  const contacts = await getContacts();

  return (
    <main className="p-10">
      <h1 className="text-3xl font-bold mb-6">
        Contacts
      </h1>

      <div className="space-y-4">
        {contacts.map((contact: any) => (
          <div
            key={contact[0]}
            className="border rounded p-4"
          >
            <div>
              <strong>Name:</strong> {contact[1]}
            </div>

            <div>
              <strong>Email:</strong> {contact[2]}
            </div>

            <div>
              <strong>Company:</strong> {contact[3]}
            </div>

            <div>
              <strong>Notes:</strong> {contact[5]}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
