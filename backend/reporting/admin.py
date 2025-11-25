from django.contrib import admin
from .models import SchoolStatDaily, SchoolReportStatus

@admin.register(SchoolStatDaily)
class SchoolStatDailyAdmin(admin.ModelAdmin):
    list_display = ("organization","day","screened","red_flags","approved","supplies_delivered","compliance_compliant","milestones_overdue")
    list_filter = ("organization",)
    date_hierarchy = "day"

@admin.register(SchoolReportStatus)
class SchoolReportStatusAdmin(admin.ModelAdmin):
    list_display = ("organization","next_due_on","last_sent_at","last_period_start","last_period_end")
    list_filter = ("next_due_on",)
    search_fields = ("organization__name",)
