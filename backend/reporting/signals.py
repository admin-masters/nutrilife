"""Reporting rollup signals.

The Inditech and school dashboards read from reporting.models.SchoolStatDaily.
Historically these rollups were only generated via a management command or a
nightly Celery beat job, which meant dashboards could show all zeros unless a
backfill was run.

These signals keep daily rollups current by rebuilding the relevant day whenever
source data changes.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from assist.models import Application
from program.models import ComplianceSubmission, Enrollment, MonthlySupply, ScreeningMilestone
from screening.models import Screening

from .services import build_daily_rollup


def _local_day(dt) -> date | None:
    if not dt:
        return None
    try:
        return timezone.localtime(dt).date()
    except Exception:
        return dt.date()


def _queue_rebuild(org, day: date | None):
    if not org or not day:
        return
    transaction.on_commit(lambda: build_daily_rollup(org, day))


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=Screening)
def _screening_capture_previous(sender, instance: Screening, **kwargs):
    if not instance.pk:
        return
    try:
        prev = Screening.objects.get(pk=instance.pk)
    except Screening.DoesNotExist:
        return
    instance._prev_screened_at = prev.screened_at
    instance._prev_org_id = prev.organization_id


@receiver(post_save, sender=Screening)
@receiver(post_delete, sender=Screening)
def _screening_refresh_rollup(sender, instance: Screening, **kwargs):
    _queue_rebuild(instance.organization, _local_day(getattr(instance, "screened_at", None)))

    prev_dt = getattr(instance, "_prev_screened_at", None)
    prev_org_id = getattr(instance, "_prev_org_id", None)
    if prev_dt and prev_org_id and prev_org_id != instance.organization_id:
        from accounts.models import Organization
        try:
            prev_org = Organization.objects.get(pk=prev_org_id)
        except Organization.DoesNotExist:
            prev_org = None
        _queue_rebuild(prev_org, _local_day(prev_dt))
    elif prev_dt:
        _queue_rebuild(instance.organization, _local_day(prev_dt))


# ---------------------------------------------------------------------------
# Applications (supplement requests)
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=Application)
def _application_capture_previous(sender, instance: Application, **kwargs):
    if not instance.pk:
        return
    try:
        prev = Application.objects.get(pk=instance.pk)
    except Application.DoesNotExist:
        return
    instance._prev_applied_at = prev.applied_at
    instance._prev_forwarded_at = prev.forwarded_at
    instance._prev_reviewed_at = prev.sapa_reviewed_at
    instance._prev_org_id = prev.organization_id


@receiver(post_save, sender=Application)
@receiver(post_delete, sender=Application)
def _application_refresh_rollup(sender, instance: Application, **kwargs):
    from accounts.models import Organization

    orgs: list[Organization] = []
    if getattr(instance, "organization_id", None):
        orgs.append(instance.organization)
    prev_org_id = getattr(instance, "_prev_org_id", None)
    if prev_org_id and prev_org_id != instance.organization_id:
        try:
            orgs.append(Organization.objects.get(pk=prev_org_id))
        except Organization.DoesNotExist:
            pass

    days: set[date] = set()
    for dt in (
        getattr(instance, "applied_at", None),
        getattr(instance, "forwarded_at", None),
        getattr(instance, "sapa_reviewed_at", None),
        getattr(instance, "_prev_applied_at", None),
        getattr(instance, "_prev_forwarded_at", None),
        getattr(instance, "_prev_reviewed_at", None),
    ):
        d = _local_day(dt)
        if d:
            days.add(d)

    for org in orgs:
        for day in days:
            _queue_rebuild(org, day)


# ---------------------------------------------------------------------------
# Program logistics / compliance
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=Enrollment)
def _enrollment_capture_previous(sender, instance: Enrollment, **kwargs):
    if not instance.pk:
        return
    try:
        prev = Enrollment.objects.get(pk=instance.pk)
    except Enrollment.DoesNotExist:
        return
    instance._prev_created_at = prev.created_at


@receiver(post_save, sender=Enrollment)
@receiver(post_delete, sender=Enrollment)
def _enrollment_refresh_rollup(sender, instance: Enrollment, **kwargs):
    _queue_rebuild(instance.organization, _local_day(getattr(instance, "created_at", None)))
    prev_dt = getattr(instance, "_prev_created_at", None)
    if prev_dt:
        _queue_rebuild(instance.organization, _local_day(prev_dt))


@receiver(pre_save, sender=MonthlySupply)
def _monthly_supply_capture_previous(sender, instance: MonthlySupply, **kwargs):
    if not instance.pk:
        return
    try:
        prev = MonthlySupply.objects.get(pk=instance.pk)
    except MonthlySupply.DoesNotExist:
        return
    instance._prev_delivered_on = prev.delivered_on


@receiver(post_save, sender=MonthlySupply)
@receiver(post_delete, sender=MonthlySupply)
def _monthly_supply_refresh_rollup(sender, instance: MonthlySupply, **kwargs):
    org = instance.enrollment.organization if getattr(instance, "enrollment_id", None) else None
    _queue_rebuild(org, getattr(instance, "delivered_on", None))
    prev_day = getattr(instance, "_prev_delivered_on", None)
    if prev_day:
        _queue_rebuild(org, prev_day)


@receiver(pre_save, sender=ComplianceSubmission)
def _compliance_capture_previous(sender, instance: ComplianceSubmission, **kwargs):
    if not instance.pk:
        return
    try:
        prev = ComplianceSubmission.objects.get(pk=instance.pk)
    except ComplianceSubmission.DoesNotExist:
        return
    instance._prev_submitted_at = prev.submitted_at


@receiver(post_save, sender=ComplianceSubmission)
@receiver(post_delete, sender=ComplianceSubmission)
def _compliance_refresh_rollup(sender, instance: ComplianceSubmission, **kwargs):
    org = None
    if getattr(instance, "monthly_supply_id", None):
        try:
            org = instance.monthly_supply.enrollment.organization
        except Exception:
            org = None

    _queue_rebuild(org, _local_day(getattr(instance, "submitted_at", None)))
    prev_dt = getattr(instance, "_prev_submitted_at", None)
    if prev_dt:
        _queue_rebuild(org, _local_day(prev_dt))


@receiver(pre_save, sender=ScreeningMilestone)
def _milestone_capture_previous(sender, instance: ScreeningMilestone, **kwargs):
    if not instance.pk:
        return
    try:
        prev = ScreeningMilestone.objects.get(pk=instance.pk)
    except ScreeningMilestone.DoesNotExist:
        return
    instance._prev_due_on = prev.due_on
    instance._prev_updated_at = prev.updated_at
    instance._prev_completed_at = getattr(prev, "completed_at", None)


@receiver(post_save, sender=ScreeningMilestone)
@receiver(post_delete, sender=ScreeningMilestone)
def _milestone_refresh_rollup(sender, instance: ScreeningMilestone, **kwargs):
    org = instance.enrollment.organization if getattr(instance, "enrollment_id", None) else None

    days: set[date] = set()
    for d in (getattr(instance, "due_on", None), getattr(instance, "_prev_due_on", None)):
        if d:
            days.add(d)

    for dt in (
        getattr(instance, "updated_at", None),
        getattr(instance, "completed_at", None),
        getattr(instance, "_prev_updated_at", None),
        getattr(instance, "_prev_completed_at", None),
    ):
        d = _local_day(dt)
        if d:
            days.add(d)

    for day in days:
        _queue_rebuild(org, day)
