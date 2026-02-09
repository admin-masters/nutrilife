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
import uuid
from django.urls import reverse

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
    #DEFAULT_GRADES includes Nursery, K.G., 1..12
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


# ---------------------------------------------------------------------------
# Screening Program: Parent WhatsApp message (NO RED-FLAG NAMING)
# Source text: NutriLift_Parent_WhatsApp_Message_NoRedFlag_Multilingual.docx
# ---------------------------------------------------------------------------

PARENT_WHATSAPP_MESSAGE_TEMPLATES = {
    "en": "\n".join([
        "Dear Parent/Guardian,",
        "This is <teacher name>, class teacher (<school name>). On <date>, we did the routine twice-a-year growth & nutrition screening for your child (Class <class/div>).",
        "We:",
        "measured height and weight; and",
        "asked your child a few simple questions. Your child answered, and I recorded the answers in the screening form.",
        "Based on the measurements and answers, the screening tool recommends a children’s doctor (pediatrician) check. Please show this message to the doctor.",
        "Please watch this short video for simple guidance: <video/page link>",
        "Please note:",
        "A child’s answers can sometimes be wrong or incomplete.",
        "If any measurement/answer is wrong, please contact me to do the screening again.",
        "Important:",
        "This is a school screening message. It is not a medical diagnosis.",
        "Please do not forward this message.",
        "If you received this message by mistake, reply “WRONG NUMBER” and delete it.",
        "Questions and measurements / your child’s answers:",
        "<questions and answers>",
    ]),
    "hi": "\n".join([
        "प्रिय माता-पिता/अभिभावक,",
        "यह <teacher name> है, आपके बच्चे का (कक्षा <class/div>) कक्षा अध्यापक/अध्यापिका (<school name>)। <date> को हमने आपके बच्चे की नियमित (वर्ष में दो बार) वृद्धि और पोषण की जांच की।",
        "हमने:",
        "बच्चे की लंबाई और वजन मापा; और",
        "कुछ आसान प्रश्न बच्चे से पूछे। आपके बच्चे ने उत्तर दिए और मैंने उन्हें जांच फॉर्म में दर्ज किया।",
        "इन मापों और उत्तरों के आधार पर, स्क्रीनिंग टूल बच्चों के डॉक्टर (बाल रोग विशेषज्ञ) से जांच कराने की सलाह देता है। कृपया यह संदेश डॉक्टर को दिखाएं।",
        "सरल जानकारी के लिए कृपया यह छोटा वीडियो देखें: <video/page link>",
        "कृपया ध्यान दें:",
        "बच्चों के उत्तर कभी-कभी गलत या अधूरे हो सकते हैं।",
        "यदि कोई माप/उत्तर गलत है, तो कृपया मुझसे संपर्क करें ताकि हम फिर से जांच कर सकें।",
        "महत्वपूर्ण:",
        "यह स्कूल की स्क्रीनिंग है, यह कोई मेडिकल निदान नहीं है।",
        "कृपया इस संदेश को आगे न भेजें।",
        "यदि यह संदेश आपको गलती से मिला है, तो “WRONG NUMBER” लिखकर जवाब दें और संदेश को हटा दें।",
        "प्रश्न और माप / आपके बच्चे के उत्तर:",
        "<questions and answers>",
    ]),
    "ta": "\n".join([
        "அன்பார்ந்த பெற்றோர்/ பாதுகாவலர்,",
        "இது உங்கள் குழந்தையின் வகுப்பு (வகுப்பு <class/div>) ஆசிரியர்/ஆசிரியையாகிய <teacher name>, (<school name>) . <date> அன்று நாங்கள் குழந்தைகளுக்கான வழக்கமான ஆண்டுக்கு இரண்டு முறை வளர்ச்சி மற்றும் ஊட்டச்சத்து பரிசோதனையை மேற்கொண்டோம்.",
        "நாங்கள்:",
        "குழந்தைகளின் உயரம் மற்றும் எடையை அளந்தோம்; மற்றும்",
        "குழந்தையிடம் சில எளிய கேள்விகளைக் கேட்டோம். உங்கள் குழந்தை பதிலளித்தது, நான் அந்த பதில்களை பரிசோதனைப் படிவத்தில் பதிவு செய்தேன்.",
        "அளவீடுகள் மற்றும் பதில்களின் அடிப்படையில், பரிசோதனைக் கருவி ஒரு குழந்தைகள் மருத்துவர் (குழந்தை நல மருத்துவர்) பரிசோதனையை பரிந்துரைக்கிறது. தயவுசெய்து இந்தச் செய்தியை மருத்துவரிடம் காட்டுங்கள்.",
        "எளிய வழிகாட்டுதலுக்கு இந்த குறுகிய வீடியோவைப் பாருங்கள்: <video/page link>",
        "தயவுசெய்து கவனத்தில் கொள்ளுங்கள்:",
        "குழந்தையின் பதில்கள் சில நேரங்களில் தவறாகவோ முழுமையற்றதாகவோ இருக்கலாம்.",
        "ஏதேனும் அளவீடு/பதில் தவறாக இருந்தால், மீண்டும் பரிசோதனை செய்ய என்னை தொடர்பு கொள்ளுங்கள்.",
        "முக்கியம்:",
        "இது ஒரு பள்ளி பரிசோதனை செய்தி. இது ஒரு மருத்துவ நோயறிதல் அல்ல.",
        "தயவுசெய்து இந்தச் செய்தியை மற்றவர்களுக்கு அனுப்ப வேண்டாம்.",
        "நீங்கள் தவறுதலாக இந்தச் செய்தியைப் பெற்றிருந்தால், “WRONG NUMBER” என்று பதிலளித்து அதை நீக்குங்கள்.",
        "கேள்விகள் மற்றும் அளவீடுகள் / உங்கள் குழந்தையின் பதில்கள்:",
        "<questions and answers>",
    ]),
    "te": "\n".join([
        "ప్రియమైన తల్లిదండ్రులకు/సంరక్షకులకు,",
        "ఇది <teacher name>, మీ పిల్లల (తరగతి <class/div>) క్లాస్ టీచర్ (<school name>). <date>నాడు, మీ పిల్లల కోసం సంవత్సరానికి రెండుసార్లు నిర్వహించే సాధారణ గ్రోత్ మరియు పోషణ పరీక్ష చేశాము.",
        "మేము:",
        "మీ పిల్లల ఎత్తు మరియు బరువు కొలిచాము; మరియు",
        "మీ పిల్లలను కొన్ని సాధారణ ప్రశ్నలు అడిగాము. మీ పిల్లలు సమాధానాలు ఇచ్చారు, నేను వాటిని స్క్రీనింగ్ ఫారంలో నమోదు చేశాను.",
        "కొలతలు మరియు సమాధానాల ఆధారంగా, స్క్రీనింగ్ టూల్ పిల్లల వైద్యుడు (పీడియాట్రిషియన్) చెక్ సిఫారసు చేస్తుంది. దయచేసి ఈ మెసేజ్‌ను డాక్టర్‌కు చూపించండి.",
        "సులభమైన మార్గదర్శకానికి ఈ చిన్న వీడియో చూడండి: <video/page link>",
        "దయచేసి గమనించండి:",
        "కొన్ని సార్లు పిల్లల సమాధానాలు తప్పు లేదా అసంపూర్ణంగా ఉండవచ్చు.",
        "ఏదైనా కొలత/సమాధానం తప్పు ఉంటే, దయచేసి నన్ను సంప్రదించి స్క్రీనింగ్ మళ్లీ చేయించండి.",
        "ముఖ్యమైనది:",
        "ఇది స్కూల్ స్క్రీనింగ్ మెసేజ్. ఇది మెడికల్ డయాగ్నసిస్ కాదు.",
        "దయచేసి ఈ సందేశాన్ని ఫార్వర్డ్ చేయవద్దు.",
        "మీకు ఈ సందేశం పొరపాటున అందితే, “WRONG NUMBER” అని జవాబు ఇచ్చి డిలీట్ చేయండి.",
        "ప్రశ్నలు మరియు కొలతలు / మీ పిల్లల సమాధానాలు:",
        "<questions and answers>",
    ]),
    "ml": "\n".join([
        "പ്രിയപ്പെട്ട രക്ഷിതാവിന്/രക്ഷകര്‍ത്താവിന്,",
        "ഞാൻ <teacher name> ആണ്, നിങ്ങളുടെ കുട്ടിയുടെ (ക്ലാസ് <class/div>) ക്ലാസ് ടീച്ചര്‍ (<school name>). <date> ന്, നിങ്ങളുടെ കുട്ടിയുടെ പതിവ് (വർഷത്തിൽ രണ്ട് തവണ) വളർച്ചയും പോഷകാഹാര പരിശോധനയും നടത്തി.",
        "ഞങ്ങൾ:",
        "കുട്ടിയുടെ ഉയരവും ഭാരവും അളന്നു; കൂടാതെ",
        "കുട്ടിയോട് കുറച്ച് ലളിതമായ ചോദ്യങ്ങൾ ചോദിച്ചു. നിങ്ങളുടെ കുട്ടി മറുപടി പറഞ്ഞു, ഞാൻ അത് സ്ക്രീനിംഗ് ഫോമിൽ രേഖപ്പെടുത്തി.",
        "അളവുകളും മറുപടികളും അടിസ്ഥാനമാക്കി, സ്ക്രീനിംഗ് ടൂൾ കുട്ടികളുടെ ഡോക്ടർ (പീഡിയാട്രിഷ്യൻ) പരിശോധന ശുപാർശ ചെയ്യുന്നു. ദയവായി ഈ സന്ദേശം ഡോക്ടറെ കാണിക്കുക.",
        "ലളിതമായ മാർഗ്ഗനിർദ്ദേശത്തിനായി ഈ ചെറിയ വീഡിയോ കാണുക: <video/page link>",
        "ദയവായി ശ്രദ്ധിക്കുക:",
        "കുട്ടികളുടെ മറുപടികൾ ചിലപ്പോൾ തെറ്റായതോ അപൂർണമായതോ ആയിരിക്കാം.",
        "ഏതെങ്കിലും അളവ്/മറുപടി തെറ്റാണെങ്കില്‍, ദയവായി എന്നെ ബന്ധപ്പെടുക, സ്ക്രീനിംഗ് വീണ്ടും ചെയ്യാനായി.",
        "പ്രധാനപ്പെട്ടത്:",
        "ഇത് സ്കൂൾ സ്ക്രീനിംഗ് സന്ദേശമാണ്. ഇത് ഒരു മെഡിക്കൽ രോഗനിർണയം അല്ല.",
        "ദയവായി ഈ സന്ദേശം ഫോർവേഡ് ചെയ്യരുത്.",
        "ഈ സന്ദേശം നിങ്ങൾക്ക് തെറ്റായി ലഭിച്ചതാണെങ്കിൽ, “WRONG NUMBER” എന്ന് മറുപടി നൽകി അത് ഡിലീറ്റ് ചെയ്യുക.",
        "ചോദ്യങ്ങളും അളവുകളും / നിങ്ങളുടെ കുട്ടിയുടെ മറുപടികൾ:",
        "<questions and answers>",
    ]),
    "kn": "\n".join([
        "ಪ್ರಿಯ ಪೋಷಕರೇ/ರಕ್ಷಕರೇ,",
        "ನಾನು <teacher name>, ನಿಮ್ಮ ಮಗುವಿನ (ವರ್ಗ <class/div>) ತರಗತಿ ಶಿಕ್ಷಕ/ಶಿಕ್ಷಕಿಯಾಗಿದ್ದು (<school name>). <date> ರಂದು ನಾವು ನಿಮ್ಮ ಮಗುವಿಗಾಗಿ ವರ್ಷದ ಎರಡು ಬಾರಿ ನಡೆಯುವ ಸಾಮಾನ್ಯ ಬೆಳವಣಿಗೆ ಮತ್ತು ಪೌಷ್ಟಿಕಾಂಶ ತಪಾಸಣೆಯನ್ನು ಮಾಡಿದೆವು.",
        "ನಾವು:",
        "ಮಗುವಿನ ಎತ್ತರ ಮತ್ತು ತೂಕವನ್ನು ಅಳೆಯಿತು; ಮತ್ತು",
        "ಮಗುವಿಗೆ ಕೆಲವು ಸರಳ ಪ್ರಶ್ನೆಗಳನ್ನು ಕೇಳಿದೆವು. ನಿಮ್ಮ ಮಗು ಉತ್ತರಿಸಿತು, ನಾನು ಆ ಉತ್ತರಗಳನ್ನು ತಪಾಸಣೆ ಫಾರ್ಮ್‌ನಲ್ಲಿ ದಾಖಲಿಸಿದೆನು.",
        "ಅಳತೆಗಳು ಮತ್ತು ಉತ್ತರಗಳ ಆಧಾರದ ಮೇಲೆ, ತಪಾಸಣೆ ಉಪಕರಣವು ಮಕ್ಕಳ ವೈದ್ಯರು (ಪೀಡಿಯಾಟ್ರಿಷಿಯನ್) ಪರಿಶೀಲನೆ ಮಾಡಿಸಲು ಸಲಹೆ ನೀಡುತ್ತದೆ. ದಯವಿಟ್ಟು ಈ ಸಂದೇಶವನ್ನು ವೈದ್ಯರಿಗೆ ತೋರಿಸಿ.",
        "ಸರಳ ಮಾರ್ಗದರ್ಶನಕ್ಕಾಗಿ ಈ ಚಿಕ್ಕ ವೀಡಿಯೊವನ್ನು ನೋಡಿ: <video/page link>",
        "ದಯವಿಟ್ಟು ಗಮನಿಸಿ:",
        "ಮಗುವಿನ ಉತ್ತರಗಳು ಕೆಲವೊಮ್ಮೆ ತಪ್ಪಾಗಿರಬಹುದು ಅಥವಾ ಅಪೂರ್ಣವಾಗಿರಬಹುದು.",
        "ಯಾವುದೇ ಅಳತೆ/ಉತ್ತರ ತಪ್ಪಿದ್ದರೆ, ದಯವಿಟ್ಟು ನನ್ನನ್ನು ಸಂಪರ್ಕಿಸಿ ಮತ್ತೆ ತಪಾಸಣೆ ಮಾಡಿಸಿ.",
        "ಮುಖ್ಯ:",
        "ಇದು ಶಾಲಾ ತಪಾಸಣೆ ಸಂದೇಶ. ಇದು ವೈದ್ಯಕೀಯ ನಿರ್ಣಯವಲ್ಲ.",
        "ದಯವಿಟ್ಟು ಈ ಸಂದೇಶವನ್ನು ಫಾರ್ವರ್ಡ್ ಮಾಡಬೇಡಿ.",
        "ನೀವು ಈ ಸಂದೇಶವನ್ನು ತಪ್ಪಾಗಿ ಪಡೆದಿದ್ದರೆ, “WRONG NUMBER” ಎಂದು ಉತ್ತರಿಸಿ ಮತ್ತು ಅದನ್ನು ಅಳಿಸಿ.",
        "ಪ್ರಶ್ನೆಗಳು ಮತ್ತು ಅಳತೆಗಳು / ನಿಮ್ಮ ಮಗುವಿನ ಉತ್ತರಗಳು:",
        "<questions and answers>",
    ]),
    "mr": "\n".join([
        "प्रिय पालक/संरक्षक,",
        "मी <teacher name> आहे, तुमच्या मुलाचा/मुलीचा (इयत्ता <class/div>) वर्गशिक्षक/वर्गशिक्षिका (<school name>)। <date> रोजी, आम्ही तुमच्या मुलाचे नियमित (वर्षातून दोन वेळा) वाढ आणि पोषण तपासणी केली.",
        "आम्ही:",
        "मुलाची उंची आणि वजन मोजले; आणि",
        "मुलाला काही सोपे प्रश्न विचारले. तुमच्या मुलाने उत्तरे दिली आणि मी ती तपासणी फॉर्ममध्ये नोंदवली.",
        "मोजमापे आणि उत्तरांच्या आधारे, स्क्रीनिंग टूल मुलांच्या डॉक्टर (बालरोग तज्ञ) तपासणीची शिफारस करते. कृपया हा संदेश डॉक्टरांना दाखवा.",
        "सोप्या मार्गदर्शनासाठी हा छोटा व्हिडिओ बघा: <video/page link>",
        "कृपया लक्षात घ्या:",
        "कधी कधी मुलांची उत्तरे चुकीची किंवा अपूर्ण असू शकतात.",
        "जर कोणतेही मोजमाप/उत्तर चुकीचे असेल, तर कृपया माझ्याशी संपर्क साधा, जेणेकरून आम्ही स्क्रीनिंग पुन्हा करू शकू.",
        "महत्वाचे:",
        "हा शाळेचा स्क्रीनिंग संदेश आहे. हे वैद्यकीय निदान नाही.",
        "कृपया हा संदेश पुढे पाठवू नका.",
        "जर तुम्हाला हा संदेश चुकून मिळाला असेल, तर “WRONG NUMBER” असे उत्तर द्या आणि तो हटवा.",
        "प्रश्न आणि मोजमापे / तुमच्या मुलाची उत्तरे:",
        "<questions and answers>",
    ]),
    "bn": "\n".join([
        "প্রিয় অভিভাবক/অভিভাবিকা,",
        "আমি <teacher name>, আপনার সন্তানের (শ্রেণী <class/div>) শ্রেণী শিক্ষক/শিক্ষিকা (<school name>)। <date> তারিখে আমরা আপনার সন্তানের নিয়মিত (বছরে দুবার) বৃদ্ধি ও পুষ্টি পরীক্ষা করেছি।",
        "আমরা:",
        "সন্তানের উচ্চতা ও ওজন মেপেছি; এবং",
        "সন্তানকে কয়েকটি সহজ প্রশ্ন করেছি। আপনার সন্তান উত্তর দিয়েছে এবং আমি সেই উত্তরগুলি স্ক্রীনিং ফর্মে লিখেছি।",
        "পরিমাপ এবং উত্তরগুলির ভিত্তিতে, স্ক্রীনিং টুল শিশুদের ডাক্তার (পেডিয়াট্রিশিয়ান) দ্বারা পরীক্ষা করার পরামর্শ দেয়। অনুগ্রহ করে এই বার্তাটি ডাক্তারকে দেখান।",
        "সহজ নির্দেশনার জন্য এই ছোট ভিডিওটি দেখুন: <video/page link>",
        "অনুগ্রহ করে মনে রাখবেন:",
        "সন্তানের উত্তর কখনও কখনও ভুল বা অসম্পূর্ণ হতে পারে।",
        "যদি কোনও পরিমাপ/উত্তর ভুল হয়, অনুগ্রহ করে আমার সাথে যোগাযোগ করুন যাতে আমরা আবার স্ক্রীনিং করতে পারি।",
        "গুরুত্বপূর্ণ:",
        "এটি একটি স্কুল স্ক্রীনিং বার্তা। এটি কোনও চিকিৎসা নির্ণয় নয়।",
        "অনুগ্রহ করে এই বার্তাটি ফরোয়ার্ড করবেন না।",
        "আপনি যদি ভুলবশত এই বার্তাটি পেয়ে থাকেন, তাহলে “WRONG NUMBER” লিখে উত্তর দিন এবং এটি মুছে ফেলুন।",
        "প্রশ্ন ও পরিমাপ / আপনার সন্তানের উত্তর:",
        "<questions and answers>",
    ]),
}

