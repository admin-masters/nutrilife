from django.contrib import admin
from .models import Application
from .models import ApprovalBatch, BatchItem

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("id","organization","student","guardian","status","source","applied_at","forwarded_at")
    list_filter = ("organization","status","source")
    search_fields = ("student__first_name","student__last_name","guardian__phone_e164")



@admin.register(ApprovalBatch)
class ApprovalBatchAdmin(admin.ModelAdmin):
    list_display = ("organization","method","n_selected","executed_at","created_by")
    list_filter = ("organization","method")
    search_fields = ("organization__name",)

@admin.register(BatchItem)
class BatchItemAdmin(admin.ModelAdmin):
    list_display = ("approval_batch","application","outcome","created_at")
    list_filter = ("outcome",)
    search_fields = ("approval_batch__organization__name","application__student__first_name","application__student__last_name")
