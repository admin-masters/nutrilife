import json, time, logging, os
from django.utils.deprecation import MiddlewareMixin
from django.utils.timezone import now

log = logging.getLogger("request")
REDACT = os.getenv("REDACT_PII_IN_LOGS","1") == "1"
LOG_REQUESTS = os.getenv("LOG_REQUESTS","1") == "1"

REDACT_KEYS = {"password","parent_phone_e164","phone","to_phone_e164","email"}

def _scrub(d: dict):
    if not REDACT or not d: return d
    out = {}
    for k,v in d.items():
        if k.lower() in REDACT_KEYS:
            out[k] = "***redacted***"
        else:
            out[k] = v
    return out

class RequestLogMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not LOG_REQUESTS: return
        request._ts = time.time()

    def process_response(self, request, response):
        if not LOG_REQUESTS: return response
        try:
            dur = time.time() - getattr(request, "_ts", time.time())
            u = getattr(request, "user", None)
            org = getattr(request, "org", None)
            payload = {
                "ts": now().isoformat(),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": int(dur*1000),
                "user": (u.email if u and u.is_authenticated else None),
                "org": (org.id if org else None),
                "ip": request.META.get("REMOTE_ADDR"),
                "ua": request.META.get("HTTP_USER_AGENT",""),
            }
            # Only log POST bodies minimally
            if request.method in ("POST","PUT","PATCH"):
                payload["body_keys"] = list(getattr(request, "POST", {}).keys())
            log.info(json.dumps(payload))
        except Exception:
            pass
        return response
