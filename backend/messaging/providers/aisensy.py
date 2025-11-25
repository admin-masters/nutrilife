# messaging/providers/aisensy.py
import os, requests
from .base import WhatsAppProvider

class AiSensyProvider(WhatsAppProvider):
    """
    Thin wrapper over AiSensy Campaign API v2.
    Uses API Campaigns you've set live (one per language), e.g.
    nutrilift_redflag_edu_v1_en / _hi
    """
    def __init__(self):
        self.api_key = os.getenv("AISENSY_API_KEY")
        self.base_url = os.getenv("AISENSY_BASE_URL", "https://backend.aisensy.com/campaign/t1/api/v2")
        self.source = os.getenv("AISENSY_SOURCE", "backend")
        self.username_fallback = os.getenv("AISENSY_USERNAME_FALLBACK", "User")
        if not self.api_key:
            raise RuntimeError("Missing AISENSY_API_KEY")

    def send_template(self, to_phone_e164: str, template_name: str, language_code: str, components: dict):
        """
        components contract (from your existing service layer):
          - components["body"]    : list of strings -> ordered {{1}}, {{2}}, ... for the Body
          - components["buttons"] : list of strings -> dynamic button URLs (informational)
        For AiSensy, templateParams must include all {{n}} used by the campaign.
        We assume your campaigns reuse the same {{n}} in buttons as in body,
        so 'body' alone satisfies the count. If your button uses extra {{n}},
        pass components["params"] explicitly with the full ordered list.
        """
        campaign_name = f"{template_name}_{language_code}"  # e.g., nutrilift_redflag_assist_v1_hi

        # Prefer explicit "params" if provided; else default to body-only
        body_params = components.get("body") or []
        template_params = components.get("params", body_params)

        # Use first body param as recipient name if available
        user_name = str(components.get("user_name") or (body_params[0] if body_params else self.username_fallback))

        payload = {
            "apiKey": self.api_key,
            "campaignName": campaign_name,
            "destination": to_phone_e164,         # keep E.164; AiSensy accepts +91… (docs)
            "userName": user_name,
            "source": self.source,
            "templateParams": [str(x) for x in template_params],
        }

        # Optional: attach a few useful attributes as strings
        attrs = components.get("attributes") or {}
        if attrs:
            payload["attributes"] = {str(k): str(v) for k, v in attrs.items()}

        r = requests.post(self.base_url, json=payload, timeout=20)
        # If AiSensy returns non-2xx, raise; Celery will retry if used
        r.raise_for_status()

        # Response may be {"status":"success","message":"queued"} or similar; an ID isn't guaranteed
        try:
            data = r.json()
        except ValueError:
            data = {}

        provider_status = str(data.get("status", "sent")).lower()  # treat success as "sent"
        # We don't get a WhatsApp message-id here; persist an empty id.
        return ("", "sent" if provider_status in ("success", "sent") else provider_status)
