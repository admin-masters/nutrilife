from functools import wraps
from django.http import HttpResponseForbidden
from accounts.models import Organization, Role

def require_teacher_or_public(view_func):
    """
    Allows access if:
    - authenticated user is TEACHER or ORG_ADMIN in the resolved org, OR
    - request.session['public_teacher_org_id'] matches the resolved org.

    The org is resolved from (in order):
    - request.org (if already set by a caller),
    - URL kwarg 'token' (teacher token routes),
    - session key 'public_teacher_org_id'.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        org = getattr(request, "org", None)

        # 1) Resolve org by token if not already present
        if org is None:
            token = kwargs.get("token")
            if token:
                org = Organization.objects.filter(screening_link_token=token).first()
                if org:
                    request.org = org
                    # Stickiness: ensure the session is pinned to this org after token entry
                    request.session["public_teacher_org_id"] = org.id 

        # 2) Resolve org from public teacher session if still not present
        if org is None:
            sess_org_id = request.session.get("public_teacher_org_id")
            if sess_org_id:
                try:
                    org = Organization.objects.get(id=sess_org_id)
                    request.org = org
                except Organization.DoesNotExist:
                    pass

        if org is None:
            return HttpResponseForbidden("Organization not resolved.")

        # A) Authenticated path (teacher/admin membership in this org)
        if request.user.is_authenticated:
            mem = getattr(request, "membership", None)
            if mem and mem.organization_id == org.id and mem.role in (Role.TEACHER, Role.ORG_ADMIN):
                return view_func(request, *args, **kwargs)

        # B) Public teacher session path
        if request.session.get("public_teacher_org_id") == org.id:
            return view_func(request, *args, **kwargs)

        return HttpResponseForbidden("Teacher access required.")
    return _wrapped
