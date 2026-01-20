from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

from accounts.models import Role, OrgMembership, Organization


def _is_screening_only_org(org: Organization) -> bool:
    try:
        org.screening_only_profile
        return True
    except Exception:
        return False


def require_teacher_or_public(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        # Normal teacher access (authenticated)
        if request.user.is_authenticated:
            mem = getattr(request, "membership", None)
            if mem and mem.role == Role.TEACHER:
                return view_func(request, *args, **kwargs)

        # Legacy public teacher-session access (DISABLED for Screening-only orgs)
        org_id = request.session.get("public_teacher_org_id")
        if org_id:
            org = Organization.objects.filter(id=org_id).first()
            if org:
                if _is_screening_only_org(org):
                    # Force new Screening Program teacher auth flow
                    return redirect(reverse("screening_only:teacher_access_portal", args=[org.screening_link_token]))

                request.org = org
                request.membership = (
                    OrgMembership.objects.filter(user=request.user, organization=org, is_active=True).first()
                    if request.user.is_authenticated
                    else None
                )
                return view_func(request, *args, **kwargs)

        return HttpResponseForbidden("Teacher login required.")
    return _wrapped
