import sqlite3
import json
from datetime import datetime
from typing import Optional

DB_PATH = "memory.db"


# ──────────────────────────────────────────────
# CONNECTION
# ──────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────
# SCHEMA INIT
# ──────────────────────────────────────────────

def init_campaign_tables():
    conn = get_conn()
    c = conn.cursor()

    # Campaigns
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            goal            TEXT,
            status          TEXT DEFAULT 'active',   -- active | paused | completed
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Per-contact state within a campaign
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaign_contacts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL,
            contact_email   TEXT NOT NULL,
            sequence_step   INTEGER DEFAULT 0,        -- which follow-up step
            status          TEXT DEFAULT 'pending',   -- pending | sent | replied | bounced | opted_out
            last_sent_at    TEXT,
            replied_at      TEXT,
            reply_gmail_id  TEXT,                     -- gmail_id of the reply email
            notes           TEXT,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
            UNIQUE(campaign_id, contact_email)
        )
    """)

    # Deal / partnership pipeline
    c.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_email   TEXT NOT NULL,
            company         TEXT,
            title           TEXT,                     -- e.g. "Sponsored video: Brand X"
            stage           TEXT DEFAULT 'prospecting',
            -- stages: prospecting → outreach_sent → in_discussion → negotiation → closed_won | closed_lost
            deal_value      REAL,                     -- estimated $ value
            currency        TEXT DEFAULT 'USD',
            notes           TEXT,
            thread_ids      TEXT DEFAULT '[]',        -- JSON list of gmail thread_ids
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("✔ Campaign + deal tables initialized")


# ──────────────────────────────────────────────
# CAMPAIGNS
# ──────────────────────────────────────────────

def create_campaign(name: str, goal: str = "") -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO campaigns (name, goal) VALUES (?, ?)",
        (name, goal)
    )
    campaign_id = c.lastrowid
    conn.commit()
    conn.close()
    return campaign_id


def get_campaign(campaign_id: int) -> Optional[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def list_campaigns(status: str = None) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if status:
        c.execute("SELECT * FROM campaigns WHERE status = ? ORDER BY created_at DESC", (status,))
    else:
        c.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_campaign_status(campaign_id: int, status: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE campaigns SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, campaign_id)
    )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# CAMPAIGN CONTACTS
# ──────────────────────────────────────────────

def add_contact_to_campaign(campaign_id: int, contact_email: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO campaign_contacts (campaign_id, contact_email)
        VALUES (?, ?)
    """, (campaign_id, contact_email))
    conn.commit()
    conn.close()


def mark_email_sent(campaign_id: int, contact_email: str, step: int = 0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE campaign_contacts
        SET status = 'sent',
            sequence_step = ?,
            last_sent_at = CURRENT_TIMESTAMP
        WHERE campaign_id = ? AND contact_email = ?
    """, (step, campaign_id, contact_email))
    conn.commit()
    conn.close()


def mark_replied(campaign_id: int, contact_email: str, reply_gmail_id: str):
    """Call this when we detect an inbound reply that matches a campaign contact."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE campaign_contacts
        SET status = 'replied',
            replied_at = CURRENT_TIMESTAMP,
            reply_gmail_id = ?
        WHERE campaign_id = ? AND contact_email = ?
    """, (reply_gmail_id, campaign_id, contact_email))
    conn.commit()
    conn.close()


def get_campaign_contacts(campaign_id: int, status: str = None) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if status:
        c.execute("""
            SELECT * FROM campaign_contacts
            WHERE campaign_id = ? AND status = ?
        """, (campaign_id, status))
    else:
        c.execute("SELECT * FROM campaign_contacts WHERE campaign_id = ?", (campaign_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_campaign_stats(campaign_id: int) -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'sent'    THEN 1 ELSE 0 END) as sent,
            SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN status = 'bounced' THEN 1 ELSE 0 END) as bounced
        FROM campaign_contacts
        WHERE campaign_id = ?
    """, (campaign_id,))
    row = c.fetchone()
    conn.close()
    d = dict(row)
    total = d["total"] or 1
    d["reply_rate"] = round((d["replied"] or 0) / total * 100, 1)
    return d


# ──────────────────────────────────────────────
# REPLY DETECTION
# ──────────────────────────────────────────────

def check_if_campaign_reply(sender_email: str, gmail_id: str) -> Optional[dict]:
    """
    When a new inbound email arrives, check if this sender is in any active
    campaign as 'sent'. If yes, mark them replied and return the campaign info.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT cc.*, cam.name as campaign_name
        FROM campaign_contacts cc
        JOIN campaigns cam ON cam.id = cc.campaign_id
        WHERE cc.contact_email LIKE ?
          AND cc.status = 'sent'
          AND cam.status = 'active'
        LIMIT 1
    """, (f"%{sender_email}%",))
    row = c.fetchone()
    conn.close()

    if row:
        row_dict = dict(row)
        mark_replied(row_dict["campaign_id"], row_dict["contact_email"], gmail_id)
        return row_dict
    return None


# ──────────────────────────────────────────────
# DEALS
# ──────────────────────────────────────────────

DEAL_STAGES = [
    "prospecting",
    "outreach_sent",
    "in_discussion",
    "negotiation",
    "closed_won",
    "closed_lost"
]


def create_deal(
    contact_email: str,
    title: str,
    company: str = "",
    deal_value: float = None,
    notes: str = ""
) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO deals (contact_email, title, company, deal_value, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (contact_email, title, company, deal_value, notes))
    deal_id = c.lastrowid
    conn.commit()
    conn.close()
    return deal_id


def advance_deal_stage(deal_id: int, new_stage: str):
    if new_stage not in DEAL_STAGES:
        raise ValueError(f"Invalid stage. Choose from: {DEAL_STAGES}")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE deals
        SET stage = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_stage, deal_id))
    conn.commit()
    conn.close()


def attach_thread_to_deal(deal_id: int, thread_id: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT thread_ids FROM deals WHERE id = ?", (deal_id,))
    row = c.fetchone()
    if row:
        threads = json.loads(row["thread_ids"])
        if thread_id not in threads:
            threads.append(thread_id)
        c.execute(
            "UPDATE deals SET thread_ids = ? WHERE id = ?",
            (json.dumps(threads), deal_id)
        )
    conn.commit()
    conn.close()


def get_deals(stage: str = None) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if stage:
        c.execute("SELECT * FROM deals WHERE stage = ? ORDER BY updated_at DESC", (stage,))
    else:
        c.execute("SELECT * FROM deals ORDER BY updated_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_deal_by_contact(contact_email: str) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM deals WHERE contact_email LIKE ? ORDER BY updated_at DESC",
        (f"%{contact_email}%",)
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_summary() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT stage, COUNT(*) as count, SUM(deal_value) as total_value
        FROM deals
        GROUP BY stage
    """)
    rows = c.fetchall()
    conn.close()
    return {r["stage"]: {"count": r["count"], "total_value": r["total_value"] or 0} for r in rows}


if __name__ == "__main__":
    init_campaign_tables()
