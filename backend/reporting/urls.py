from django.urls import path
from .views import (
    school_dashboard, export_school_csv,
    inditech_dashboard, inditech_school, inditech_export_school_csv,
)
from . import views

app_name = "reporting"

urlpatterns = [
    path("reporting/school", school_dashboard, name="school_dashboard"),
    path("reporting/school/export.csv", export_school_csv, name="export_school_csv"),

    path("reporting/inditech", inditech_dashboard, name="inditech_dashboard"),
    path("reporting/inditech/school/<int:org_id>", inditech_school, name="inditech_school"),
    path("reporting/inditech/school/<int:org_id>/export.csv", inditech_export_school_csv, name="inditech_export_school_csv"),
    path("inditech/", views.inditech_console, name="inditech_console"),
]
