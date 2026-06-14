import sys
import os
sys.path.insert(0, os.path.abspath("."))

import json
import asyncio
import secrets
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Response, Cookie, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# ── Internal modules ──────────────────────────────────────────
from db import db_cursor
from gmail_utils import fetch_full_email, fetch_thread, fetch_emails
from memory import (
    save_email, email_exists, semantic_search,
    get_thread_summary, save_thread_summary,
    upsert_contact, upsert_thread
)
from embeddings import create_embedding
from classifier import classify_email
from responder import generate_reply
from draft_creator import create_draft, update_draft, send_draft, generate_and_create_draft, within_draft_window
from summarizer import summarize_thread
from campaign_tracker import (
    init_campaign_tables, create_campaign, list_campaigns,
    get_campaign, update_campaign_status, add_contact_to_campaign,
    mark_email_sent, get_campaign_contacts, get_campaign_stats,
    check_if_campaign_reply, create_deal, advance_deal_stage,
    attach_thread_to_deal, get_deals, get_pipeline_summary,
    get_deal_by_contact, DEAL_STAGES
)
from contact_intelligence import (
    init_contact_intelligence_tables, upsert_contact_profile,
    get_top_contacts, get_contacts_by_type, get_contact,
    get_vip_contacts, search_contacts, refresh_all_scores,
    ai_categorize_contact, set_vip, compute_relationship_score
)
from style_profiler import (
    init_style_table, load_style_profile, get_style_prompt,
    build_style_profile
)
from outbound_v2 import generate_outreach_email
from corrections import init_corrections_table, init_sender_patterns_table, log_correction
from daemon import start_daemon
from auth import (
    get_google_auth_url, exchange_code_for_tokens, get_google_userinfo,
    find_or_create_supabase_user, save_oauth_tokens,
    create_session_jwt, verify_session_jwt, get_gmail_service_for_user, FRONTEND_URL
)


# ──────────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────────

app = FastAPI(title="Email Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# AUTH DEPENDENCY
# ──────────────────────────────────────────────

def get_current_user(session_token: Optional[str] = Cookie(default=None)) -> str:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_session_jwt(session_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return payload["sub"]


# WebSocket connection manager for real-time events, scoped per user
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str):
        await ws.accept()
        self.active.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: str):
        conns = self.active.get(user_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, user_id: str, message: dict):
        dead = []
        for ws in self.active.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active[user_id].remove(ws)


manager = ConnectionManager()


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_campaign_tables()
    init_contact_intelligence_tables()
    init_style_table()
    init_corrections_table()
    init_sender_patterns_table()

    # Start the continuous inbox-polling daemon (runs in a background thread).
    # It polls every connected user's inbox; its event_callback runs off the
    # asyncio event loop, so bridge broadcasts back via run_coroutine_threadsafe.
    if os.getenv("DAEMON_ENABLED", "false").lower() == "true":
        loop = asyncio.get_event_loop()

        def event_callback(event: dict):
            asyncio.run_coroutine_threadsafe(manager.broadcast(event["user_id"], event), loop)

        start_daemon(event_callback)
        print("✔ API server started (daemon enabled)")
    else:
        print("✔ API server started (daemon disabled — set DAEMON_ENABLED=true to enable polling)")


# ──────────────────────────────────────────────
# HEALTH
# ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ──────────────────────────────────────────────
# GOOGLE OAUTH (multi-user login)
# ──────────────────────────────────────────────

@app.get("/auth/google/login")
def auth_google_login():
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(get_google_auth_url(state))
    response.set_cookie(
        "oauth_state", state,
        httponly=True, samesite="lax", max_age=600,
    )
    return response


@app.get("/auth/google/callback")
def auth_google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    oauth_state: Optional[str] = Cookie(default=None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code or not state or state != oauth_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    token_response = exchange_code_for_tokens(code)
    if "refresh_token" not in token_response:
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Revoke the app's "
                   "access at https://myaccount.google.com/permissions and try again "
                   "(Google only returns a refresh token on first consent)."
        )

    userinfo = get_google_userinfo(token_response["access_token"])
    email = userinfo["email"]

    user_id = find_or_create_supabase_user(email)
    save_oauth_tokens(user_id, email, token_response)

    session_token = create_session_jwt(user_id, email)

    redirect = RedirectResponse(f"{FRONTEND_URL}/")
    redirect.delete_cookie("oauth_state")
    redirect.set_cookie(
        "session_token", session_token,
        httponly=True, samesite="lax", max_age=30 * 24 * 3600,
    )
    return redirect


