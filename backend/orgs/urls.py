from django.urls import path
from .views import org_start

app_name = "orgs"
urlpatterns = [
    path("orgs/start", org_start, name="org_start"),
]
