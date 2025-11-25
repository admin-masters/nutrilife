# backend/program/models.py
from __future__ import annotations
from datetime import date, datetime, timedelta, time as _time
import secrets
from typing import Optional

from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import Organization, User
from assist.models import Application
from roster.models import Student
from screening.models import Screening

from datetime import date, timedelta
from django.utils.dateparse import parse_date

def _mint_token(nbytes: int = 24) -> str:
    # url-safe, ~32 chars for 24 bytes
    return secrets.token_urlsafe(nbytes)


def _unique_qr_token() -> str:
    # generate until unique
    for _ in range(6):
        token = _mint_token(24)
        if not MonthlySupply.objects.filter(qr_token=token).exists():
            return token
    # last resort (extremely unlikely)
    return _mint_token(32)


def _due_dt_for(delivered_on: date) -> datetime:
    """
    Compliance due = delivered_on + 27 days at 09:00 local time.
    Adjust time to something reasonable for reminders next sprint.
    """
    local_tz = timezone.get_current_timezone()
    target_day = delivered_on + timedelta(days=27)
    naive = datetime.combine(target_day, _time(hour=9, minute=0, second=0))
    return timezone.make_aware(naive, local_tz)


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        STOPPED = "STOPPED", "Stopped"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="enrollments")
    application = models.OneToOneField(Application, on_delete=models.PROTECT, related_name="enrollment")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")

    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return f"{self.student.full_name} ({self.status})"

    @staticmethod
    def create_for_approved(app: Application, approved_by: User | None):
        start = timezone.now().date()
        end = start + timedelta(days=180)
        with transaction.atomic():
            e = Enrollment.objects.create(
                organization=app.organization,
                application=app,
                student=app.student,
                start_date=start,
                end_date=end,
                status=Enrollment.Status.ACTIVE,
                approved_by=approved_by,
            )
            MonthlySupply.bootstrap_for_enrollment(e)
            ScreeningMilestone.bootstrap_for_enrollment(e)  # NEW
        return e
    #phase 11
    def _normalize_dates(self):
        # Coerce strings (e.g. "2024-01-01") to datetime.date
        if isinstance(self.start_date, str):
            parsed = parse_date(self.start_date)
            if parsed is not None:
                self.start_date = parsed
        if isinstance(self.end_date, str):
            parsed = parse_date(self.end_date)
            if parsed is not None:
                self.end_date = parsed
    def save(self, *args, **kwargs):
        self._normalize_dates()
        return super().save(*args, **kwargs)

class MonthlySupply(models.Model):
    """
    One row per month (1..6). Each pack has a unique qr_token printed on its label.
    When 'delivered_on' is set, we compute 'compliance_due_at = delivered_on + 27 days'.
    """
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="supplies")
    month_index = models.PositiveSmallIntegerField()  # 1..6
    scheduled_delivery_date = models.DateField(null=True, blank=True)
    delivered_on = models.DateField(null=True, blank=True)
    compliance_due_at = models.DateTimeField(null=True, blank=True, db_index=True)

    qr_token = models.CharField(max_length=96, unique=True)
    ok_to_ship_next = models.BooleanField(default=False)  # used in Sprint 6 gating

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("enrollment", "month_index"),)
        indexes = [
            models.Index(fields=["delivered_on"]),
            models.Index(fields=["compliance_due_at"]),
        ]

    def __str__(self):
        return f"{self.enrollment.student.full_name} M{self.month_index}"

    def set_delivered(self, delivered_on: Optional[date] = None, save: bool = True):
        delivered_on = delivered_on or timezone.now().date()
        self.delivered_on = delivered_on
        self.compliance_due_at = _due_dt_for(delivered_on)
        if save:
            self.save(update_fields=["delivered_on", "compliance_due_at", "updated_at"])

    def save(self, *args, **kwargs):
        # ensure token exists
        if not self.qr_token:
            self.qr_token = _unique_qr_token()

        # recompute due if delivered_on changed (best-effort)
        if self.delivered_on and not self.compliance_due_at:
            self.compliance_due_at = _due_dt_for(self.delivered_on)
        super().save(*args, **kwargs)

    # @staticmethod
    # def bootstrap_for_enrollment(e: Enrollment):
    #     """
    #     Create supplies 1..6 if none exist.
    #     scheduled_delivery_date is optional; set first month to start_date for convenience.
    #     """
    #     if e.supplies.exists():
    #         return
    #     objs = []
    #     for i in range(1, 7):
    #         objs.append(MonthlySupply(
    #             enrollment=e,
    #             month_index=i,
    #             scheduled_delivery_date=e.start_date if i == 1 else None,
    #             qr_token=_unique_qr_token()
    #         ))
    #     MonthlySupply.objects.bulk_create(objs, ignore_conflicts=True)

    # @staticmethod
    # def bootstrap_for_enrollment(e: "Enrollment"):
    #     """
    #     Create 3‑month (+~90d) and 6‑month (+~180d) milestones if missing.
    #     """
    #     existing = {m.milestone for m in e.milestones.all()}

    #     # --- Normalize to date to avoid string + timedelta TypeError ---
    #     start = e.start_date
    #     if isinstance(start, str):
    #         parsed = parse_date(start)
    #         if parsed is not None:
    #             start = parsed
    #         else:
    #             # as a fallback, load from DB which returns a proper date
    #             e.refresh_from_db(fields=["start_date"])
    #             start = e.start_date
    #     # ----------------------------------------------------------------

    #     rows = []
    #     if "MONTH_3" not in existing:
    #         rows.append(ScreeningMilestone(
    #             enrollment=e,
    #             milestone=ScreeningMilestone.Milestone.MONTH_3,
    #             due_on=start + timedelta(days=90),
    #         ))
    #     if "MONTH_6" not in existing:
    #         rows.append(ScreeningMilestone(
    #             enrollment=e,
    #             milestone=ScreeningMilestone.Milestone.MONTH_6,
    #             due_on=start + timedelta(days=180),
    #         ))

    #     # (whatever you already do to persist `rows`, e.g., bulk_create)
    @staticmethod
    def bootstrap_for_enrollment(e: "Enrollment"):
        existing = {m.milestone for m in e.milestones.all()}

        # Normalize before math, in case anything else in the future sets strings
        start = e.start_date
        if isinstance(start, str):
            start = parse_date(start)

        rows = []
        if "MONTH_3" not in existing:
            rows.append(ScreeningMilestone(
                enrollment=e,
                milestone=ScreeningMilestone.Milestone.MONTH_3,
                due_on=start + timedelta(days=90),
            ))
        if "MONTH_6" not in existing:
            rows.append(ScreeningMilestone(
                enrollment=e,
                milestone=ScreeningMilestone.Milestone.MONTH_6,
                due_on=start + timedelta(days=180),
            ))

        if rows:
            ScreeningMilestone.objects.bulk_create(rows)