def _normalize_form_language(lang: str) -> str:
    """
    Normalize a language code coming from the teacher UI.
    Supported: en, mr, hi, te, ta, ml, kn, bn
    """
    lang = (lang or "").strip().lower()
    if not lang:
        return "mr"
    # tolerate "hi-IN", etc.
    lang = lang.split("-", 1)[0]
    if lang not in PARENT_WHATSAPP_MESSAGE_TEMPLATES:
        return "mr"
    return lang


def _render_parent_whatsapp_message(
    *,
    lang: str,
    teacher_name: str,
    school_name: str,
    date_str: str,
    class_div: str,
    video_url: str,
    questions_and_answers: str,
) -> str:
    template = PARENT_WHATSAPP_MESSAGE_TEMPLATES.get(lang) or PARENT_WHATSAPP_MESSAGE_TEMPLATES["mr"]
    msg = template
    replacements = {
        "<teacher name>": teacher_name or "",
        "<school name>": school_name or "",
        "<date>": date_str or "",
        "<class/div>": class_div or "",
        "<video/page link>": video_url or "",
        "<questions and answers>": (questions_and_answers or "").strip() or "-",
    }
    for k, v in replacements.items():
        msg = msg.replace(k, v)
    return msg


def _screening_parent_whatsapp_idempotency_key(screening_id: int, to_phone_e164: str) -> str:
    """One message per (screening, phone)."""
    raw = f"SCREENING_PARENT_WHATSAPP_V1|{screening_id}|{to_phone_e164}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def prepare_screening_only_redflag_click_to_chat(
    request,
    screening: "Screening",
    *,
    form_language: str = "",
    questions_and_answers: str = "",
    to_phone_e164: str = "",
) -> Tuple[Optional[MessageLog], str]:
    """
    Creates a click-to-chat MessageLog that opens WhatsApp on the device with a pre-filled message.

    IMPORTANT CHANGE:
      - If to_phone_e164 is passed, we use it instead of guardian.phone_e164.
      - This is required when guardian phone is no longer stored in DB.
    """
    org = screening.organization
    student = screening.student

    guardian = getattr(student, "primary_guardian", None)
    if not guardian:
        link = (student.guardian_links.select_related("guardian").first() if hasattr(student, "guardian_links") else None)
        guardian = link.guardian if link else None

    phone = (to_phone_e164 or "").strip() or (getattr(guardian, "phone_e164", "") or "").strip()
    if not phone:
        return None, ""

    lang = _normalize_form_language(form_language)

    idem = _screening_parent_whatsapp_idempotency_key(screening.id, phone)
    existing = MessageLog.objects.filter(idempotency_key=idem).first()
    if existing:
        payload = existing.payload or {}
        return existing, payload.get("_prefill_text", "")

    teacher_name = ""
    try:
        u = getattr(request, "user", None)
        if u and getattr(u, "is_authenticated", False):
            teacher_name = (u.get_full_name() or "").strip()
            if not teacher_name:
                teacher_name = (getattr(u, "email", "") or getattr(u, "username", "") or "").strip()
    except Exception:
        teacher_name = ""
    if not teacher_name:
        teacher_name = "Class Teacher"

    school_name = (getattr(org, "name", "") or "").strip()
    date_str = timezone.localtime(screening.screened_at).strftime("%d-%m-%Y")

    classroom = getattr(student, "classroom", None)
    class_div = str(classroom) if classroom else ""

    parent_token = build_parent_token(screening.id)
    video_url = request.build_absolute_uri(reverse("screening_only:parent_video", args=[parent_token]))

    prefill_text = _render_parent_whatsapp_message(
        lang=lang,
        teacher_name=teacher_name,
        school_name=school_name,
        date_str=date_str,
        class_div=class_div,
        video_url=video_url,
        questions_and_answers=questions_and_answers,
    )

    log = MessageLog.objects.create(
        idempotency_key=idem,
        organization=org,
        to_phone_e164=phone,
        channel="whatsapp",
        template_code="SCREENING_ONLY_PARENT_NO_REDFLAG_V1",
        language=lang,
        payload={
            "_prefill_text": prefill_text,
            "screening_id": screening.id,
            "parent_token": parent_token,
            "video_url": video_url,
            "form_language": lang,
            "questions_and_answers": (questions_and_answers or ""),
        },
        status=MessageLog.Status.QUEUED,
        related_screening=screening,
    )

    return log, prefill_text