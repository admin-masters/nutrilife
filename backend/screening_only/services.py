from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.core import signing
from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Organization
from messaging.models import MessageLog
#from messaging.services import click_to_chat_url
from messaging.i18n import flags_to_text
from roster.services import _grades_nursery_to_12
DEFAULT_GRADES=_grades_nursery_to_12()

from screening.models import Screening


PARENT_TOKEN_SALT = "screening_only_parent_v1"
TERMS_VERSION = "v1"

# Academic year configuration (India often June -> May)
ACADEMIC_YEAR_START_MONTH = getattr(settings, "SCREENING_ACADEMIC_YEAR_START_MONTH", 6)


def unique_screening_token(org_name: str) -> str:
    from django.utils.crypto import get_random_string

    base = slugify(org_name)[:48] or "school"
    for _ in range(10):
        token = f"{base}-{get_random_string(8)}"
        if not Organization.objects.filter(screening_link_token=token).exists():
            return token
    # Extremely unlikely
    return f"{base}-{get_random_string(12)}"


def academic_year_label_for_date(d: date, start_month: int = ACADEMIC_YEAR_START_MONTH) -> str:
    if d.month < start_month:
        start_year = d.year - 1
    else:
        start_year = d.year
    end_year = start_year + 1
    return f"{start_year}-{str(end_year)[-2:]}"


