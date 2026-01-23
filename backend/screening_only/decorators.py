from functools import wraps
from django.http import HttpResponseForbidden

from accounts.decorators import require_roles
from accounts.models import Role


def require_screening_only_org(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        org = getattr(request, "org", None)
        if not org:
            return HttpResponseForbidden("Organization context missing.")
        try:
            org.screening_only_profile
        except Exception:
            return HttpResponseForbidden("This organization is not enrolled in the Screening Program.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_screening_only_admin(view_func):
    return require_roles(Role.ORG_ADMIN)(require_screening_only_org(view_func))


def require_screening_only_teacher(view_func):
    # Allow both Teacher and School Admin into the screening-only “teacher” views
    return require_roles(Role.TEACHER, Role.ORG_ADMIN)(require_screening_only_org(view_func))
