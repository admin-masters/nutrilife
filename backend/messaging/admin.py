from django.contrib import admin
from .models import MessageLog

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "pid", "template_code", "language", "status", "provider_msg_id")
    list_filter = ("organization", "status", "template_code", "language")
    search_fields = ("pid", "provider_msg_id", "idempotency_key")
    readonly_fields = ("created_at", "updated_at", "sent_at", "pid", "to_phone_e164", "payload")