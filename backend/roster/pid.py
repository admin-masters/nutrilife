import base64
import hashlib
import hmac
import re
from django.conf import settings

_WS_RE = re.compile(r"\s+")

def _normalize_first_name(first_name: str) -> str:
    """
    Normalize the student name input into the canonical 'first name' used for PID:
    - lowercased
    - trimmed
    - collapse whitespace
    - take FIRST token only (guards against someone typing full name)
    """
    s = (first_name or "").strip().lower()
    s = _WS_RE.sub(" ", s)
    if not s:
        return ""
    return s.split(" ")[0]

def _normalize_phone(phone_e164: str) -> str:
    """
    phone is expected to already be normalized to E.164 by the form.
    """
    return (phone_e164 or "").strip()

def compute_pid(*, first_name: str, phone_e164: str) -> str:
    """
    Deterministic PID = base32(HMAC_SHA256(PID_HMAC_KEY, "<first>|<phone>")) truncated.
    - Non-reversible (unless key is compromised AND attacker brute-forces inputs)
    - Alphanumeric (A-Z + 2-7), no punctuation
    """
    fn = _normalize_first_name(first_name)
    ph = _normalize_phone(phone_e164)

    if not fn or not ph:
        raise ValueError("first_name and phone_e164 are required to compute PID")

    key = (getattr(settings, "PID_HMAC_KEY", "") or "").encode("utf-8")
    if not key:
        raise RuntimeError("settings.PID_HMAC_KEY is not set")

    msg = f"{fn}|{ph}".encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).digest()

    # base32 => [A-Z2-7], strip padding, take 26 chars (~130 bits)
    pid = base64.b32encode(digest).decode("ascii").rstrip("=")
    return pid[:26]
