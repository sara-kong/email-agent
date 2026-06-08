import sqlite3
import json

DB_PATH = "memory.db"


# ==============================
# DB CONNECTION
# ==============================
def get_conn():
    return sqlite3.connect(DB_PATH)


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
            email_text,
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
        SELECT sender, subject, snippet, email_text
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
        SELECT email_text, embedding
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
        SELECT email_text, embedding
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
