import json
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class GoogleOAuthError(Exception):
    pass


def _http_post_form(url: str, data: Dict[str, str], timeout: int = 15) -> Dict[str, Any]:
    body = urlencode(data).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        raise GoogleOAuthError(f"HTTPError {e.code} from Google token endpoint: {raw}")
    except URLError as e:
        raise GoogleOAuthError(f"URLError contacting Google token endpoint: {e}")


def _http_get_json(url: str, params: Dict[str, str], timeout: int = 15) -> Dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    req = Request(full_url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        raise GoogleOAuthError(f"HTTPError {e.code} from Google tokeninfo endpoint: {raw}")
    except URLError as e:
        raise GoogleOAuthError(f"URLError contacting Google tokeninfo endpoint: {e}")


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        # you can add "access_type": "online" or "offline" if you need refresh tokens
        "access_type": "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_id_token(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    token_resp = _http_post_form(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    id_token = token_resp.get("id_token")
    if not id_token:
        raise GoogleOAuthError(f"No id_token in token response: {token_resp}")
    return id_token


def verify_id_token_and_get_email(
    *,
    id_token: str,
    client_id: str,
) -> Dict[str, Any]:
    """
    Uses Google's tokeninfo endpoint to validate and decode the ID token.

    Returns the decoded payload including 'email', 'email_verified', 'name', etc.
    """
    info = _http_get_json(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
    aud = info.get("aud")
    if aud != client_id:
        raise GoogleOAuthError(f"Invalid token audience. Expected {client_id}, got {aud}")

    if str(info.get("email_verified", "")).lower() not in ("true", "1", "yes"):
        raise GoogleOAuthError("Google account email is not verified.")

    email = info.get("email")
    if not email:
        raise GoogleOAuthError("No email found in Google token payload.")

    return info
