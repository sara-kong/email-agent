import sys
import os
sys.path.insert(0, os.path.abspath("."))

import json
import asyncio
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Internal modules ──────────────────────────────────────────
from gmail_utils import get_gmail_service, fetch_full_email, fetch_thread
from memory import (
    save_email, email_exists, semantic_search,
    get_thread_summary, save_thread_summary,
    upsert_contact, upsert_thread
)
from embeddings import create_embedding
from classifier import classify_email
from responder import generate_reply
from draft_creator import create_draft
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
from outbound import generate_outreach_email


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

# WebSocket connection manager for real-time events
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

# Gmail service (lazy-loaded)
_gmail_service = None
def get_service():
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = get_gmail_service()
    return _gmail_service


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_campaign_tables()
    init_contact_intelligence_tables()
    init_style_table()
    print("✔ API server started")


# ──────────────────────────────────────────────
# HEALTH
# ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ──────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────

@app.get("/auth/status")
def auth_status():
    try:
        svc = get_service()
        profile = svc.users().getProfile(userId="me").execute()
        return {"authenticated": True, "email": profile.get("emailAddress")}
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


# ──────────────────────────────────────────────
# INBOX
# ──────────────────────────────────────────────

class ProcessInboxRequest(BaseModel):
    max_results: int = 10
    label_ids: list[str] = ["INBOX"]

@app.post("/inbox/process")
async def process_inbox(req: ProcessInboxRequest, background_tasks: BackgroundTasks):
    """Trigger inbox processing in the background."""
    background_tasks.add_task(_process_inbox_task, req.max_results, req.label_ids)
    return {"status": "processing_started", "max_results": req.max_results}


async def _process_inbox_task(max_results: int, label_ids: list[str]):
    """Background task: fetch, classify, embed, and store emails."""
    from gmail_utils import fetch_emails

    service = get_service()
    emails, _ = fetch_emails(service, max_results=max_results)

    for email in emails:
        gmail_id = email["id"]
        if email_exists(gmail_id):
            continue

        email_data = fetch_full_email(service, gmail_id)
        thread_id = email_data["thread_id"]
        sender = email_data["sender"]
        subject = email_data["subject"]
        snippet = email_data["snippet"]
        email_text = email_data["email_text"]

        embedding = create_embedding(email_text)
        classification = classify_email(email_text)
        label = classification.get("label", "unknown")
        action = classification.get("suggested_action", "ignore")
        score = classification.get("importance_score", 0)

        existing_summary = get_thread_summary(thread_id)
        updated_summary = summarize_thread(existing_summary, email_text)
        save_thread_summary(thread_id, updated_summary)

        save_email(
            gmail_id, thread_id, sender, subject, snippet,
            email_text, json.dumps(embedding),
            label, action, str(score), updated_summary
        )

        upsert_contact_profile(email=sender, name=sender, received=True)
        upsert_thread(thread_id, subject, sender, snippet)

        # Reply detection for campaigns
        check_if_campaign_reply(sender, gmail_id)

        await manager.broadcast({
            "event": "new_email",
            "gmail_id": gmail_id,
            "sender": sender,
            "subject": subject,
            "label": label,
            "action": action
        })


