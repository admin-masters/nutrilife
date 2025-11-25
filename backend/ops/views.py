from django.http import JsonResponse
from django.utils import timezone
from .models import Heartbeat

def healthz(request):
    beat = Heartbeat.objects.filter(key="beat").first()
    beat_ok = False
    if beat:
        beat_ok = (timezone.now() - beat.seen_at).total_seconds() < 180  # <3min
    return JsonResponse({"ok": True, "celery_beat_ok": beat_ok})
