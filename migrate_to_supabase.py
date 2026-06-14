"""
One-time migration: backfill memory.db (SQLite) rows into Supabase Postgres
under TARGET_USER_ID.

DB-only — does not touch Gmail or OpenAI.

Run: .venv/bin/python migrate_to_supabase.py
"""
import json
import sqlite3
from collections import defaultdict

from psycopg2.extras import Json

from db import db_cursor

SQLITE_PATH = "memory.db"
TARGET_USER_ID = "82a6e1bd-0fe2-42ba-bf86-a5797974f37e"


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────
# EMAILS — only rows not already in Postgres
# ──────────────────────────────────────────────
def migrate_emails(sconn):
    with db_cursor() as cur:
        cur.execute("SELECT gmail_id FROM emails WHERE user_id = %s", (TARGET_USER_ID,))
        existing = {r[0] for r in cur.fetchall()}

    rows = sconn.execute("SELECT * FROM emails").fetchall()
    new_rows = [r for r in rows if r["gmail_id"] not in existing]

    inserted = 0
    with db_cursor(commit=True) as cur:
        for r in new_rows:
            embedding = json.loads(r["embedding"]) if r["embedding"] else None
            cur.execute("""
                INSERT INTO emails (
                    user_id, gmail_id, thread_id, sender, subject, snippet,
                    full_text, embedding, category, action, importance, summary,
                    draft_status, draft_text, draft_gmail_id, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        COALESCE(%s::timestamptz, now()))
                ON CONFLICT (user_id, gmail_id) DO NOTHING
            """, (
                TARGET_USER_ID, r["gmail_id"], r["thread_id"], r["sender"], r["subject"], r["snippet"],
                r["full_text"], embedding, r["category"], r["action"], r["importance"], r["summary"],
                r["draft_status"], r["draft_text"], r["draft_gmail_id"], r["created_at"]
            ))
            inserted += cur.rowcount

    print(f"emails: {len(rows)} in sqlite, {len(existing)} already in postgres, {inserted} new rows inserted")
    return new_rows


# ──────────────────────────────────────────────
# THREAD SUMMARIES — for threads touched by the new emails
# ──────────────────────────────────────────────
def migrate_thread_summaries(sconn, new_email_rows):
    thread_ids = {r["thread_id"] for r in new_email_rows if r["thread_id"]}
    summaries = {row["thread_id"]: row for row in sconn.execute("SELECT * FROM thread_summaries").fetchall()}

    count = 0
    with db_cursor(commit=True) as cur:
        for tid in thread_ids:
            row = summaries.get(tid)
            if not row:
                continue
            cur.execute("""
                INSERT INTO thread_summaries (user_id, thread_id, summary, updated_at)
                VALUES (%s, %s, %s, COALESCE(%s::timestamptz, now()))
                ON CONFLICT (user_id, thread_id) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
            """, (TARGET_USER_ID, tid, row["summary"], row["updated_at"]))
            count += 1

    print(f"thread_summaries: upserted {count} of {len(thread_ids)} touched thread_ids")


# ──────────────────────────────────────────────
# THREADS — new threads get sqlite's full historical message_count;
# threads that already exist in postgres just get bumped for the
# new email(s) being added to them.
# ──────────────────────────────────────────────
def migrate_threads(sconn, new_email_rows):
    with db_cursor() as cur:
        cur.execute("SELECT gmail_thread_id FROM threads WHERE user_id = %s", (TARGET_USER_ID,))
        existing_threads = {r[0] for r in cur.fetchall()}

    by_thread = defaultdict(list)
    for r in new_email_rows:
        if r["thread_id"]:
            by_thread[r["thread_id"]].append(r)

    inserted, updated = 0, 0
    with db_cursor(commit=True) as cur:
        for tid, rows in by_thread.items():
            latest = max(rows, key=lambda r: r["id"])

            if tid in existing_threads:
                cur.execute("""
                    UPDATE threads SET
                        message_count = message_count + %s,
                        last_message_snippet = %s,
                        last_updated = now()
                    WHERE user_id = %s AND gmail_thread_id = %s
                """, (len(rows), latest["snippet"], TARGET_USER_ID, tid))
                updated += 1
            else:
                total_count = sconn.execute(
                    "SELECT COUNT(*) FROM emails WHERE thread_id = ?", (tid,)
                ).fetchone()[0]
                cur.execute("""
                    INSERT INTO threads (
                        user_id, gmail_thread_id, subject, participants,
                        message_count, last_message_snippet, last_updated
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (user_id, gmail_thread_id) DO NOTHING
                """, (TARGET_USER_ID, tid, latest["subject"], latest["sender"], total_count, latest["snippet"]))
                inserted += 1

    print(f"threads: {inserted} new threads inserted, {updated} existing threads bumped")


