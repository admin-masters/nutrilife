import os
from typing import Dict, Tuple
from django.utils import timezone
from accounts.models import Organization
from roster.models import Guardian
from screening.models import Screening
from .models import MessageLog
from .i18n import choose_language, flags_to_text, edu_video_url, assist_apply_url
import hashlib
from django.db import transaction
from .ratelimit import check_global_per_min, check_per_phone_daily, RateLimitExceeded
import uuid
# provider picker
def _provider():
    prov = (os.getenv("WHATSAPP_PROVIDER") or "mock").lower()
    if prov == "meta":
        from .providers.meta_cloud import MetaCloudProvider
        return MetaCloudProvider()
    elif prov == "aisensy":
        from .providers.aisensy import AiSensyProvider
        return AiSensyProvider()
    else:
        from .providers.mock import MockProvider
        return MockProvider()

# Map our internal codes to WABA template names
TEMPLATE_NAME = {
    "RED_EDU_V1": "nutrilift_redflag_edu_v1",
    "RED_ASSIST_V1": "nutrilift_redflag_assist_v1",
}

# Map language shortcut to WABA language codes
LANG_CODE = {
    "en": "en",    # you may use en_US if that is how the template was approved
    "hi": "hi",
    "local": "en", # fallback; you can add actual local (e.g., "mr") once approved
}

def _guardian_and_phone(screening: Screening):
    g = screening.student.primary_guardian
    return g, (g.phone_e164 if g else "")

# def _make_idem_key(*parts):
#     raw = "|".join(str(p) for p in parts)
#     return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:60]

def _make_idem_key(*parts):
    raw = "|".join(str(p) for p in parts)
    # Deterministic 36-char key that fits CharField(max_length=36)
    # UUIDv5 is stable for the same input and namespace
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

def _click_to_chat_text(body_lines: list[str]) -> str:
    """Join body lines for pre-filled WhatsApp text (simple, readable)."""
    return "\n".join([str(x) for x in body_lines if x])

def prepare_redflag_education_click_to_chat(screening: Screening):
    """
    Build the SAME payload as RED_EDU_V1, log it, DO NOT send.
    Return (MessageLog, prefilled_text).
    """
    org: Organization = screening.organization
    guardian, phone = _guardian_and_phone(screening)
    if not phone:
        raise ValueError("Missing guardian phone")
    lang = choose_language(getattr(guardian, "preferred_language", None), getattr(org, "locale", None))
    flags_txt = flags_to_text(screening.red_flags, lang)
    video = edu_video_url(lang)

    components = {
        "body": [screening.student.full_name, flags_txt, video],
        "buttons": [video],
    }

    idem = _make_idem_key("red_edu", phone, screening.id)
    existing = MessageLog.objects.filter(idempotency_key=idem).first()
    if existing:
        body = (existing.payload or {}).get("_components", {}).get("body") or components["body"]
        return existing, _click_to_chat_text(body)

    # Rate limiting (same as send)
    check_global_per_min()
    check_per_phone_daily(phone, "RED_EDU_V1")

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=phone,
        template_code="RED_EDU_V1",
        language=lang,
        payload={
            "screening_id": screening.id,
            "flags": screening.red_flags,
            "video": video,
            "_components": components,
        },
        related_screening=screening,
        idempotency_key=idem,
        status=MessageLog.Status.QUEUED,
    )
    return log, _click_to_chat_text(components["body"])

def prepare_redflag_assistance_click_to_chat(screening: Screening):
    """
    Build the SAME payload as RED_ASSIST_V1, log it, DO NOT send.
    Return (MessageLog, prefilled_text).
    """
    org: Organization = screening.organization
    guardian, phone = _guardian_and_phone(screening)
    if not phone:
        raise ValueError("Missing guardian phone")
    lang = choose_language(getattr(guardian, "preferred_language", None), getattr(org, "locale", None))
    flags_txt = flags_to_text(screening.red_flags, lang)
    video = edu_video_url(lang)
    apply_url = assist_apply_url(screening.student_id, screening.id, lang)

    # NOTE: We do NOT alter payload shape; _components is not stored for ASSIST per current code.
    idem = _make_idem_key("red_assist", phone, screening.id)
    existing = MessageLog.objects.filter(idempotency_key=idem).first()
    if existing:
        payload = existing.payload or {}
        body = [flags_txt, payload.get("video", ""), payload.get("apply_url", "")]
        return existing, _click_to_chat_text(body)

    # Rate limiting (same as send)
    check_global_per_min()
    check_per_phone_daily(phone, "RED_ASSIST_V1")

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=phone,
        template_code="RED_ASSIST_V1",
        language=lang,
        payload={
            "screening_id": screening.id,
            "flags": screening.red_flags,
            "video": video,
            "apply_url": apply_url,
        },
        related_screening=screening,
        idempotency_key=idem,
        status=MessageLog.Status.QUEUED,
    )
    # Pre-filled WhatsApp text uses only current payload fields/links
    return log, _click_to_chat_text([flags_txt, video, apply_url])

