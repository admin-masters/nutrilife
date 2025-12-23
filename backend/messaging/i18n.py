import os
from typing import Optional

LANG_CODE = {
    "en": os.getenv("MSG_LANG_EN", "en"),
    "hi": os.getenv("MSG_LANG_HI", "hi"),
    "local": os.getenv("MSG_LANG_LOCAL", os.getenv("MSG_LANG_EN", "en")),
}

def to_provider_lang(value: Optional[str]) -> str:
    """Normalize arbitrary inputs like 'EN', 'en_US', 'hi-IN', 'local' → provider code."""
    v = (value or "").lower()
    if v.startswith("hi"):
        return LANG_CODE["hi"]
    if v == "local":
        return LANG_CODE["local"]
    # default and any 'en*' variant
    return LANG_CODE["en"]

FLAG_TEXT = {
    "en": {
        "bmi_low": "low BMI for age",
        "measurement_incomplete": "measurement incomplete",
        "diet_diversity_low": "low diet diversity",
        "symptoms_present": "some symptoms reported",
        "multiple_symptoms": "multiple symptoms reported",
    },
    "hi": {
        "bmi_low": "आयु के अनुसार BMI कम",
        "measurement_incomplete": "माप अपूर्ण",
        "diet_diversity_low": "आहार विविधता कम",
        "symptoms_present": "कुछ लक्षण रिपोर्ट हुए",
        "multiple_symptoms": "कई लक्षण रिपोर्ट हुए",
    },
    # Use org/guardian 'local' language; fallback to English if not found
    "local": {
        "bmi_low": "Local: low BMI",
        "measurement_incomplete": "Local: measurement incomplete",
        "diet_diversity_low": "Local: low diet diversity",
        "symptoms_present": "Local: some symptoms",
        "multiple_symptoms": "Local: multiple symptoms",
    }
}

def choose_language(guardian_pref: str | None, org_locale: str | None) -> str:
    for cand in (guardian_pref, org_locale, "en"):
        if not cand:
            continue
        c = cand.lower()
        if c in ("en","hi","local"):
            return c
        # normalize common variants
        if c.startswith("en"): return "en"
        if c.startswith("hi"): return "hi"
    return "en"

def flags_to_text(flags, lang: str) -> str:
    mapping = FLAG_TEXT.get(lang) or FLAG_TEXT["en"]
    return ", ".join(mapping.get(f, f) for f in (flags or []))

def edu_video_url(lang: str) -> str:
    if lang == "hi":
        return os.getenv("EDU_VIDEO_URL_HI", os.getenv("EDU_VIDEO_URL_EN",""))
    if lang == "local":
        return os.getenv("EDU_VIDEO_URL_LOCAL", os.getenv("EDU_VIDEO_URL_EN",""))
    return os.getenv("EDU_VIDEO_URL_EN","")

def assist_apply_url(student_id: int, screening_id: int, lang: str) -> str:
    base = os.getenv("ASSIST_APPLY_URL_BASE","")
    print("Base",base)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}student_id={student_id}&screening_id={screening_id}&lang={lang}"
