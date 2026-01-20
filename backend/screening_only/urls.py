from django.urls import path

from . import views

app_name = "screening_only"

urlpatterns = [
    # School enrollment (public)
    path("enroll/", views.enroll_school, name="enroll_school"),
    path("enroll/success/<slug:token>/", views.enroll_success, name="enroll_success"),

    # Google OAuth
    path("auth/google/start/", views.google_oauth_start, name="google_oauth_start"),
    path("auth/google/callback/", views.google_oauth_callback, name="google_oauth_callback"),
    path("auth/logout/", views.logout_view, name="logout"),

    # Admin flow
    path("admin/<slug:token>/auth/", views.admin_auth_required, name="admin_auth_required"),
    path("admin/onboarding/", views.admin_onboarding, name="admin_onboarding"),
    path("admin/link/", views.admin_link_dashboard, name="admin_link_dashboard"),
    path("admin/dashboard/", views.admin_performance_dashboard, name="admin_performance_dashboard"),

    # Teacher flow
    path("teacher/auth-required/", views.teacher_auth_required, name="teacher_auth_required"),
    path("teacher/dashboard/", views.teacher_dashboard, name="teacher_dashboard"),
    path("teacher/<slug:token>/", views.teacher_access_portal, name="teacher_access_portal"),

    # Parent flow (public, tokenized)
    path("p/<str:token>/video/", views.parent_video, name="parent_video"),
    path("p/<str:token>/result/", views.parent_result, name="parent_result"),

    # Inditech
    path("inditech/schools/", views.inditech_school_list, name="inditech_school_list"),
    path("inditech/schools/<int:org_id>/dashboard/", views.inditech_school_dashboard, name="inditech_school_dashboard"),
]
