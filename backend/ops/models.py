from django.db import models
from django.utils import timezone

class Heartbeat(models.Model):
    key = models.CharField(max_length=32, unique=True)   # e.g., "beat"
    seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    def __str__(self): return f"{self.key} @ {self.seen_at}"
