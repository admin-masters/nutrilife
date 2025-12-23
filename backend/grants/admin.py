from django.contrib import admin

from .models import Grant, GrantAllocation, Grantor


@admin.register(Grantor)
class GrantorAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "contact_email", "contact_phone_e164", "organization")
    search_fields = ("name", "contact_email", "contact_phone_e164")


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "grantor", "status", "currency", "amount_committed", "amount_received")
    list_filter = ("status", "currency")
    search_fields = ("title", "grantor__name")


@admin.register(GrantAllocation)
class GrantAllocationAdmin(admin.ModelAdmin):
    list_display = ("id", "grant", "enrollment", "amount", "allocated_at", "allocated_by")
    list_filter = ("grant",)
