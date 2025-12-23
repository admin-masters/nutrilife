from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from accounts.decorators import require_roles
from accounts.models import Role
from django.urls import path, include

def health(_):
    return JsonResponse({"ok": True})

@require_roles(Role.SAPA_ADMIN, Role.ORG_ADMIN, allow_superuser=True)
def whoami(request):
    u = request.user
    org = getattr(request, "org", None)
    return JsonResponse({
        "email": u.email,
        "roles": list(u.memberships.values_list("role", flat=True)),
        "active_org": org.name if org else None,
    })

urlpatterns = [
    path("health/", health),
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    path("whoami/", whoami),
    path("screening/", include("screening.urls")),
    path("", include("messaging.urls")),
    path("", include("assist.urls")),
    path("", include("program.urls")),
    path("", include("fulfillment.urls")),
    path("", include("reporting.urls")),
    path("", include("ops.urls")),
    path("", include("orgs.urls")),
]


