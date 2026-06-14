import os
from datetime import datetime, timedelta, timezone

import jwt
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from db import db_cursor

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
SESSION_TTL_DAYS = 30

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.modify",
]

_fernet = Fernet(os.getenv("ENCRYPTION_KEY").encode())


# ==============================
# GOOGLE OAUTH
# ==============================
def get_google_auth_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def exchange_code_for_tokens(code: str) -> dict:
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_google_userinfo(access_token: str) -> dict:
    resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ==============================
# SUPABASE AUTH USER LOOKUP / CREATION
# ==============================
def find_or_create_supabase_user(email: str) -> str:
    """Returns the Supabase auth.users id (uuid str) for this email,
    creating the user via the Admin API if it doesn't exist yet."""
    with db_cursor() as cur:
        cur.execute("select id from auth.users where email = %s", (email,))
        row = cur.fetchone()
        if row:
            return str(row[0])

    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        },
        json={"email": email, "email_confirm": True},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


# ==============================
# ENCRYPTED TOKEN STORAGE
# ==============================
def save_oauth_tokens(user_id: str, google_email: str, token_response: dict):
    encrypted_refresh = _fernet.encrypt(token_response["refresh_token"].encode()).decode()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_response.get("expires_in", 3600))

    with db_cursor(commit=True) as cur:
        cur.execute("""
            insert into oauth_tokens (
                user_id, provider, google_email, encrypted_refresh_token,
                access_token, access_token_expires_at, scopes, updated_at
            )
            values (%s, 'google', %s, %s, %s, %s, %s, now())
            on conflict (user_id) do update set
                google_email = excluded.google_email,
                encrypted_refresh_token = excluded.encrypted_refresh_token,
                access_token = excluded.access_token,
                access_token_expires_at = excluded.access_token_expires_at,
                scopes = excluded.scopes,
                updated_at = now()
        """, (
            user_id, google_email, encrypted_refresh,
            token_response.get("access_token"), expires_at, token_response.get("scope"),
        ))


def get_gmail_service_for_user(user_id: str):
    """Build an authenticated Gmail API client for this user, refreshing
    the access token if needed and persisting the refreshed token."""
    with db_cursor() as cur:
        cur.execute("""
            select encrypted_refresh_token, access_token
            from oauth_tokens where user_id = %s
        """, (user_id,))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"No Gmail credentials stored for user {user_id}")

    encrypted_refresh, access_token = row
    refresh_token = _fernet.decrypt(encrypted_refresh.encode()).decode()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES,
    )

    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
        with db_cursor(commit=True) as cur:
            cur.execute("""
                update oauth_tokens
                set access_token = %s, access_token_expires_at = %s, updated_at = now()
                where user_id = %s
            """, (creds.token, creds.expiry, user_id))

    return build("gmail", "v1", credentials=creds)


# ==============================
# SESSION JWT
# ==============================
def create_session_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_session_jwt(token: str) -> dict:
    """Returns the decoded payload, or raises jwt.PyJWTError if invalid/expired."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
