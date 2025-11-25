from django.urls import path
from .views import wa_webhook

urlpatterns = [
    path("webhooks/whatsapp/", wa_webhook, name="wa_webhook"),
]
