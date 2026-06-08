from fastapi import FastAPI
from memory import get_all_contacts

from pydantic import BaseModel
from outbound import generate_outreach_email

app = FastAPI()

class CampaignRequest(BaseModel):

    name: str
    email: str
    notes: str
    campaign_prompt: str

@app.get("/")
def home():
    return {"status": "running"}

@app.get("/contacts")
def contacts():

    contacts = get_all_contacts()

    return contacts

@app.post("/generate")
def generate(request: CampaignRequest):

    contact = (
        None,
        request.name,
        request.email,
        "",
        "",
        request.notes
    )

    draft = generate_outreach_email(
        contact,
        request.campaign_prompt
    )

    return {
        "draft": draft
    }