@app.get("/inbox/emails")
def list_emails(
    limit: int = 20,
    label: Optional[str] = None,
    sender: Optional[str] = None
):
    import sqlite3
    conn = sqlite3.connect("memory.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = "SELECT * FROM emails WHERE 1=1"
    params = []
    if label:
        query += " AND category = ?"
        params.append(label)
    if sender:
        query += " AND sender LIKE ?"
        params.append(f"%{sender}%")
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return {"emails": [dict(r) for r in rows]}


@app.get("/inbox/emails/{gmail_id}")
def get_email(gmail_id: str):
    import sqlite3
    conn = sqlite3.connect("memory.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM emails WHERE gmail_id = ?", (gmail_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    return dict(row)


# ──────────────────────────────────────────────
# REPLY / DRAFT GENERATION
# ──────────────────────────────────────────────

class GenerateReplyRequest(BaseModel):
    gmail_id: str
    email_text: str
    thread_summary: Optional[str] = ""
    auto_send: bool = False

@app.post("/inbox/reply")
def generate_reply_endpoint(req: GenerateReplyRequest):
    embedding = create_embedding(req.email_text)
    memory_context = "\n\n".join(semantic_search(embedding, limit=3))
    style_prompt = get_style_prompt()

    reply = generate_reply(req.email_text, req.thread_summary or "", memory_context, style_prompt)

    if req.auto_send:
        # Create a Gmail draft
        import sqlite3
        conn = sqlite3.connect("memory.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT sender, subject FROM emails WHERE gmail_id = ?", (req.gmail_id,))
        row = c.fetchone()
        conn.close()
        if row:
            create_draft(get_service(), row["sender"], row["subject"], reply)

    return {"reply": reply, "draft_created": req.auto_send}


# ──────────────────────────────────────────────
# CONTACTS
# ──────────────────────────────────────────────

@app.get("/contacts")
def contacts(
    limit: int = 50,
    contact_type: Optional[str] = None,
    vip_only: bool = False,
    q: Optional[str] = None
):
    if q:
        return {"contacts": search_contacts(q)}
    if vip_only:
        return {"contacts": get_vip_contacts()}
    if contact_type:
        return {"contacts": get_contacts_by_type(contact_type)}
    return {"contacts": get_top_contacts(limit=limit)}


@app.get("/contacts/{email}")
def get_contact_endpoint(email: str):
    contact = get_contact(email)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    deals = get_deal_by_contact(email)
    contact["deals"] = deals
    return contact


class VIPRequest(BaseModel):
    email: str
    reason: str = ""

@app.post("/contacts/vip")
def mark_vip(req: VIPRequest):
    set_vip(req.email, req.reason)
    return {"status": "ok"}


class CategorizeRequest(BaseModel):
    email: str

@app.post("/contacts/{email}/categorize")
def categorize_contact(email: str, background_tasks: BackgroundTasks):
    """Trigger AI categorization for a contact."""
    import sqlite3
    conn = sqlite3.connect("memory.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT full_text FROM emails WHERE sender LIKE ? ORDER BY id DESC LIMIT 5",
        (f"%{email}%",)
    )
    rows = c.fetchall()
    conn.close()
    recent = [r["full_text"] for r in rows]
    result = ai_categorize_contact(email, recent)
    return result


@app.post("/contacts/scores/refresh")
def refresh_scores(background_tasks: BackgroundTasks):
    background_tasks.add_task(refresh_all_scores)
    return {"status": "refresh_started"}


# ──────────────────────────────────────────────
# CAMPAIGNS
# ──────────────────────────────────────────────

class CreateCampaignRequest(BaseModel):
    name: str
    goal: str = ""
    contacts: list[str] = []

@app.post("/campaigns")
def create_campaign_endpoint(req: CreateCampaignRequest):
    campaign_id = create_campaign(req.name, req.goal)
    for email in req.contacts:
        add_contact_to_campaign(campaign_id, email)
    return {"campaign_id": campaign_id, "status": "created"}


@app.get("/campaigns")
def list_campaigns_endpoint(status: Optional[str] = None):
    campaigns = list_campaigns(status=status)
    for c in campaigns:
        c["stats"] = get_campaign_stats(c["id"])
    return {"campaigns": campaigns}


@app.get("/campaigns/{campaign_id}")
def get_campaign_endpoint(campaign_id: int):
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign["contacts"] = get_campaign_contacts(campaign_id)
    campaign["stats"] = get_campaign_stats(campaign_id)
    return campaign


class OutboundEmailRequest(BaseModel):
    campaign_id: int
    contact_email: str
    campaign_prompt: str
    send_as_draft: bool = True

@app.post("/campaigns/{campaign_id}/send")
def send_campaign_email(campaign_id: int, req: OutboundEmailRequest):
    """Generate and optionally draft a personalized outbound email."""
    contact = get_contact(req.contact_email)
    if not contact:
        # Minimal contact tuple for backward compat
        contact_tuple = (None, req.contact_email, req.contact_email, "", "", "")
    else:
        contact_tuple = (
            contact.get("id"), contact.get("name", ""),
            contact.get("email"), contact.get("company", ""),
            contact.get("role", ""), contact.get("ai_summary", "")
        )

    style_prompt = get_style_prompt()
    email_body = generate_outreach_email(contact_tuple, req.campaign_prompt, style_prompt)

    if req.send_as_draft:
        subject = f"[Campaign: {campaign_id}] Outreach"
        create_draft(get_service(), req.contact_email, subject, email_body)

    mark_email_sent(campaign_id, req.contact_email)

    return {"email_body": email_body, "draft_created": req.send_as_draft}


class UpdateCampaignStatusRequest(BaseModel):
    status: str  # active | paused | completed

@app.patch("/campaigns/{campaign_id}/status")
def update_campaign(campaign_id: int, req: UpdateCampaignStatusRequest):
    update_campaign_status(campaign_id, req.status)
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
def create_deal_endpoint(req: CreateDealRequest):
    deal_id = create_deal(
        req.contact_email, req.title,
        req.company, req.deal_value, req.notes
    )
    return {"deal_id": deal_id, "status": "created"}


@app.get("/deals")
def list_deals(stage: Optional[str] = None):
    return {"deals": get_deals(stage=stage)}


@app.get("/deals/pipeline")
def pipeline_summary():
    return {"pipeline": get_pipeline_summary(), "stages": DEAL_STAGES}


class AdvanceDealRequest(BaseModel):
    stage: str

@app.patch("/deals/{deal_id}/stage")
def advance_deal(deal_id: int, req: AdvanceDealRequest):
    try:
        advance_deal_stage(deal_id, req.stage)
        return {"status": "updated", "new_stage": req.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AttachThreadRequest(BaseModel):
    thread_id: str

@app.post("/deals/{deal_id}/threads")
def attach_thread(deal_id: int, req: AttachThreadRequest):
    attach_thread_to_deal(deal_id, req.thread_id)
    return {"status": "attached"}


# ──────────────────────────────────────────────
# STYLE PROFILE
# ──────────────────────────────────────────────

@app.get("/style")
def get_style():
    profile = load_style_profile()
    if not profile:
        return {"built": False, "message": "Style profile not yet built. POST /style/build to generate."}
    return {"built": True, "profile": profile}


@app.post("/style/build")
async def rebuild_style(background_tasks: BackgroundTasks):
    """Rebuild the style profile from sent emails (runs in background)."""
    background_tasks.add_task(_build_style_task)
    return {"status": "building", "message": "Style analysis started. Check /style when complete."}


async def _build_style_task():
    service = get_service()
    profile = build_style_profile(service, max_samples=50)
    await manager.broadcast({"event": "style_profile_ready", "profile": profile})


# ──────────────────────────────────────────────
# AGENT CHAT
# ──────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None  # e.g. {"email_id": "...", "contact_email": "..."}

@app.post("/agent/chat")
def agent_chat(req: AgentChatRequest):
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
            import sqlite3
            conn = sqlite3.connect("memory.db")
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM emails WHERE gmail_id = ?", (req.context["email_id"],))
            row = c.fetchone()
            conn.close()
            if row:
                context_parts.append(f"CURRENT EMAIL:\n{dict(row)}")

        if req.context.get("contact_email"):
            contact = get_contact(req.context["contact_email"])
            if contact:
                context_parts.append(f"CONTACT:\n{json.dumps(contact, indent=2)}")

    # Semantic search for relevant memories
    embedding = create_embedding(req.message)
    memories = semantic_search(embedding, limit=3)
    if memories:
        context_parts.append(f"RELEVANT EMAIL HISTORY:\n" + "\n---\n".join(memories))

    pipeline = get_pipeline_summary()
    context_parts.append(f"DEAL PIPELINE SUMMARY:\n{json.dumps(pipeline)}")

    style_prompt = get_style_prompt()

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
def semantic_search_endpoint(req: SearchRequest):
    embedding = create_embedding(req.query)
    results = semantic_search(embedding, limit=req.limit)
    return {"results": results}


# ──────────────────────────────────────────────
# WEBSOCKET (real-time daemon events)
# ──────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep alive; events are pushed via manager.broadcast()
            await asyncio.sleep(30)
            await websocket.send_json({"event": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ──────────────────────────────────────────────
# ANALYTICS
# ──────────────────────────────────────────────

@app.get("/analytics/overview")
def analytics_overview():
    import sqlite3
    conn = sqlite3.connect("memory.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as total FROM emails")
    total_emails = c.fetchone()["total"]

    c.execute("SELECT category, COUNT(*) as count FROM emails GROUP BY category")
    by_category = {r["category"]: r["count"] for r in c.fetchall()}

    c.execute("SELECT COUNT(*) as total FROM contact_profiles")
    total_contacts = c.fetchone()["total"]

    conn.close()

    pipeline = get_pipeline_summary()

    return {
        "total_emails": total_emails,
        "emails_by_category": by_category,
        "total_contacts": total_contacts,
        "pipeline": pipeline,
        "top_contacts": get_top_contacts(limit=5)
    }