# ──────────────────────────────────────────────
# SENDERS — sqlite's counts are the true historical totals
# (they already include whatever overlap postgres independently
# re-ingested today), so overwrite rather than add.
# ──────────────────────────────────────────────
def migrate_senders(sconn):
    rows = sconn.execute("SELECT * FROM senders").fetchall()
    with db_cursor(commit=True) as cur:
        for r in rows:
            cur.execute("""
                INSERT INTO senders (user_id, sender, email_count, important_count, last_seen)
                VALUES (%s, %s, %s, %s, %s::timestamptz)
                ON CONFLICT (user_id, sender) DO UPDATE SET
                    email_count = excluded.email_count,
                    important_count = excluded.important_count,
                    last_seen = GREATEST(senders.last_seen, excluded.last_seen)
            """, (TARGET_USER_ID, r["sender"], r["email_count"], r["important_count"], r["last_seen"]))

    print(f"senders: upserted {len(rows)} rows")


# ──────────────────────────────────────────────
# CONTACT PROFILES — merge sqlite's historical intelligence into
# whatever postgres already has for each contact.
# ──────────────────────────────────────────────
def migrate_contact_profiles(sconn):
    rows = sconn.execute("SELECT * FROM contact_profiles").fetchall()
    with db_cursor(commit=True) as cur:
        for r in rows:
            tags = json.loads(r["tags"]) if r["tags"] else []
            cur.execute("""
                INSERT INTO contact_profiles (
                    user_id, email, name, company, role, contact_type, relationship_type,
                    emails_received, emails_sent, threads_shared,
                    first_contact_date, last_contact_date, relationship_score,
                    is_vip, vip_reason, ai_summary, tags, notes, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz, %s, %s, %s, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz)
                ON CONFLICT (user_id, email) DO UPDATE SET
                    name = CASE WHEN excluded.name != '' THEN excluded.name ELSE contact_profiles.name END,
                    company = CASE WHEN excluded.company != '' THEN excluded.company ELSE contact_profiles.company END,
                    role = CASE WHEN excluded.role != '' THEN excluded.role ELSE contact_profiles.role END,
                    contact_type = CASE WHEN excluded.contact_type != 'unknown' THEN excluded.contact_type ELSE contact_profiles.contact_type END,
                    relationship_type = CASE WHEN excluded.relationship_type != 'new' THEN excluded.relationship_type ELSE contact_profiles.relationship_type END,
                    emails_received = excluded.emails_received,
                    emails_sent = excluded.emails_sent,
                    threads_shared = excluded.threads_shared,
                    first_contact_date = LEAST(contact_profiles.first_contact_date, excluded.first_contact_date),
                    last_contact_date = GREATEST(contact_profiles.last_contact_date, excluded.last_contact_date),
                    relationship_score = excluded.relationship_score,
                    is_vip = contact_profiles.is_vip OR excluded.is_vip,
                    vip_reason = CASE WHEN excluded.vip_reason != '' THEN excluded.vip_reason ELSE contact_profiles.vip_reason END,
                    ai_summary = CASE WHEN excluded.ai_summary != '' THEN excluded.ai_summary ELSE contact_profiles.ai_summary END,
                    tags = CASE WHEN jsonb_array_length(excluded.tags) > 0 THEN excluded.tags ELSE contact_profiles.tags END,
                    notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE contact_profiles.notes END,
                    updated_at = now()
            """, (
                TARGET_USER_ID, r["email"], r["name"] or "", r["company"] or "", r["role"] or "",
                r["contact_type"] or "unknown", r["relationship_type"] or "new",
                r["emails_received"] or 0, r["emails_sent"] or 0, r["threads_shared"] or 0,
                r["first_contact_date"], r["last_contact_date"], r["relationship_score"] or 0.0,
                bool(r["is_vip"]), r["vip_reason"] or "", r["ai_summary"] or "",
                Json(tags), r["notes"] or "", r["created_at"], r["updated_at"]
            ))

    print(f"contact_profiles: upserted {len(rows)} rows")


