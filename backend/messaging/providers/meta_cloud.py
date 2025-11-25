import os, requests
from .base import WhatsAppProvider

class MetaCloudProvider(WhatsAppProvider):
    """
    Minimal wrapper for WhatsApp Cloud API (template sends).
    Requires:
      WA_PHONE_NUMBER_ID, WA_ACCESS_TOKEN
    """
    def __init__(self):
        self.phone_number_id = os.getenv("WA_PHONE_NUMBER_ID")
        self.token = os.getenv("WA_ACCESS_TOKEN")
        if not self.phone_number_id or not self.token:
            raise RuntimeError("Meta Cloud Provider missing WA_PHONE_NUMBER_ID/WA_ACCESS_TOKEN")

    def send_template(self, to_phone_e164: str, template_name: str, language_code: str, components: dict):
        url = f"https://graph.facebook.com/v20.0/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": "template",
            "template": {
                "name": template_name,                    # must exist/approved in WABA
                "language": {"code": language_code},      # e.g., "en", "hi"
                "components": []
            }
        }
        # Body params
        body_params = components.get("body", [])
        if body_params:
            payload["template"]["components"].append({
                "type": "body",
                "parameters": [{"type":"text","text": str(x)} for x in body_params]
            })
        # URL buttons (index order must match template)
        buttons = components.get("buttons", [])
        for idx, url_text in enumerate(buttons):
            payload["template"]["components"].append({
                "type": "button", "sub_type": "url", "index": idx,
                "parameters": [{"type":"text","text": url_text}]
            })
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        # Return first message id if present
        msg_id = (data.get("messages") or [{}])[0].get("id","")
        return (msg_id or "", "sent")
