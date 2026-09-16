"""Google OAuth 2.0 (SSO) authentication module for RetailOps."""
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Ephemeral CSRF state store: state -> expiry_timestamp
_STATES: Dict[str, float] = {}
STATE_TTL_SECONDS = 900  # 15 minutes


def _clean_env(name: str) -> str:
    """Read env var, stripping whitespace, surrounding quotes or template brackets."""
    val = os.getenv(name, "").strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1].strip()
    if val.startswith('<') and val.endswith('>'):
        val = val[1:-1].strip()
    return val


def is_google_auth_configured() -> bool:
    """Check if Google OAuth 2.0 credentials are present in the environment."""
    client_id = _clean_env("GOOGLE_CLIENT_ID")
    client_secret = _clean_env("GOOGLE_CLIENT_SECRET")
    return bool(client_id and client_secret)



def create_state() -> str:
    """Generate and store a single-use random state token for CSRF protection."""
    now = time.time()
    # Clean up expired states
    expired = [k for k, exp in _STATES.items() if exp < now]
    for k in expired:
        _STATES.pop(k, None)

    token = secrets.token_urlsafe(24)
    _STATES[token] = now + STATE_TTL_SECONDS
    return token


def verify_and_consume_state(state: Optional[str]) -> bool:
    """Verify that state exists and has not expired, then immediately invalidate it."""
    if not state or not isinstance(state, str):
        return False
    now = time.time()
    exp = _STATES.pop(state, None)
    if exp is None:
        return False
    return exp >= now


def get_google_auth_url(origin: str, state: str) -> str:
    """Construct Google OAuth 2.0 authorization URL."""
    client_id = _clean_env("GOOGLE_CLIENT_ID")
    redirect_uri = f"{origin.rstrip('/')}/auth/google/callback"
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def exchange_code_for_user_info(code: str, origin: str) -> Dict[str, str]:
    """Exchange authorization code with Google and retrieve user profile info."""
    client_id = _clean_env("GOOGLE_CLIENT_ID")
    client_secret = _clean_env("GOOGLE_CLIENT_SECRET")
    redirect_uri = f"{origin.rstrip('/')}/auth/google/callback"

    token_url = "https://oauth2.googleapis.com/token"
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=token_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "RetailOps-Auth/1.0")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_res = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        logger.error(f"Google token exchange failed: {e.code} - {err_body}")
        raise ValueError(f"Không thể xác thực mã với Google: {e.code}") from None
    except Exception as e:
        logger.error(f"Google token exchange connection error: {e}")
        raise ValueError("Lỗi kết nối tới máy chủ xác thực Google.") from None

    access_token = token_res.get("access_token")
    if not access_token:
        raise ValueError("Google không trả về access_token hợp lệ.")

    # Retrieve user profile using access token
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    user_req = urllib.request.Request(userinfo_url, method="GET")
    user_req.add_header("Authorization", f"Bearer {access_token}")
    user_req.add_header("User-Agent", "RetailOps-Auth/1.0")

    try:
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            profile = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Google userinfo request failed: {e}")
        raise ValueError("Không lấy được thông tin người dùng từ Google.") from None

    email = profile.get("email", "").strip().lower()
    if not email:
        raise ValueError("Tài khoản Google không cung cấp email.")

    return {
        "email": email,
        "name": profile.get("name", "").strip() or email.split("@")[0],
        "sub": str(profile.get("sub", "")),
        "picture": profile.get("picture", ""),
    }


def resolve_role_from_email(email: str) -> str:
    """Smart Role Mapping: Map email to 'manager', 'staff', or 'customer'."""
    clean = email.strip().lower()
    staff_str = _clean_env("STAFF_EMAILS")
    manager_str = _clean_env("MANAGER_EMAILS")
    staff_emails = [e.strip().lower() for e in staff_str.split(",") if e.strip()]
    manager_emails = [e.strip().lower() for e in manager_str.split(",") if e.strip()]

    if clean in manager_emails:
        return "manager"
    if clean in staff_emails:
        return "staff"
    return _clean_env("DEFAULT_ROLE") or "customer"

