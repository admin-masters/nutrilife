from django.urls import path

from . import views

app_name = "grants"

urlpatterns = [
    path("grants/", views.grants_dashboard, name="dashboard"),
    path("grants/grantor/new", views.grantor_create, name="grantor_create"),
    path("grants/new", views.grant_create, name="grant_create"),
    path("grants/<int:grant_id>/pgc-approve", views.grant_pgc_approve, name="grant_pgc_approve"),
    path("grants/<int:grant_id>/activate", views.grant_activate, name="grant_activate"),
]
