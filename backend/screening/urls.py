from django.urls import path
from .views import teacher_portal, screening_create, screening_result, send_education, send_assistance
from .export import export_screenings_csv

urlpatterns = [
    path("teacher/", teacher_portal, name="teacher_portal"),
    path("teacher/screen/<int:student_id>/", screening_create, name="screening_create"),
    path("teacher/result/<int:screening_id>/", screening_result, name="screening_result"),
    path("admin/export/screenings.csv", export_screenings_csv, name="export_screenings_csv"),
    path("send/education/<int:screening_id>/", send_education, name="send_education"),
    path("send/assistance/<int:screening_id>/", send_assistance, name="send_assistance"),
]
