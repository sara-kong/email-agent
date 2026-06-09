import sqlite3
from memory import upsert_contact

conn = sqlite3.connect("memory.db")
cursor = conn.cursor()

cursor.execute("""
SELECT DISTINCT sender
FROM emails
""")

rows = cursor.fetchall()

count = 0

for row in rows:
    sender = row[0]

    if sender:
        upsert_contact(sender, received=True)
        count += 1

print(f"Added {count} contacts")

conn.close()
