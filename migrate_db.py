import sqlite3

DB_PATH = "memory.db"


def run_migrations():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("Running migrations...")

    # ── Ensure base emails table exists (from original code) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id    TEXT UNIQUE,
            thread_id   TEXT,
            sender      TEXT,
            subject     TEXT,
            snippet     TEXT,
            full_text   TEXT,
            embedding   TEXT,
            category    TEXT,
            action      TEXT,
            importance  TEXT,
            summary     TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Senders (from original) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS senders (
            sender          TEXT PRIMARY KEY,
            email_count     INTEGER DEFAULT 0,
            important_count INTEGER DEFAULT 0,
            last_seen       TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Thread summaries (from original) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS thread_summaries (
            thread_id   TEXT PRIMARY KEY,
            summary     TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Campaigns ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            goal        TEXT,
            status      TEXT DEFAULT 'active',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Campaign contacts ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaign_contacts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL,
            contact_email   TEXT NOT NULL,
            sequence_step   INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'pending',
            last_sent_at    TEXT,
            replied_at      TEXT,
            reply_gmail_id  TEXT,
            notes           TEXT,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
            UNIQUE(campaign_id, contact_email)
        )
    """)

    # ── Deals ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_email   TEXT NOT NULL,
            company         TEXT,
            title           TEXT,
            stage           TEXT DEFAULT 'prospecting',
            deal_value      REAL,
            currency        TEXT DEFAULT 'USD',
            notes           TEXT,
            thread_ids      TEXT DEFAULT '[]',
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Contact profiles ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS contact_profiles (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            email               TEXT UNIQUE NOT NULL,
            name                TEXT DEFAULT '',
            company             TEXT DEFAULT '',
            role                TEXT DEFAULT '',
            contact_type        TEXT DEFAULT 'unknown',
            emails_received     INTEGER DEFAULT 0,
            emails_sent         INTEGER DEFAULT 0,
            threads_shared      INTEGER DEFAULT 0,
            first_contact_date  TEXT,
            last_contact_date   TEXT,
            relationship_score  REAL DEFAULT 0.0,
            is_vip              INTEGER DEFAULT 0,
            vip_reason          TEXT DEFAULT '',
            ai_summary          TEXT DEFAULT '',
            tags                TEXT DEFAULT '[]',
            notes               TEXT DEFAULT '',
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Style profile ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS style_profile (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_json TEXT NOT NULL,
            sample_count INTEGER DEFAULT 0,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Sent samples ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id    TEXT UNIQUE,
            body        TEXT,
            to_email    TEXT,
            subject     TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Threads (from original) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_thread_id     TEXT UNIQUE,
            subject             TEXT,
            participants        TEXT,
            message_count       INTEGER DEFAULT 0,
            last_message_snippet TEXT,
            last_updated        TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Contacts (original table — keep for backward compat) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            email               TEXT UNIQUE,
            emails_sent         INTEGER DEFAULT 0,
            emails_received     INTEGER DEFAULT 0,
            relationship_score  REAL DEFAULT 0,
            last_contact_date   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("✔ All migrations complete")


if __name__ == "__main__":
    run_migrations()
