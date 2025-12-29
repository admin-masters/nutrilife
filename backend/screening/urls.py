from django.urls import path, re_path
from .views import (
    teacher_portal,
    teacher_portal_token,
    teacher_add_student,
    screening_create,
    screening_result,
    send_parent_whatsapp,
)
from .export import export_screenings_csv

urlpatterns = [
    re_path(r"^teacher/(?P<token>[-a-z0-9_]+-[A-Za-z0-9]{8})/add-student/$",
            teacher_add_student, name="teacher_add_student_token"),
    path("teacher/add-student/", teacher_add_student, name="teacher_add_student"),
    re_path(r"^teacher/(?P<token>[-a-z0-9_]+-[A-Za-z0-9]{8})/$",
            teacher_portal_token, name="teacher_portal_token"),

    path("teacher/", teacher_portal, name="teacher_portal"),
    path("teacher/screen/<int:student_id>/", screening_create, name="screening_create"),
    path("teacher/result/<int:screening_id>/", screening_result, name="screening_result"),
    path("teacher/send/<int:screening_id>/", send_parent_whatsapp, name="send_parent_whatsapp"),

    path("admin/export/screenings.csv", export_screenings_csv, name="export_screenings_csv"),
]