@transaction.atomic
def send_redflag_education(screening):
    org = screening.organization
    guardian, phone = _guardian_and_phone(screening)
    if not phone:
        raise ValueError("Missing guardian phone")
    lang = choose_language(getattr(guardian,"preferred_language",None), getattr(org,"locale",None))
    flags_txt = flags_to_text(screening.red_flags, lang)
    video = edu_video_url(lang)

    components = {
        "body": [screening.student.full_name, flags_txt, video],
        "buttons": [video],
    }

    idem = _make_idem_key("red_edu", phone, screening.id)
    # Idempotency shortcut: if exists -> return
    existing = MessageLog.objects.filter(idempotency_key=idem).first()
    if existing:
        return existing

    # Rate limiting
    check_global_per_min()
    check_per_phone_daily(phone, "RED_EDU_V1")

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=phone,
        template_code="RED_EDU_V1",
        language=lang,
        payload={"screening_id": screening.id, "flags": screening.red_flags, "video": video, "_components": components},
        related_screening=screening,
        idempotency_key=idem,
        status=MessageLog.Status.QUEUED
    )
    from .tasks import send_message_task  # local import breaks the cycle
    send_message_task.delay(log.id)
    return log


def send_redflag_assistance(screening: Screening) -> MessageLog:
    org: Organization = screening.organization
    guardian, phone = _guardian_and_phone(screening)
    lang = choose_language(getattr(guardian,"preferred_language",None), getattr(org,"locale",None))
    flags_txt = flags_to_text(screening.red_flags, lang)
    video = edu_video_url(lang)
    apply_url = assist_apply_url(screening.student_id, screening.id, lang)

    components = {
        "body": [
            screening.student.full_name,  # {{1}}
            flags_txt,                    # {{2}}
            video,                        # {{3}}
            apply_url                     # {{4}}
        ],
        "buttons": [video, apply_url]     # Button 0 -> video, Button 1 -> apply
    }

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=phone,
        template_code="RED_ASSIST_V1",
        language=lang,
        payload={"screening_id": screening.id, "flags": screening.red_flags, "video": video, "apply_url": apply_url},
        related_screening=screening,
        status=MessageLog.Status.QUEUED
    )

    prov = _provider()
    msg_id, pstatus = prov.send_template(phone, TEMPLATE_NAME["RED_ASSIST_V1"], LANG_CODE[lang], components)
    log.provider_msg_id = msg_id
    log.status = MessageLog.Status.SENT if pstatus.lower() == "sent" else MessageLog.Status.QUEUED
    log.sent_at = timezone.now()
    log.save(update_fields=["provider_msg_id","status","sent_at","updated_at"])
    return log

# add to TEMPLATE_NAME mapping 
TEMPLATE_NAME.update({
    "COMPLIANCE_REMINDER_V1": "nutrilift_compliance_reminder_v1",  # name in your WABA
}) 

def send_compliance_reminder(supply) -> MessageLog:
    """
    Sends a WhatsApp reminder to complete Day-27 compliance.
    """
    from django.urls import reverse
    from django.conf import settings
    from roster.models import Guardian

    org = supply.enrollment.organization
    student = supply.enrollment.student
    guardian = student.primary_guardian
    phone = guardian.phone_e164 if guardian else ""

    base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    link = f"{base}{reverse('program:compliance_form', args=[supply.qr_token])}"

    lang = choose_language(getattr(guardian, "preferred_language", None), getattr(org, "locale", None))
    components = {
        # Adjust placeholders to your approved WABA template
        "body": [
            student.full_name,  # {{1}} Child Name
            link,               # {{2}} Link to compliance form
        ],
        "buttons": [link],     # URL button 0 -> {{1}} dynamic URL
    }

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=phone,
        template_code="COMPLIANCE_REMINDER_V1",
        language=lang,
        payload={"supply_id": supply.id, "student": student.full_name, "link": link},
        related_supply=supply,
        status=MessageLog.Status.QUEUED,
    )

    prov = _provider()
    msg_id, pstatus = prov.send_template(phone, TEMPLATE_NAME["COMPLIANCE_REMINDER_V1"], LANG_CODE[lang], components)
    log.provider_msg_id = msg_id
    log.status = MessageLog.Status.SENT if pstatus.lower() == "sent" else MessageLog.Status.QUEUED
    log.sent_at = timezone.now()
    log.save(update_fields=["provider_msg_id","status","sent_at","updated_at"])
    return log