class ComplianceSubmission(models.Model):
    class Status(models.TextChoices):
        NOT_SUBMITTED = "NOT_SUBMITTED", "Not submitted"
        COMPLIANT = "COMPLIANT", "Submitted & compliant"
        UNABLE = "UNABLE", "Submitted & unable"

    monthly_supply = models.OneToOneField(MonthlySupply, on_delete=models.CASCADE, related_name="compliance")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_SUBMITTED)
    submitted_at = models.DateTimeField(null=True, blank=True)
    responses = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.monthly_supply} → {self.status}"


# Optional: also generate supplies when someone creates an Enrollment directly (safety net)
# @receiver(post_save, sender=Enrollment)
# def _auto_generate_supplies(sender, instance: Enrollment, created: bool, **kwargs):
#     if created:
#         MonthlySupply.bootstrap_for_enrollment(instance)
@receiver(post_save, sender=Enrollment)
def _auto_generate_supplies_and_milestones(sender, instance: Enrollment, created: bool, **kwargs):
    if created:
        MonthlySupply.bootstrap_for_enrollment(instance)
        ScreeningMilestone.bootstrap_for_enrollment(instance)  # NEW

class ScreeningMilestone(models.Model):
    class Milestone(models.TextChoices):
        MONTH_3 = "MONTH_3", "3-month"
        MONTH_6 = "MONTH_6", "6-month"

    class Status(models.TextChoices):
        DUE = "DUE", "Due"
        COMPLETED = "COMPLETED", "Completed"
        OVERDUE = "OVERDUE", "Overdue"

    enrollment = models.ForeignKey("program.Enrollment", on_delete=models.CASCADE, related_name="milestones")
    milestone = models.CharField(max_length=16, choices=Milestone.choices)
    due_on = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DUE)

    completed_screening = models.ForeignKey("screening.Screening", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("enrollment","milestone"),)
        indexes = [
            models.Index(fields=["status","due_on"]),
            models.Index(fields=["enrollment","milestone"]),
        ]

    def __str__(self):
        return f"{self.enrollment.student.full_name} – {self.milestone} – {self.status}"

    @staticmethod
    def bootstrap_for_enrollment(e: "Enrollment"):
        """
        Create 3‑month (+~90d) and 6‑month (+~180d) milestones if missing.
        """
        existing = {m.milestone for m in e.milestones.all()}
        rows = []
        if "MONTH_3" not in existing:
            rows.append(ScreeningMilestone(
                enrollment=e,
                milestone=ScreeningMilestone.Milestone.MONTH_3,
                due_on=e.start_date + timedelta(days=90),
            ))
        if "MONTH_6" not in existing:
            rows.append(ScreeningMilestone(
                enrollment=e,
                milestone=ScreeningMilestone.Milestone.MONTH_6,
                due_on=e.start_date + timedelta(days=180),
            ))
        if rows:
            ScreeningMilestone.objects.bulk_create(rows, ignore_conflicts=True)

    def mark_completed(self, screening: Screening):
        if self.status == self.Status.COMPLETED:
            return
        self.status = self.Status.COMPLETED
        self.completed_screening = screening
        self.completed_at = timezone.now()
        self.save(update_fields=["status","completed_screening","completed_at","updated_at"])