# ──────────────────────────────────────────────
# STYLE PROFILE — only if postgres has none yet for this user
# ──────────────────────────────────────────────
def migrate_style_profile(sconn):
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM style_profile WHERE user_id = %s", (TARGET_USER_ID,))
        if cur.fetchone():
            print("style_profile: postgres already has a row, skipping")
            return

    row = sconn.execute("SELECT * FROM style_profile ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        print("style_profile: nothing to migrate")
        return

    profile_json = json.loads(row["profile_json"])
    example_emails = json.loads(row["example_emails"]) if row["example_emails"] else []

    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO style_profile (user_id, profile_json, sample_count, example_emails, updated_at)
            VALUES (%s, %s, %s, %s, %s::timestamptz)
        """, (TARGET_USER_ID, Json(profile_json), row["sample_count"], Json(example_emails), row["updated_at"]))

    print("style_profile: migrated 1 row")


# ──────────────────────────────────────────────
# SENT SAMPLES
# ──────────────────────────────────────────────
def migrate_sent_samples(sconn):
    rows = sconn.execute("SELECT * FROM sent_samples").fetchall()
    inserted = 0
    with db_cursor(commit=True) as cur:
        for r in rows:
            cur.execute("""
                INSERT INTO sent_samples (user_id, gmail_id, body, to_email, subject, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                ON CONFLICT (user_id, gmail_id) DO NOTHING
            """, (TARGET_USER_ID, r["gmail_id"], r["body"], r["to_email"], r["subject"], r["created_at"]))
            inserted += cur.rowcount

    print(f"sent_samples: {inserted} of {len(rows)} inserted")


# ──────────────────────────────────────────────
# CORRECTIONS — dedup by (gmail_id, original/corrected category+action)
# since there's no unique constraint to rely on for idempotency.
# ──────────────────────────────────────────────
def migrate_corrections(sconn):
    with db_cursor(dict_rows=True) as cur:
        cur.execute("""
            SELECT gmail_id, original_category, corrected_category, original_action, corrected_action
            FROM corrections WHERE user_id = %s
        """, (TARGET_USER_ID,))
        existing = {
            (r["gmail_id"], r["original_category"], r["corrected_category"], r["original_action"], r["corrected_action"])
            for r in cur.fetchall()
        }

    rows = sconn.execute("SELECT * FROM corrections").fetchall()
    inserted = 0
    with db_cursor(commit=True) as cur:
        for r in rows:
            key = (r["gmail_id"], r["original_category"], r["corrected_category"], r["original_action"], r["corrected_action"])
            if key in existing:
                continue
            embedding = json.loads(r["embedding"]) if r["embedding"] else None
            cur.execute("""
                INSERT INTO corrections (
                    user_id, gmail_id, sender, sender_domain,
                    original_category, corrected_category,
                    original_action, corrected_action,
                    email_text, embedding, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
            """, (
                TARGET_USER_ID, r["gmail_id"], r["sender"], r["sender_domain"],
                r["original_category"], r["corrected_category"],
                r["original_action"], r["corrected_action"],
                r["email_text"], embedding, r["created_at"]
            ))
            existing.add(key)
            inserted += 1

    print(f"corrections: {inserted} of {len(rows)} inserted")


# ──────────────────────────────────────────────
# SENDER PATTERNS
# ──────────────────────────────────────────────
def migrate_sender_patterns(sconn):
    rows = sconn.execute("SELECT * FROM sender_patterns").fetchall()
    inserted = 0
    with db_cursor(commit=True) as cur:
        for r in rows:
            cur.execute("""
                INSERT INTO sender_patterns (user_id, sender_domain, typical_category, typical_action, correction_count, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                ON CONFLICT (user_id, sender_domain) DO NOTHING
            """, (TARGET_USER_ID, r["sender_domain"], r["typical_category"], r["typical_action"], r["correction_count"], r["last_updated"]))
            inserted += cur.rowcount

    print(f"sender_patterns: {inserted} of {len(rows)} inserted")


def main():
    sconn = get_sqlite_conn()

    new_email_rows = migrate_emails(sconn)
    migrate_thread_summaries(sconn, new_email_rows)
    migrate_threads(sconn, new_email_rows)
    migrate_senders(sconn)
    migrate_contact_profiles(sconn)
    migrate_style_profile(sconn)
    migrate_sent_samples(sconn)
    migrate_corrections(sconn)
    migrate_sender_patterns(sconn)

    sconn.close()
    print("\nDone. Skipped: legacy `contacts` table (unused by the live app) "
          "and sqlite `threads` table (stale thread IDs not matching emails.thread_id).")


if __name__ == "__main__":
    main()
