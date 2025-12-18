import hmac, hashlib, os, json
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import MessageLog
from .i18n import flags_to_text, choose_language
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from urllib.parse import quote

VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN","")
APP_SECRET = os.getenv("WA_APP_SECRET","")

def _verify_signature(request):
    if not APP_SECRET:
        return True
    signature = request.headers.get("X-Hub-Signature-256","").replace("sha256=","")
    digest = hmac.new(APP_SECRET.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, digest)

@csrf_exempt
def wa_webhook(request):
    # GET: verification
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge or "")
        return HttpResponseForbidden("Verification failed")

    # POST: events
    if request.method == "POST":
        if not _verify_signature(request):
            return HttpResponseForbidden("Invalid signature")
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return HttpResponse(status=400)

        # Iterate status updates (Meta format)
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status in value.get("statuses", []):
                    msg_id = status.get("id") or ""
                    wa_status = (status.get("status") or "").lower()
                    error = status.get("errors", [{}])[0] if status.get("errors") else {}

                    try:
                        log = MessageLog.objects.get(provider_msg_id=msg_id)
                    except MessageLog.DoesNotExist:
                        continue

                    if wa_status == "sent":
                        log.status = MessageLog.Status.SENT
                    elif wa_status == "delivered":
                        log.status = MessageLog.Status.DELIVERED
                    elif wa_status == "read":
                        log.status = MessageLog.Status.READ
                    elif wa_status == "failed":
                        log.status = MessageLog.Status.FAILED
                        log.error_code = str(error.get("code",""))
                        log.error_title = error.get("title","")
                    else:
                        # unknown state; do not regress
                        pass
                    log.updated_at = timezone.now()
                    log.save(update_fields=["status","error_code","error_title","updated_at"])
        return JsonResponse({"ok": True})
    return HttpResponse(status=405)

def _digits_only(phone_e164: str) -> str:
    return "".join([c for c in (phone_e164 or "") if c.isdigit()])

def _wa_link(phone_e164: str, text: str) -> str:
    digits = _digits_only(phone_e164)
    return f"https://wa.me/{digits}?text={quote(text)}"

def whatsapp_preview(request, log_id: int):
    """
    Interstitial page that (a) shows the pre-filled message, (b) tries to open WhatsApp
    with a single click fallback. Does NOT send anything automatically.
    """
    log = get_object_or_404(MessageLog, pk=log_id)
    payload = log.payload or {}

    # Build the prefilled text ONLY from current payload + links
    if log.template_code == "RED_EDU_V1":
        body = (payload.get("_components", {}) or {}).get("body") or []
        text = "\n".join([str(x) for x in body if x])
    elif log.template_code == "RED_ASSIST_V1":
        # flags humanization (no payload change)
        try:
            s = log.related_screening
            lang = choose_language(
                getattr(getattr(s.student, "primary_guardian", None), "preferred_language", None),
                getattr(s.organization, "locale", None)
            )
            flags_txt = flags_to_text(payload.get("flags", []), lang)
        except Exception:
            flags_txt = ", ".join(payload.get("flags", []))
        text = "\n".join([
            flags_txt,
            payload.get("video", "") or "",
            payload.get("apply_url", "") or "",
        ]).strip()
    else:
        text = json.dumps(payload)  # fallback (not expected for this flow)

    wa_url = _wa_link(log.to_phone_e164, text)
    # By default return to screening result; allow override with ?next=
    next_url = request.GET.get("next")
    if not next_url and log.related_screening_id:
        next_url = reverse("screening_result", args=[log.related_screening_id])
    next_url = next_url or "/"

    return render(request, "screening/whatsapp_preview.html", {
        "wa_url": wa_url,
        "message_text": text,
        "phone": log.to_phone_e164,
        "template_code": log.template_code,
        "next_url": next_url,
    })