from django.urls import path
from .views import wa_webhook, whatsapp_preview

urlpatterns = [
    path("webhooks/whatsapp/", wa_webhook, name="wa_webhook"),
    path("whatsapp/preview/<int:log_id>/", whatsapp_preview, name="whatsapp_preview"),
]
