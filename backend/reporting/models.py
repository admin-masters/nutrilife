from __future__ import annotations
from dataclasses import asdict
from datetime import date, timedelta
from django.db import models
from django.utils import timezone
from accounts.models import Organization

class SchoolStatDaily(models.Model):
    """
    One row per (organization, date) rollup. Snapshot of counts for that day.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="daily_stats")
    day = models.DateField(db_index=True)

    # Screenings
    screened = models.PositiveIntegerField(default=0)
    red_flags = models.PositiveIntegerField(default=0)

    # Applications
    applied = models.PositiveIntegerField(default=0)
    forwarded = models.PositiveIntegerField(default=0)
    approved = models.PositiveIntegerField(default=0)
    rejected = models.PositiveIntegerField(default=0)

    # Enrollments
    enrollments_created = models.PositiveIntegerField(default=0)

    # Logistics
    supplies_delivered = models.PositiveIntegerField(default=0)

    # Compliance
    compliance_submitted = models.PositiveIntegerField(default=0)
    compliance_compliant = models.PositiveIntegerField(default=0)
    compliance_unable = models.PositiveIntegerField(default=0)

    # Milestones (events on this day)
    milestones_due = models.PositiveIntegerField(default=0)
    milestones_overdue = models.PositiveIntegerField(default=0)
    milestones_completed = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = (("organization", "day"),)
        indexes = [models.Index(fields=["organization", "day"])]

    def __str__(self):
        return f"{self.organization.name} – {self.day}"

class SchoolReportStatus(models.Model):
    """
    Tracks 6-month performance report cycles per school for Inditech console.
    When we send a report, we move next_due_on by +180 days.
    """
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="report_status")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_period_start = models.DateField(null=True, blank=True)
    last_period_end = models.DateField(null=True, blank=True)
    next_due_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization.name} – next due {self.next_due_on or '-'}"

    def ensure_defaults(self):
        if not self.next_due_on:
            # default: 180 days after org created_at (or today if none)
            base = (self.organization.created_at.date() if hasattr(self.organization, "created_at") else timezone.now().date())
            self.next_due_on = base + timedelta(days=180)
        self.save(update_fields=["next_due_on","updated_at"])