@app.get("/auth/me")
def auth_me(session_token: Optional[str] = Cookie(default=None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_session_jwt(session_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {"user_id": payload["sub"], "email": payload["email"]}


@app.post("/auth/logout")
def auth_logout():
    response = Response(status_code=204)
    response.delete_cookie("session_token")
    return response


# ──────────────────────────────────────────────
# INBOX
# ──────────────────────────────────────────────

class ProcessInboxRequest(BaseModel):
    max_results: int = 10
    label_ids: list[str] = ["INBOX"]

@app.post("/inbox/process")
async def process_inbox(
    req: ProcessInboxRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """Trigger inbox processing in the background."""
    background_tasks.add_task(_process_inbox_task, user_id, req.max_results, req.label_ids)
    return {"status": "processing_started", "max_results": req.max_results}


async def _process_inbox_task(user_id: str, max_results: int, label_ids: list[str]):
    """Background task: fetch, classify, embed, and store emails."""
    service = get_gmail_service_for_user(user_id)
    emails, _ = fetch_emails(service, max_results=max_results)

    for email in emails:
        gmail_id = email["id"]
        if email_exists(user_id, gmail_id):
            continue

        email_data = fetch_full_email(service, gmail_id)
        thread_id = email_data["thread_id"]
        sender = email_data["sender"]
        subject = email_data["subject"]
        snippet = email_data["snippet"]
        email_text = email_data["email_text"]

        embedding = create_embedding(email_text)
        classification = classify_email(user_id, email_text, sender=sender, embedding=embedding)
        label = classification.get("label", "unknown")
        action = classification.get("suggested_action", "ignore")
        score = classification.get("importance_score", 0)

        existing_summary = get_thread_summary(user_id, thread_id)
        updated_summary = summarize_thread(existing_summary, email_text)
        save_thread_summary(user_id, thread_id, updated_summary)

        # Auto-generate a reply draft for reply-worthy emails received recently
        # (avoids mass-drafting an old backlog of un-ingested inbox emails)
        draft_status = "none"
        draft_text = None
        draft_gmail_id = None
        if action == "reply" and within_draft_window(email_data.get("internal_date")):
            draft_text, draft_gmail_id = generate_and_create_draft(
                user_id, service, sender, subject, email_text, updated_summary, embedding
            )
            draft_status = "ready"

        save_email(
            user_id, gmail_id, thread_id, sender, subject, snippet,
            email_text, embedding,
            label, action, str(score), updated_summary,
            draft_status=draft_status, draft_text=draft_text, draft_gmail_id=draft_gmail_id
        )

        upsert_contact_profile(user_id, email=sender, name=sender, received=True)
        upsert_thread(user_id, thread_id, subject, sender, snippet)

        # Reply detection for campaigns
        check_if_campaign_reply(user_id, sender, gmail_id)

        await manager.broadcast(user_id, {
            "event": "new_email",
            "gmail_id": gmail_id,
            "sender": sender,
            "subject": subject,
            "label": label,
            "action": action,
            "draft_status": draft_status
        })


EMAIL_COLUMNS = """
    id, user_id, gmail_id, thread_id, sender, subject, snippet, full_text,
    category, action, importance, summary,
    draft_status, draft_text, draft_gmail_id, created_at
"""


@app.get("/inbox/emails")
def list_emails(
    limit: int = 20,
    label: Optional[str] = None,
    sender: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    query = f"SELECT {EMAIL_COLUMNS} FROM emails WHERE user_id = %s"
    params = [user_id]
    if label:
        query += " AND category = %s"
        params.append(label)
    if sender:
        query += " AND sender ILIKE %s"
        params.append(f"%{sender}%")
    query += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    with db_cursor(dict_rows=True) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    return {"emails": [dict(r) for r in rows]}


@app.get("/inbox/emails/{gmail_id}")
def get_email(gmail_id: str, user_id: str = Depends(get_current_user)):
    with db_cursor(dict_rows=True) as cur:
        cur.execute(
            f"SELECT {EMAIL_COLUMNS} FROM emails WHERE user_id = %s AND gmail_id = %s",
            (user_id, gmail_id)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    return dict(row)


@app.get("/inbox/threads/{thread_id}")
def get_thread_endpoint(thread_id: str, user_id: str = Depends(get_current_user)):
    """Fetch the full Gmail conversation for a thread, including sent replies."""
    try:
        messages = fetch_thread(get_gmail_service_for_user(user_id), thread_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread not found: {e}")

    summary = get_thread_summary(user_id, thread_id)
    return {"thread_id": thread_id, "summary": summary, "messages": messages}


class EmailCorrectionRequest(BaseModel):
    category: str
    action: Optional[str] = None

@app.post("/inbox/emails/{gmail_id}/correct")
def correct_email(
    gmail_id: str,
    req: EmailCorrectionRequest,
    user_id: str = Depends(get_current_user),
):
    """Record a user correction to an email's category/action and log it for future classification."""
    with db_cursor(commit=True, dict_rows=True) as cur:
        cur.execute(
            "SELECT * FROM emails WHERE user_id = %s AND gmail_id = %s",
            (user_id, gmail_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")

        original_category = row["category"]
        original_action = row["action"]
        corrected_category = req.category
        corrected_action = req.action or original_action

        cur.execute(
            "UPDATE emails SET category = %s, action = %s WHERE user_id = %s AND gmail_id = %s",
            (corrected_category, corrected_action, user_id, gmail_id)
        )

    log_correction(
        user_id,
        gmail_id=gmail_id,
        sender=row["sender"],
        original_category=original_category,
        corrected_category=corrected_category,
        original_action=original_action,
        corrected_action=corrected_action,
        email_text=row["full_text"],
        embedding=row["embedding"],
    )

    return {
        "status": "corrected",
        "gmail_id": gmail_id,
        "category": corrected_category,
        "action": corrected_action,
    }


# ──────────────────────────────────────────────
# REPLY / DRAFT GENERATION
# ──────────────────────────────────────────────

class GenerateReplyRequest(BaseModel):
    gmail_id: str
    email_text: str
    thread_summary: Optional[str] = ""
    auto_send: bool = False
    final_text: Optional[str] = None

@app.post("/inbox/reply")
def generate_reply_endpoint(req: GenerateReplyRequest, user_id: str = Depends(get_current_user)):
    if req.final_text is not None:
        # User has already generated and edited a draft; use it as-is.
        reply = req.final_text
    else:
        embedding = create_embedding(req.email_text)
        memory_context = "\n\n".join(semantic_search(user_id, embedding, limit=3))
        style_prompt = get_style_prompt(user_id)
        reply = generate_reply(user_id, req.email_text, req.thread_summary or "", memory_context, style_prompt)

    if req.auto_send:
        # Create a Gmail draft
        with db_cursor(dict_rows=True) as cur:
            cur.execute(
                "SELECT sender, subject FROM emails WHERE user_id = %s AND gmail_id = %s",
                (user_id, req.gmail_id)
            )
            row = cur.fetchone()
        if row:
            create_draft(get_gmail_service_for_user(user_id), row["sender"], row["subject"], reply)

    return {"reply": reply, "draft_created": req.auto_send}


class SendDraftRequest(BaseModel):
    final_text: Optional[str] = None

@app.post("/inbox/emails/{gmail_id}/draft/send")
def send_draft_endpoint(
    gmail_id: str,
    req: SendDraftRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Approve and send the auto-generated draft for an email (or, if final_text
    is provided, send that text instead). Actually sends via the Gmail API —
    the frontend should confirm with the user before calling this.
    """
    with db_cursor(commit=True, dict_rows=True) as cur:
        cur.execute(
            "SELECT sender, subject, draft_text, draft_gmail_id FROM emails WHERE user_id = %s AND gmail_id = %s",
            (user_id, gmail_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")

        text = req.final_text if req.final_text is not None else row["draft_text"]
        if not text:
            raise HTTPException(status_code=400, detail="No draft text to send")

        service = get_gmail_service_for_user(user_id)
        draft_id = row["draft_gmail_id"]

        if draft_id:
            if req.final_text is not None and req.final_text != row["draft_text"]:
                update_draft(service, draft_id, row["sender"], row["subject"], text)
            send_draft(service, draft_id)
        else:
            draft = create_draft(service, row["sender"], row["subject"], text)
            send_draft(service, draft["id"])

        cur.execute(
            "UPDATE emails SET draft_status = 'sent', draft_text = %s WHERE user_id = %s AND gmail_id = %s",
            (text, user_id, gmail_id)
        )

    return {"status": "sent", "gmail_id": gmail_id}


# ──────────────────────────────────────────────
# CONTACTS
# ──────────────────────────────────────────────

@app.get("/contacts")
def contacts(
    limit: int = 50,
    contact_type: Optional[str] = None,
    vip_only: bool = False,
    q: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    if q:
        return {"contacts": search_contacts(user_id, q)}
    if vip_only:
        return {"contacts": get_vip_contacts(user_id)}
    if contact_type:
        return {"contacts": get_contacts_by_type(user_id, contact_type)}
    return {"contacts": get_top_contacts(user_id, limit=limit)}


@app.get("/contacts/{email}")
def get_contact_endpoint(email: str, user_id: str = Depends(get_current_user)):
    contact = get_contact(user_id, email)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact["deals"] = get_deal_by_contact(user_id, email)
    return contact


class VIPRequest(BaseModel):
    email: str
    reason: str = ""

@app.post("/contacts/vip")
def mark_vip(req: VIPRequest, user_id: str = Depends(get_current_user)):
    set_vip(user_id, req.email, req.reason)
    return {"status": "ok"}


class CategorizeRequest(BaseModel):
    email: str

@app.post("/contacts/{email}/categorize")
def categorize_contact(
    email: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """Trigger AI categorization for a contact."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT full_text FROM emails WHERE user_id = %s AND sender ILIKE %s ORDER BY id DESC LIMIT 5",
            (user_id, f"%{email}%")
        )
        recent = [r[0] for r in cur.fetchall()]

    result = ai_categorize_contact(user_id, email, recent)
    return result


@app.post("/contacts/scores/refresh")
def refresh_scores(background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user)):
    background_tasks.add_task(refresh_all_scores, user_id)
    return {"status": "refresh_started"}


# ──────────────────────────────────────────────
# CAMPAIGNS
# ──────────────────────────────────────────────

class CreateCampaignRequest(BaseModel):
    name: str
    goal: str = ""
    contacts: list[str] = []

@app.post("/campaigns")
def create_campaign_endpoint(req: CreateCampaignRequest, user_id: str = Depends(get_current_user)):
    campaign_id = create_campaign(user_id, req.name, req.goal)
    for email in req.contacts:
        add_contact_to_campaign(user_id, campaign_id, email)
    return {"campaign_id": campaign_id, "status": "created"}


@app.get("/campaigns")
def list_campaigns_endpoint(status: Optional[str] = None, user_id: str = Depends(get_current_user)):
    campaigns = list_campaigns(user_id, status=status)
    for c in campaigns:
        c["stats"] = get_campaign_stats(user_id, c["id"])
    return {"campaigns": campaigns}


@app.get("/campaigns/{campaign_id}")
def get_campaign_endpoint(campaign_id: int, user_id: str = Depends(get_current_user)):
    campaign = get_campaign(user_id, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign["contacts"] = get_campaign_contacts(user_id, campaign_id)
    campaign["stats"] = get_campaign_stats(user_id, campaign_id)
    return campaign


class AddCampaignContactsRequest(BaseModel):
    emails: list[str]

@app.post("/campaigns/{campaign_id}/contacts")
def add_campaign_contacts(
    campaign_id: int,
    req: AddCampaignContactsRequest,
    user_id: str = Depends(get_current_user),
):
    if not get_campaign(user_id, campaign_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    for email in req.emails:
        add_contact_to_campaign(user_id, campaign_id, email)
    return {"status": "added", "count": len(req.emails)}


class OutboundEmailRequest(BaseModel):
    campaign_id: int
    contact_email: str
    campaign_prompt: str
    send_as_draft: bool = True

@app.post("/campaigns/{campaign_id}/send")
def send_campaign_email(
    campaign_id: int,
    req: OutboundEmailRequest,
    user_id: str = Depends(get_current_user),
):
    """Generate and optionally draft a personalized outbound email."""
    contact = get_contact(user_id, req.contact_email)
    if not contact:
        # Minimal contact tuple for backward compat
        contact_tuple = (None, req.contact_email, req.contact_email, "", "", "")
    else:
        contact_tuple = (
            contact.get("id"), contact.get("name", ""),
            contact.get("email"), contact.get("company", ""),
            contact.get("role", ""), contact.get("ai_summary", "")
        )

    style_prompt = get_style_prompt(user_id)
    email_body = generate_outreach_email(user_id, contact_tuple, req.campaign_prompt, style_prompt)

    if req.send_as_draft:
        subject = f"[Campaign: {campaign_id}] Outreach"
        create_draft(get_gmail_service_for_user(user_id), req.contact_email, subject, email_body)

    mark_email_sent(user_id, campaign_id, req.contact_email)

    return {"email_body": email_body, "draft_created": req.send_as_draft}


class UpdateCampaignStatusRequest(BaseModel):
    status: str  # active | paused | completed

@app.patch("/campaigns/{campaign_id}/status")
def update_campaign(
    campaign_id: int,
    req: UpdateCampaignStatusRequest,
    user_id: str = Depends(get_current_user),
):
    update_campaign_status(user_id, campaign_id, req.status)
    return {"status": "updated"}


# ──────────────────────────────────────────────
# DEALS
# ──────────────────────────────────────────────

class CreateDealRequest(BaseModel):
    contact_email: str
    title: str
    company: str = ""
    deal_value: Optional[float] = None
    notes: str = ""

@app.post("/deals")
def create_deal_endpoint(req: CreateDealRequest, user_id: str = Depends(get_current_user)):
    deal_id = create_deal(
        user_id, req.contact_email, req.title,
        req.company, req.deal_value, req.notes
    )
    return {"deal_id": deal_id, "status": "created"}


@app.get("/deals")
def list_deals(stage: Optional[str] = None, user_id: str = Depends(get_current_user)):
    return {"deals": get_deals(user_id, stage=stage)}


@app.get("/deals/pipeline")
def pipeline_summary(user_id: str = Depends(get_current_user)):
    return {"pipeline": get_pipeline_summary(user_id), "stages": DEAL_STAGES}


class AdvanceDealRequest(BaseModel):
    stage: str

@app.patch("/deals/{deal_id}/stage")
def advance_deal(deal_id: int, req: AdvanceDealRequest, user_id: str = Depends(get_current_user)):
    try:
        advance_deal_stage(user_id, deal_id, req.stage)
        return {"status": "updated", "new_stage": req.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AttachThreadRequest(BaseModel):
    thread_id: str

@app.post("/deals/{deal_id}/threads")
def attach_thread(deal_id: int, req: AttachThreadRequest, user_id: str = Depends(get_current_user)):
    attach_thread_to_deal(user_id, deal_id, req.thread_id)
    return {"status": "attached"}


# ──────────────────────────────────────────────
# STYLE PROFILE
# ──────────────────────────────────────────────

@app.get("/style")
def get_style(user_id: str = Depends(get_current_user)):
    profile = load_style_profile(user_id)
    if not profile:
        return {"built": False, "message": "Style profile not yet built. POST /style/build to generate."}
    return {"built": True, "profile": profile}


@app.post("/style/build")
async def rebuild_style(background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user)):
    """Rebuild the style profile from sent emails (runs in background)."""
    background_tasks.add_task(_build_style_task, user_id)
    return {"status": "building", "message": "Style analysis started. Check /style when complete."}


async def _build_style_task(user_id: str):
    service = get_gmail_service_for_user(user_id)
    profile = build_style_profile(user_id, service, max_samples=50)
    await manager.broadcast(user_id, {"event": "style_profile_ready", "profile": profile})


# ──────────────────────────────────────────────
# AGENT CHAT
# ──────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None  # e.g. {"email_id": "...", "contact_email": "..."}

@app.post("/agent/chat")
def agent_chat(req: AgentChatRequest, user_id: str = Depends(get_current_user)):
    """
    Natural language interface to the agent.
    Handles questions like:
      - "Summarize my emails from Nike today"
      - "Draft a reply to the last email from john@example.com"
      - "What's the status of my deal with Brand X?"
    """
    from openai import OpenAI
    client = OpenAI()

    # Build context string
    context_parts = []
    if req.context:
        if req.context.get("email_id"):
            with db_cursor(dict_rows=True) as cur:
                cur.execute(
                    f"SELECT {EMAIL_COLUMNS} FROM emails WHERE user_id = %s AND gmail_id = %s",
                    (user_id, req.context["email_id"])
                )
                row = cur.fetchone()
            if row:
                context_parts.append(f"CURRENT EMAIL:\n{dict(row)}")

        if req.context.get("contact_email"):
            contact = get_contact(user_id, req.context["contact_email"])
            if contact:
                context_parts.append(f"CONTACT:\n{json.dumps(contact, indent=2, default=str)}")

    # Semantic search for relevant memories
    embedding = create_embedding(req.message)
    memories = semantic_search(user_id, embedding, limit=3)
    if memories:
        context_parts.append(f"RELEVANT EMAIL HISTORY:\n" + "\n---\n".join(memories))

    pipeline = get_pipeline_summary(user_id)
    context_parts.append(f"DEAL PIPELINE SUMMARY:\n{json.dumps(pipeline)}")

    style_prompt = get_style_prompt(user_id)

    system_prompt = f"""You are an intelligent email relationship OS and personal assistant for a creator/freelancer.

You have access to their inbox history, contact intelligence, campaign data, and deal pipeline.
Your job is to help them manage inbound/outbound email, track brand deals, and understand their relationships.

{style_prompt}

When generating email drafts, match the user's voice exactly.
Be concise, actionable, and direct. No fluff.

CONTEXT:
{chr(10).join(context_parts)}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": req.message}
        ]
    )

    return {"response": response.choices[0].message.content}


# ──────────────────────────────────────────────
# SEMANTIC SEARCH
# ──────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: int = 5

@app.post("/search")
def semantic_search_endpoint(req: SearchRequest, user_id: str = Depends(get_current_user)):
    embedding = create_embedding(req.query)
    results = semantic_search(user_id, embedding, limit=req.limit)
    return {"results": results}


# ──────────────────────────────────────────────
# WEBSOCKET (real-time daemon events)
# ──────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_token = websocket.cookies.get("session_token")
    try:
        payload = verify_session_jwt(session_token)
        user_id = payload["sub"]
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Keep alive; events are pushed via manager.broadcast()
            await asyncio.sleep(30)
            await websocket.send_json({"event": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)


# ──────────────────────────────────────────────
# ANALYTICS
# ──────────────────────────────────────────────

@app.get("/analytics/overview")
def analytics_overview(user_id: str = Depends(get_current_user)):
    with db_cursor(dict_rows=True) as cur:
        cur.execute("SELECT COUNT(*) as total FROM emails WHERE user_id = %s", (user_id,))
        total_emails = cur.fetchone()["total"]

        cur.execute(
            "SELECT category, COUNT(*) as count FROM emails WHERE user_id = %s GROUP BY category",
            (user_id,)
        )
        by_category = {r["category"]: r["count"] for r in cur.fetchall()}

        cur.execute("SELECT COUNT(*) as total FROM contact_profiles WHERE user_id = %s", (user_id,))
        total_contacts = cur.fetchone()["total"]

    pipeline = get_pipeline_summary(user_id)

    return {
        "total_emails": total_emails,
        "emails_by_category": by_category,
        "total_contacts": total_contacts,
        "pipeline": pipeline,
        "top_contacts": get_top_contacts(user_id, limit=5)
    }
