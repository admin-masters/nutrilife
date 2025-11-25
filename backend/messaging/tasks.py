import logging, time
from celery import shared_task
from django.utils import timezone
from .models import MessageLog

from .i18n import to_provider_lang, choose_language

from .services import TEMPLATE_NAME

log = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=5, default_retry_delay=30)  # ~ exponential-ish backoff
def send_message_task(self, message_id: int):
    from .services import _provider
    try:
        msg = MessageLog.objects.get(id=message_id)
    except MessageLog.DoesNotExist:
        return "gone"

    if msg.status in ("SENT","DELIVERED","READ"):
        return "already sent"

    # prov = _provider()
    # lang_code = to_provider_lang(msg.language)
    # components = msg.payload.get("_components") or {}  # we will stash components before queueing
    prov = _provider()
    lang_code = to_provider_lang(msg.language)
    components = msg.payload.get("_components") or {}
    # Resolve the actual template name for the provider
    tpl = TEMPLATE_NAME.get(msg.template_code, msg.template_code)

    try:
        #pid, pstatus = prov.send_template(msg.to_phone_e164, msg.template_code if msg.template_code in ("COMPLIANCE_REMINDER_V1","nutrilift_compliance_reminder_v1") else msg.template_code, lang_code, components)
        pid, pstatus = prov.send_template(
            msg.to_phone_e164,
            tpl,           # e.g., "nutrilift_redflag_edu_v1"
            lang_code,     # "en" | "hi"
            components
        )
        msg.provider_msg_id = pid
        msg.status = MessageLog.Status.SENT if str(pstatus).lower() == "sent" else MessageLog.Status.QUEUED
        msg.sent_at = timezone.now()
        msg.save(update_fields=["provider_msg_id","status","sent_at","updated_at"])
        return "ok"
    except Exception as e:
        log.warning("send_message_task error: %s", e)
        raise self.retry(exc=e, countdown=min(300, (self.request.retries+1)*30))
