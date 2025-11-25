def audit_log(user, org, action, target=None, payload=None, request=None):
    from .models import AuditLog
    payload = payload or {}
    target_app = target.__class__._meta.app_label if target else ""
    target_model = target.__class__._meta.model_name if target else ""
    target_id = str(target.pk) if target else ""
    ip = request.META.get("REMOTE_ADDR") if request else None
    ua = request.META.get("HTTP_USER_AGENT") if request else ""
    AuditLog.objects.create(
        organization=org, actor=user, action=action,
        target_app=target_app, target_model=target_model, target_id=target_id,
        payload=payload, ip=ip, user_agent=ua
    )
