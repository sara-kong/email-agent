import sqlite3
import json

DB_PATH = "memory.db"


# ==============================
# DB CONNECTION
# ==============================
def get_conn():
    return sqlite3.connect(DB_PATH)

def init_threads_table():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_thread_id TEXT UNIQUE,
        subject TEXT,
        participants TEXT,
        message_count INTEGER DEFAULT 0,
        last_message_snippet TEXT,
        last_updated TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def init_contacts_table():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        emails_sent INTEGER DEFAULT 0,
        emails_received INTEGER DEFAULT 0,
        relationship_score REAL DEFAULT 0,
        last_contact_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# ==============================
# SAVE EMAIL
# ==============================
def save_email(
    gmail_id,
    thread_id,
    sender,
    subject,
    snippet,
    email_text,
    embedding_json,
    label,
    action,
    score,
    summary
):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO emails (
            gmail_id,
            thread_id,
            sender,
            subject,
            snippet,
            full_text,
            embedding,
            category,
            action,
            importance,
            summary
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        gmail_id,
        thread_id,
        sender,
        subject,
        snippet,
        email_text,
        embedding_json,
        label,
        action,
        score,
        summary
    ))

    conn.commit()
    conn.close()


# ==============================
# DEDUP CHECK
# ==============================
def email_exists(gmail_id):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 1 FROM emails WHERE gmail_id = ?
    """, (gmail_id,))

    result = cursor.fetchone()
    conn.close()

    return result is not None


# ==============================
# GET ALL CONTACT-LIKE DATA
# ==============================
def get_all_contacts():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sender, COUNT(*) as freq
        FROM emails
        GROUP BY sender
        ORDER BY freq DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return rows


# ==============================
# GET THREAD (CRITICAL FOR YOUR OS)
# ==============================
def get_thread(thread_id):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sender, subject, snippet, full_text
        FROM emails
        WHERE thread_id = ?
        ORDER BY id ASC
    """, (thread_id,))

    rows = cursor.fetchall()
    conn.close()

    return rows


# ==============================
# BASIC SEMANTIC SEARCH (SAFE VERSION)
# ==============================
def semantic_search(embedding, limit=5):
    """
    NOTE: assumes embeddings are stored as JSON lists
    """

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT full_text, embedding
        FROM emails
    """)

    rows = cursor.fetchall()
    conn.close()

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b + 1e-8)

    scored = []

    for text, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            score = cosine(embedding, emb)
            scored.append((score, text))
        except:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])

    return [x[1] for x in scored[:limit]]


# ==============================
# THREAD-BASED MEMORY SEARCH (KEY UPGRADE)
# ==============================
def semantic_search_thread(thread_id, embedding, limit=3):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT full_text, embedding
        FROM emails
        WHERE thread_id = ?
    """, (thread_id,))

    rows = cursor.fetchall()
    conn.close()

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b + 1e-8)

    scored = []

    for text, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            score = cosine(embedding, emb)
            scored.append((score, text))
        except:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])

    return [x[1] for x in scored[:limit]]

def upsert_contact(email, received=True):
    conn = get_conn()
    cursor = conn.cursor()

    if received:
        cursor.execute("""
        INSERT INTO contacts (email, emails_received, last_contact_date)
        VALUES (?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(email)
        DO UPDATE SET
            emails_received = emails_received + 1,
            last_contact_date = CURRENT_TIMESTAMP
        """, (email,))
    else:
        cursor.execute("""
        INSERT INTO contacts (email, emails_sent, last_contact_date)
        VALUES (?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(email)
        DO UPDATE SET
            emails_sent = emails_sent + 1,
            last_contact_date = CURRENT_TIMESTAMP
        """, (email,))

    conn.commit()
    conn.close()

def upsert_thread(thread_id, subject, sender, snippet):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO threads (
        gmail_thread_id,
        subject,
        participants,
        message_count,
        last_message_snippet
    )
    VALUES (?, ?, ?, 1, ?)
    ON CONFLICT(gmail_thread_id)
    DO UPDATE SET
        message_count = message_count + 1,
        last_message_snippet = ?,
        last_updated = CURRENT_TIMESTAMP
    """, (
        thread_id,
        subject,
        sender,
        snippet,
        snippet
    ))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_threads_table()
    init_contacts_table()
    print("DB initialized")
def get_thread_summary(thread_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS thread_summaries (
            thread_id TEXT PRIMARY KEY,
            summary TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("SELECT summary FROM thread_summaries WHERE thread_id = ?", (thread_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def save_thread_summary(thread_id, summary):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS thread_summaries (
            thread_id TEXT PRIMARY KEY,
            summary TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO thread_summaries (thread_id, summary)
        VALUES (?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            summary = ?,
            updated_at = CURRENT_TIMESTAMP
    """, (thread_id, summary, summary))
    conn.commit()
    conn.close()

def update_sender(sender, is_important):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS senders (
            sender TEXT PRIMARY KEY,
            email_count INTEGER DEFAULT 0,
            important_count INTEGER DEFAULT 0,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO senders (sender, email_count, important_count)
        VALUES (?, 1, ?)
        ON CONFLICT(sender) DO UPDATE SET
            email_count = email_count + 1,
            important_count = important_count + CASE WHEN ? THEN 1 ELSE 0 END,
            last_seen = CURRENT_TIMESTAMP
    """, (sender, 1 if is_important else 0, is_important))
    conn.commit()
    conn.close()

def get_recent_emails_from_sender(sender, limit=5):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT full_text FROM emails
        WHERE sender LIKE ?
        ORDER BY id DESC LIMIT ?
    """, (f"%{sender}%", limit))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]