from django.contrib import admin
from .models import MessageLog

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ("created_at","organization","to_phone_e164","template_code","language","status","provider_msg_id")
    list_filter = ("organization","status","template_code","language")
    search_fields = ("to_phone_e164","provider_msg_id")
    readonly_fields = ("created_at","updated_at","sent_at")
