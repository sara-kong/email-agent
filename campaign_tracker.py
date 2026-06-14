from typing import Optional
from psycopg2.extras import Json

from db import db_cursor


# ──────────────────────────────────────────────
# SCHEMA INIT
# ──────────────────────────────────────────────

def init_campaign_tables():
    """No-op — tables are created by supabase/schema.sql."""
    pass


# ──────────────────────────────────────────────
# CAMPAIGNS
# ──────────────────────────────────────────────

def create_campaign(user_id: str, name: str, goal: str = "") -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO campaigns (user_id, name, goal) VALUES (%s, %s, %s) RETURNING id",
            (user_id, name, goal)
        )
        return cur.fetchone()[0]


def get_campaign(user_id: str, campaign_id: int) -> Optional[dict]:
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM campaigns WHERE user_id = %s AND id = %s",
            (user_id, campaign_id)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_campaigns(user_id: str, status: str = None) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        if status:
            cur.execute(
                "SELECT * FROM campaigns WHERE user_id = %s AND status = %s ORDER BY created_at DESC",
                (user_id, status)
            )
        else:
            cur.execute(
                "SELECT * FROM campaigns WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,)
            )
        return [dict(r) for r in cur.fetchall()]


def update_campaign_status(user_id: str, campaign_id: int, status: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE campaigns SET status = %s, updated_at = now() WHERE user_id = %s AND id = %s",
            (status, user_id, campaign_id)
        )


# ──────────────────────────────────────────────
# CAMPAIGN CONTACTS
# ──────────────────────────────────────────────

def add_contact_to_campaign(user_id: str, campaign_id: int, contact_email: str):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO campaign_contacts (user_id, campaign_id, contact_email)
            VALUES (%s, %s, %s)
            ON CONFLICT (campaign_id, contact_email) DO NOTHING
        """, (user_id, campaign_id, contact_email))


def mark_email_sent(user_id: str, campaign_id: int, contact_email: str, step: int = 0):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE campaign_contacts
            SET status = 'sent',
                sequence_step = %s,
                last_sent_at = now()
            WHERE user_id = %s AND campaign_id = %s AND contact_email = %s
        """, (step, user_id, campaign_id, contact_email))


def mark_replied(user_id: str, campaign_id: int, contact_email: str, reply_gmail_id: str):
    """Call this when we detect an inbound reply that matches a campaign contact."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE campaign_contacts
            SET status = 'replied',
                replied_at = now(),
                reply_gmail_id = %s
            WHERE user_id = %s AND campaign_id = %s AND contact_email = %s
        """, (reply_gmail_id, user_id, campaign_id, contact_email))


def get_campaign_contacts(user_id: str, campaign_id: int, status: str = None) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        if status:
            cur.execute("""
                SELECT * FROM campaign_contacts
                WHERE user_id = %s AND campaign_id = %s AND status = %s
            """, (user_id, campaign_id, status))
        else:
            cur.execute(
                "SELECT * FROM campaign_contacts WHERE user_id = %s AND campaign_id = %s",
                (user_id, campaign_id)
            )
        return [dict(r) for r in cur.fetchall()]


def get_campaign_stats(user_id: str, campaign_id: int) -> dict:
    with db_cursor(dict_rows=True) as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'sent'    THEN 1 ELSE 0 END) as sent,
                SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END) as replied,
                SUM(CASE WHEN status = 'bounced' THEN 1 ELSE 0 END) as bounced
            FROM campaign_contacts
            WHERE user_id = %s AND campaign_id = %s
        """, (user_id, campaign_id))
        row = cur.fetchone()

    d = dict(row)
    total = d["total"] or 1
    d["reply_rate"] = round((d["replied"] or 0) / total * 100, 1)
    return d


# ──────────────────────────────────────────────
# REPLY DETECTION
# ──────────────────────────────────────────────

def check_if_campaign_reply(user_id: str, sender_email: str, gmail_id: str) -> Optional[dict]:
    """
    When a new inbound email arrives, check if this sender is in any active
    campaign as 'sent'. If yes, mark them replied and return the campaign info.
    """
    with db_cursor(dict_rows=True) as cur:
        cur.execute("""
            SELECT cc.*, cam.name as campaign_name
            FROM campaign_contacts cc
            JOIN campaigns cam ON cam.id = cc.campaign_id
            WHERE cc.user_id = %s
              AND cc.contact_email ILIKE %s
              AND cc.status = 'sent'
              AND cam.status = 'active'
            LIMIT 1
        """, (user_id, f"%{sender_email}%"))
        row = cur.fetchone()

    if row:
        row_dict = dict(row)
        mark_replied(user_id, row_dict["campaign_id"], row_dict["contact_email"], gmail_id)
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
    user_id: str,
    contact_email: str,
    title: str,
    company: str = "",
    deal_value: float = None,
    notes: str = ""
) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO deals (user_id, contact_email, title, company, deal_value, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, contact_email, title, company, deal_value, notes))
        return cur.fetchone()[0]


def advance_deal_stage(user_id: str, deal_id: int, new_stage: str):
    if new_stage not in DEAL_STAGES:
        raise ValueError(f"Invalid stage. Choose from: {DEAL_STAGES}")
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE deals
            SET stage = %s, updated_at = now()
            WHERE user_id = %s AND id = %s
        """, (new_stage, user_id, deal_id))


def attach_thread_to_deal(user_id: str, deal_id: int, thread_id: str):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT thread_ids FROM deals WHERE user_id = %s AND id = %s", (user_id, deal_id))
        row = cur.fetchone()
        if row:
            threads = row[0] or []
            if thread_id not in threads:
                threads.append(thread_id)
            cur.execute(
                "UPDATE deals SET thread_ids = %s WHERE user_id = %s AND id = %s",
                (Json(threads), user_id, deal_id)
            )


def get_deals(user_id: str, stage: str = None) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        if stage:
            cur.execute(
                "SELECT * FROM deals WHERE user_id = %s AND stage = %s ORDER BY updated_at DESC",
                (user_id, stage)
            )
        else:
            cur.execute(
                "SELECT * FROM deals WHERE user_id = %s ORDER BY updated_at DESC",
                (user_id,)
            )
        return [dict(r) for r in cur.fetchall()]


def get_deal_by_contact(user_id: str, contact_email: str) -> list[dict]:
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM deals WHERE user_id = %s AND contact_email ILIKE %s ORDER BY updated_at DESC",
            (user_id, f"%{contact_email}%")
        )
        return [dict(r) for r in cur.fetchall()]


def get_pipeline_summary(user_id: str) -> dict:
    with db_cursor(dict_rows=True) as cur:
        cur.execute("""
            SELECT stage, COUNT(*) as count, SUM(deal_value) as total_value
            FROM deals
            WHERE user_id = %s
            GROUP BY stage
        """, (user_id,))
        rows = cur.fetchall()
    return {r["stage"]: {"count": r["count"], "total_value": r["total_value"] or 0} for r in rows}
