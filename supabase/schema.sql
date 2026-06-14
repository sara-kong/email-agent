-- Email Agent — Supabase/Postgres schema
--
-- Mirrors the existing memory.db (SQLite) tables, with two changes for
-- multi-user support:
--   1. Every table gets a `user_id uuid` column referencing Supabase Auth's
--      built-in `auth.users` table. Application code is responsible for
--      filtering/scoping by user_id (added in checkpoint 3c) — this schema
--      does not rely on Postgres RLS.
--   2. Embedding columns use pgvector's `vector(1536)` type (matching
--      OpenAI's text-embedding-3-small) instead of JSON-encoded TEXT, so
--      semantic search can eventually run as a SQL query instead of a
--      full-table Python scan.
--
-- Run this once against a fresh Supabase project (SQL Editor, or via
-- `psql "$SUPABASE_DB_URL" -f supabase/schema.sql`).

create extension if not exists vector;

-- ==============================
-- EMAILS
-- ==============================
create table if not exists emails (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references auth.users(id) on delete cascade,
    gmail_id        text not null,
    thread_id       text,
    sender          text,
    subject         text,
    snippet         text,
    full_text       text,
    embedding       vector(1536),
    category        text,
    action          text,
    importance      text,
    summary         text,
    draft_status    text default 'none',
    draft_text      text,
    draft_gmail_id  text,
    created_at      timestamptz default now(),
    unique (user_id, gmail_id)
);

create index if not exists idx_emails_user_id on emails(user_id);
create index if not exists idx_emails_thread_id on emails(user_id, thread_id);

-- ==============================
-- THREADS
-- ==============================
create table if not exists threads (
    id                      bigint generated always as identity primary key,
    user_id                 uuid not null references auth.users(id) on delete cascade,
    gmail_thread_id         text not null,
    subject                 text,
    participants            text,
    message_count           integer default 0,
    last_message_snippet    text,
    last_updated            timestamptz default now(),
    unique (user_id, gmail_thread_id)
);

create index if not exists idx_threads_user_id on threads(user_id);

-- ==============================
-- THREAD SUMMARIES
-- ==============================
create table if not exists thread_summaries (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    thread_id   text not null,
    summary     text,
    updated_at  timestamptz default now(),
    unique (user_id, thread_id)
);

create index if not exists idx_thread_summaries_user_id on thread_summaries(user_id);

-- ==============================
-- CONTACTS (legacy simple table)
-- ==============================
create table if not exists contacts (
    id                  bigint generated always as identity primary key,
    user_id             uuid not null references auth.users(id) on delete cascade,
    email               text not null,
    emails_sent         integer default 0,
    emails_received     integer default 0,
    relationship_score  real default 0,
    last_contact_date   timestamptz default now(),
    unique (user_id, email)
);

create index if not exists idx_contacts_user_id on contacts(user_id);

-- ==============================
-- CONTACT PROFILES (rich contact intelligence)
-- ==============================
create table if not exists contact_profiles (
    id                  bigint generated always as identity primary key,
    user_id             uuid not null references auth.users(id) on delete cascade,
    email               text not null,
    name                text default '',
    company             text default '',
    role                text default '',
    contact_type        text default 'unknown',
    relationship_type   text default 'new',
    emails_received     integer default 0,
    emails_sent         integer default 0,
    threads_shared      integer default 0,
    first_contact_date  timestamptz,
    last_contact_date   timestamptz,
    relationship_score  real default 0.0,
    is_vip              boolean default false,
    vip_reason          text default '',
    ai_summary          text default '',
    tags                jsonb default '[]'::jsonb,
    notes               text default '',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now(),
    unique (user_id, email)
);

create index if not exists idx_contact_profiles_user_id on contact_profiles(user_id);

-- ==============================
-- SENDERS (trust/frequency tracking)
-- ==============================
create table if not exists senders (
    id                  bigint generated always as identity primary key,
    user_id             uuid not null references auth.users(id) on delete cascade,
    sender              text not null,
    email_count         integer default 0,
    important_count     integer default 0,
    last_seen           timestamptz default now(),
    unique (user_id, sender)
);

create index if not exists idx_senders_user_id on senders(user_id);

-- ==============================
-- CAMPAIGNS
-- ==============================
create table if not exists campaigns (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    name        text not null,
    goal        text,
    status      text default 'active',
    created_at  timestamptz default now(),
    updated_at  timestamptz default now()
);

create index if not exists idx_campaigns_user_id on campaigns(user_id);

-- ==============================
-- CAMPAIGN CONTACTS
-- ==============================
create table if not exists campaign_contacts (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references auth.users(id) on delete cascade,
    campaign_id     bigint not null references campaigns(id) on delete cascade,
    contact_email   text not null,
    sequence_step   integer default 0,
    status          text default 'pending',
    last_sent_at    timestamptz,
    replied_at      timestamptz,
    reply_gmail_id  text,
    notes           text,
    unique (campaign_id, contact_email)
);

create index if not exists idx_campaign_contacts_user_id on campaign_contacts(user_id);

-- ==============================
-- DEALS
-- ==============================
create table if not exists deals (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references auth.users(id) on delete cascade,
    contact_email   text not null,
    company         text,
    title           text,
    stage           text default 'prospecting',
    deal_value      real,
    currency        text default 'USD',
    notes           text,
    thread_ids      jsonb default '[]'::jsonb,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

create index if not exists idx_deals_user_id on deals(user_id);

-- ==============================
-- STYLE PROFILE
-- ==============================
create table if not exists style_profile (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references auth.users(id) on delete cascade,
    profile_json    jsonb not null,
    sample_count    integer default 0,
    example_emails  jsonb default '[]'::jsonb,
    updated_at      timestamptz default now()
);

create index if not exists idx_style_profile_user_id on style_profile(user_id);

-- ==============================
-- SENT SAMPLES
-- ==============================
create table if not exists sent_samples (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    gmail_id    text not null,
    body        text,
    to_email    text,
    subject     text,
    created_at  timestamptz default now(),
    unique (user_id, gmail_id)
);

create index if not exists idx_sent_samples_user_id on sent_samples(user_id);

-- ==============================
-- CORRECTIONS (classifier feedback)
-- ==============================
create table if not exists corrections (
    id                  bigint generated always as identity primary key,
    user_id             uuid not null references auth.users(id) on delete cascade,
    gmail_id            text,
    sender              text,
    sender_domain       text,
    original_category   text,
    corrected_category  text,
    original_action     text,
    corrected_action    text,
    email_text          text,
    embedding           vector(1536),
    created_at          timestamptz default now()
);

create index if not exists idx_corrections_user_id on corrections(user_id);

-- ==============================
-- SENDER PATTERNS (learned classifier shortcuts)
-- ==============================
create table if not exists sender_patterns (
    user_id             uuid not null references auth.users(id) on delete cascade,
    sender_domain       text not null,
    typical_category    text,
    typical_action      text,
    correction_count    integer default 0,
    last_updated        timestamptz default now(),
    primary key (user_id, sender_domain)
);

-- ==============================
-- OAUTH TOKENS (per-user Gmail credentials)
-- ==============================
create table if not exists oauth_tokens (
    user_id                     uuid primary key references auth.users(id) on delete cascade,
    provider                    text not null default 'google',
    google_email                text,
    encrypted_refresh_token     text not null,
    access_token                text,
    access_token_expires_at     timestamptz,
    scopes                      text,
    created_at                  timestamptz default now(),
    updated_at                  timestamptz default now()
);
