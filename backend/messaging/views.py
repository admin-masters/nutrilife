import hmac, hashlib, os, json
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import MessageLog

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
