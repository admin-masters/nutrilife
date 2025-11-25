from abc import ABC, abstractmethod
from typing import Dict, Tuple

class WhatsAppProvider(ABC):
    @abstractmethod
    def send_template(self, to_phone_e164: str, template_name: str, language_code: str, components: Dict) -> Tuple[str, str]:
        """
        Returns (provider_msg_id, provider_status)
        components is provider-specific; for Meta Cloud we pass {"body": [...], "buttons": [...]}
        """
        raise NotImplementedError
