import uuid
from .base import WhatsAppProvider

class MockProvider(WhatsAppProvider):
    def send_template(self, to_phone_e164: str, template_name: str, language_code: str, components: dict):
        # pretend it's sent and immediately 'SENT'
        return (f"mock-{uuid.uuid4()}", "sent")
