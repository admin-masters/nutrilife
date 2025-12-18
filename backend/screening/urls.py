from django.urls import path, re_path
from .views import (
    teacher_portal,
    teacher_portal_token,
    teacher_add_student,
    screening_create,
    screening_result,
    send_education,
    send_assistance,
)
from .export import export_screenings_csv

urlpatterns = [
    # 1) ORG-SPECIFIC add-student (tokenized) — put this BEFORE the generic token route
    re_path(r"^teacher/(?P<token>[-a-z0-9_]+-[A-Za-z0-9]{8})/add-student/$",
            teacher_add_student, name="teacher_add_student_token"),

    # 2) Legacy non-token route (kept for back-compat; the UI won’t use it)
    path("teacher/add-student/", teacher_add_student, name="teacher_add_student"),

    # 3) Token entry for the portal (kept last to avoid swallowing other routes)
    re_path(r"^teacher/(?P<token>[-a-z0-9_]+-[A-Za-z0-9]{8})/$",
            teacher_portal_token, name="teacher_portal_token"),
    path("teacher/", teacher_portal, name="teacher_portal"),
    path("teacher/screen/<int:student_id>/", screening_create, name="screening_create"),
    path("teacher/result/<int:screening_id>/", screening_result, name="screening_result"),
    path("admin/export/screenings.csv", export_screenings_csv, name="export_screenings_csv"),
    path("send/education/<int:screening_id>/", send_education, name="send_education"),
    path("send/assistance/<int:screening_id>/", send_assistance, name="send_assistance"),
]
