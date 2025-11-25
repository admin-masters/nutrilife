from django.http import HttpResponseForbidden
from .models import OrgMembership, Organization

class CurrentOrganizationMiddleware:
    """
    Sets request.org and request.membership for authenticated users.

    Selection order:
      1) X-Organization-Id header (numeric id) if the user is a member
      2) ?org=<id> query param (for quick testing)
      3) If the user has exactly one active membership, use it
      4) Otherwise, no org attached (views can enforce via @require_roles)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.org = None
        request.membership = None

        u = getattr(request, "user", None)
        if u and u.is_authenticated:
            org_id = request.headers.get("X-Organization-Id") or request.GET.get("org")
            qs = OrgMembership.objects.select_related("organization").filter(user=u, is_active=True)
            if org_id:
                try:
                    mem = qs.get(organization_id=int(org_id))
                    request.org = mem.organization
                    request.membership = mem
                except (OrgMembership.DoesNotExist, ValueError):
                    return HttpResponseForbidden("Invalid organization for this user.")
            elif qs.count() == 1:
                mem = qs.first()
                request.org = mem.organization
                request.membership = mem
        return self.get_response(request)
