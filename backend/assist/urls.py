from django.urls import path
from .views import assist_apply, assist_thanks, school_app_dashboard, forward_all, forward_one
from .views_sapa import (
    sapa_approvals_dashboard, sapa_approve_all, sapa_approve_top_n, sapa_reject_all
)

app_name = "assist"

urlpatterns = [
    # Public parent application (link from WhatsApp)
    path("assist/apply", assist_apply, name="assist_apply"),
    path("assist/thanks", assist_thanks, name="assist_thanks"),

    # School admin dashboard
    path("assist/admin", school_app_dashboard, name="school_app_dashboard"),
    path("assist/admin/forward-all", forward_all, name="forward_all"),
    path("assist/admin/forward/<int:app_id>", forward_one, name="forward_one"),
    path("assist/sapa/approvals", sapa_approvals_dashboard, name="sapa_approvals_dashboard"),
    path("assist/sapa/approve-all", sapa_approve_all, name="sapa_approve_all"),
    path("assist/sapa/approve-top-n", sapa_approve_top_n, name="sapa_approve_top_n"),
    path("assist/sapa/reject-all", sapa_reject_all, name="sapa_reject_all"),
]