def academic_year_range(label: str, start_month: int = ACADEMIC_YEAR_START_MONTH) -> Tuple[datetime, datetime]:
    """
    label like "2024-25" -> returns [2024-06-01 00:00, 2025-06-01 00:00) in server timezone.
    """
    label = (label or "").strip()
    if not label or "-" not in label:
        today = timezone.localdate()
        label = academic_year_label_for_date(today, start_month=start_month)

    start_year_str = label.split("-")[0]
    start_year = int(start_year_str)
    end_year = start_year + 1

    start_dt = datetime(start_year, start_month, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    end_dt = datetime(end_year, start_month, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    return start_dt, end_dt


def available_academic_years(org: Organization, years_back: int = 5) -> List[str]:
    today = timezone.localdate()
    current = academic_year_label_for_date(today)
    # Simple last N options; can be refined if you want min/max from Screening data.
    start_year = int(current.split("-")[0])
    labels = []
    for y in range(start_year - years_back + 1, start_year + 1):
        labels.append(f"{y}-{str(y+1)[-2:]}")
    return list(reversed(labels))


def _grade_rank_map() -> Dict[str, int]:
    # DEFAULT_GRADES includes Nursery, LKG, UKG, 1..12, Other
    ranks = {}
    for idx, g in enumerate(DEFAULT_GRADES):
        ranks[str(g)] = idx
    return ranks


def screening_counts_by_class(org: Organization, start_dt: datetime, end_dt: datetime) -> List[dict]:
    """
    Returns rows like:
      {"grade": "4", "division": "C", "screened_once": 12, "screened_twice": 3, "total_students": 15}
    computed based on number of Screening rows per student in the given range.
    """
    ranks = _grade_rank_map()

    qs = (
        Screening.objects
        .filter(organization=org, screened_at__gte=start_dt, screened_at__lt=end_dt)
        .values(
            "student_id",
            "student__classroom_id",
            "student__classroom__grade",
            "student__classroom__division",
        )
        .annotate(n=Count("id"))
    )

    by_classroom = defaultdict(lambda: {"grade": "", "division": "", "screened_once": 0, "screened_twice": 0, "total_students": 0})
    for row in qs:
        key = row["student__classroom_id"] or 0
        d = by_classroom[key]
        d["grade"] = row["student__classroom__grade"] or ""
        d["division"] = row["student__classroom__division"] or ""
        if row["n"] >= 2:
            d["screened_twice"] += 1
        elif row["n"] == 1:
            d["screened_once"] += 1
        d["total_students"] += 1

    rows = list(by_classroom.values())

    def _sort_key(r: dict):
        g = str(r.get("grade") or "")
        return (ranks.get(g, 10_000), str(r.get("division") or ""))

    rows.sort(key=_sort_key)
    return rows


def build_parent_token(screening_id: int) -> str:
    return signing.dumps({"sid": screening_id}, salt=PARENT_TOKEN_SALT, compress=True)


def parse_parent_token(token: str) -> int:
    data = signing.loads(token, salt=PARENT_TOKEN_SALT)
    return int(data["sid"])


def _local_lang_code_from_org(org: Organization) -> str:
    try:
        prof = org.screening_only_profile
        return (prof.local_language_code or "").strip().lower()
    except Exception:
        return ""


def _resolve_local_lang_for_message(org: Organization) -> str:
    """
    We always send 3 languages per spec: English, Hindi, and local language:contentReference[oaicite:9]{index=9}.
    If local language is unknown/unconfigured, we fallback to 'local' which uses your existing local placeholders.
    """
    code = _local_lang_code_from_org(org)
    if code:
        return code
    return "local"


def _translate_message(lang: str, *, school_name: str, student_name: str, flags_text: str, video_url: str, result_url: str, screened_on: str) -> str:
    """
    Minimal message templates. You can expand translations per lang code as needed.
    """
    lang = (lang or "en").lower()

    # English
    if lang.startswith("en"):
        return (
            f"NUTRILIFT Screening – {school_name} – {screened_on}\n"
            f"Child: {student_name}\n"
            f"Findings: {flags_text}\n\n"
            f"Watch parent education video: {video_url}\n"
            f"View screening result: {result_url}\n\n"
            f"This message is sent by your child's class teacher as part of the school nutrition screening program."
        )

    # Hindi
    if lang.startswith("hi"):
        return (
            f"न्यूट्रिलिफ्ट स्क्रीनिंग – {school_name} – {screened_on}\n"
            f"बच्चे का नाम: {student_name}\n"
            f"निष्कर्ष: {flags_text}\n\n"
            f"अभिभावक शिक्षा वीडियो देखें: {video_url}\n"
            f"स्क्रीनिंग परिणाम देखें: {result_url}\n\n"
            f"यह संदेश स्कूल पोषण स्क्रीनिंग कार्यक्रम के अंतर्गत आपके बच्चे के कक्षा शिक्षक द्वारा भेजा गया है।"
        )

    # Local fallback (can be replaced with real translations)
    return (
        f"NUTRILIFT Screening – {school_name} – {screened_on}\n"
        f"Child: {student_name}\n"
        f"Findings: {flags_text}\n\n"
        f"Watch parent education video: {video_url}\n"
        f"View screening result: {result_url}\n"
    )


def prepare_screening_only_redflag_click_to_chat(request, screening) -> Tuple[Optional[MessageLog], str]:
    """
    For Screening-only orgs: if RED, build a 3-language WhatsApp message and return MessageLog + preview text.
    If not RED: returns (None, "").
    """
    if (screening.risk_level or "").upper() != "RED":
        return None, ""

    guardian = getattr(screening.student, "primary_guardian", None)

    # Fallback: StudentGuardian links
    if guardian is None:
        link = screening.student.guardian_links.select_related("guardian").first()
        guardian = link.guardian if link else None

    if not guardian or not guardian.phone_e164:
        return None, ""

    org = screening.organization
    school_name = org.name or "School"
    student_name = screening.student.full_name or "Student"
    screened_on = timezone.localtime(screening.screened_at).strftime("%Y-%m-%d")

    parent_token = build_parent_token(screening.id)
    video_url = request.build_absolute_uri(f"/screening-program/p/{parent_token}/video/")
    result_url = request.build_absolute_uri(f"/screening-program/p/{parent_token}/result/")

    # Flags in multiple languages
    flags = screening.red_flags or []
    flags_en = flags_to_text(flags, "en") or "Nutrition red flags identified."
    flags_hi = flags_to_text(flags, "hi") or "पोषण से जुड़े संकेत पाए गए।"
    local_code = _resolve_local_lang_for_message(org)
    flags_local = flags_to_text(flags, local_code) or flags_en

    part_en = _translate_message("en", school_name=school_name, student_name=student_name, flags_text=flags_en, video_url=video_url, result_url=result_url, screened_on=screened_on)
    part_hi = _translate_message("hi", school_name=school_name, student_name=student_name, flags_text=flags_hi, video_url=video_url, result_url=result_url, screened_on=screened_on)
    part_local = _translate_message(local_code, school_name=school_name, student_name=student_name, flags_text=flags_local, video_url=video_url, result_url=result_url, screened_on=screened_on)

    prefill = f"{part_local}\n\n---\n\n{part_hi}\n\n---\n\n{part_en}"

    log = MessageLog.objects.create(
        organization=org,
        to_phone_e164=guardian.phone_e164,
        channel="whatsapp",
        template_code="SCREENING_ONLY_RED_MULTI_V1",
        language="multi",
        payload={
            "_prefill_text": prefill,
            "screening_id": screening.id,
            "student_id": screening.student_id,
            "video_url": video_url,
            "result_url": result_url,
            "local_language_code": local_code,
        },
        status=MessageLog.Status.QUEUED,
        related_screening=screening,
    )

    return log, prefill