# @transaction.atomic
# def send_redflag_assistance(screening: Screening) -> MessageLog:
#     org: Organization = screening.organization
#     guardian, phone = _guardian_and_phone(screening)
#     if not phone:
#         raise ValueError("Missing guardian phone")

#     lang = choose_language(getattr(guardian, "preferred_language", None),
#                            getattr(org, "locale", None))
#     flags_txt = flags_to_text(screening.red_flags, lang)
#     video = edu_video_url(lang)
#     apply_url = assist_apply_url(screening.student_id, screening.id, lang)

#     components = {
#         "body": [
#             screening.student.full_name,  # {{1}}
#             flags_txt,                    # {{2}}
#             video,                        # {{3}}
#             apply_url                     # {{4}}
#         ],
#         "buttons": [video, apply_url]     # Button 0 -> video, Button 1 -> apply
#     }

#     # --- Idempotency ---
#     idem = _make_idem_key("red_assist", phone, screening.id)
#     existing = MessageLog.objects.filter(idempotency_key=idem).first()
#     if existing:
#         return existing

#     # --- Rate limiting ---
#     check_global_per_min()
#     check_per_phone_daily(phone, "RED_ASSIST_V1")

#     log = MessageLog.objects.create(
#         organization=org,
#         to_phone_e164=phone,
#         template_code="RED_ASSIST_V1",
#         language=lang,
#         payload={
#             "screening_id": screening.id,
#             "flags": screening.red_flags,
#             "video": video,
#             "apply_url": apply_url,
#             "_components": components,
#         },
#         related_screening=screening,
#         idempotency_key=idem,
#         status=MessageLog.Status.QUEUED,
#     )

#     from .tasks import send_message_task  # local import to avoid cycle
#     send_message_task.delay(log.id)
#     return log

# @transaction.atomic
# def send_compliance_reminder(supply) -> MessageLog:
#     """
#     Sends a WhatsApp reminder to complete Day-27 compliance.
#     """
#     from django.urls import reverse

#     org = supply.enrollment.organization
#     student = supply.enrollment.student
#     guardian = student.primary_guardian
#     phone = guardian.phone_e164 if guardian else ""
#     if not phone:
#         raise ValueError("Missing guardian phone")

#     base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
#     link = f"{base}{reverse('program:compliance_form', args=[supply.qr_token])}"

#     lang = choose_language(getattr(guardian, "preferred_language", None),
#                            getattr(org, "locale", None))

#     components = {
#         # Adjust placeholders to your approved WABA template
#         "body": [
#             student.full_name,  # {{1}} Child Name
#             link,               # {{2}} Link to compliance form
#         ],
#         "buttons": [link],     # URL button 0 -> {{1}} dynamic URL
#     }

#     # --- Idempotency ---
#     # Keyed by phone + supply so one reminder per supply per guardian is de-duped.
#     idem = _make_idem_key("compliance_reminder", phone, supply.id)
#     existing = MessageLog.objects.filter(idempotency_key=idem).first()
#     if existing:
#         return existing

#     # --- Rate limiting ---
#     check_global_per_min()
#     check_per_phone_daily(phone, "COMPLIANCE_REMINDER_V1")

#     log = MessageLog.objects.create(
#         organization=org,
#         to_phone_e164=phone,
#         template_code="COMPLIANCE_REMINDER_V1",
#         language=lang,
#         payload={
#             "supply_id": supply.id,
#             "student": student.full_name,
#             "link": link,
#             "_components": components,
#         },
#         related_supply=supply,
#         idempotency_key=idem,
#         status=MessageLog.Status.QUEUED,
#     )

#     from .tasks import send_message_task  # local import to avoid cycle
#     send_message_task.delay(log.id)
#     return log
