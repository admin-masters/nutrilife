from functools import wraps
from django.http import HttpResponseForbidden

def require_roles(*roles, allow_superuser=False):
    """
    Usage:
    @require_roles("SAPA_ADMIN", "ORG_ADMIN", allow_superuser=True)
    def view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            u = request.user
            if not u.is_authenticated:
                return HttpResponseForbidden("Auth required.")
            if allow_superuser and u.is_superuser:
                return view_func(request, *args, **kwargs)
            mem = getattr(request, "membership", None)
            if not mem:
                return HttpResponseForbidden("Organization context required.")
            if mem.role in roles:
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("Insufficient role.")
        return _wrapped
    return decorator
