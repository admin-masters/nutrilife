import csv
from datetime import timedelta
from django.http import HttpResponse
from django.utils import timezone
from accounts.decorators import require_roles
from accounts.models import Role
from .models import Screening
from audit.utils import audit_log

@require_roles(Role.ORG_ADMIN, Role.INDITECH, allow_superuser=True)
def export_screenings_csv(request):
    org = getattr(request, "org", None)
    if not org:
        return HttpResponse("Organization context required", status=403)

    # Last 6 months by default (matches dashboard text on p.8)
    since = request.GET.get("since")
    if since:
        try:
            from datetime import datetime
            since = datetime.fromisoformat(since)
        except Exception:
            since = timezone.now() - timedelta(days=180)
    else:
        since = timezone.now() - timedelta(days=180)

    qs = (Screening.objects
          .select_related("student", "student__classroom", "student__primary_guardian")
          .filter(organization=org, screened_at__gte=since)
          .order_by("-screened_at"))
    audit_log(request.user, org, "CSV_EXPORTED", payload={"count": qs.count()})
    
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="screenings.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Screened At", "Student Name", "Gender", "Age (years)", "Classroom",
        "Parent Phone", "Height (cm)", "Weight (kg)", "BMI (approx)",
        "Risk", "Red Flags"
    ])
    for s in qs:
        # compute BMI for export only
        bmi = ""
        if s.height_cm and s.weight_kg and float(s.height_cm) > 0:
            h = float(s.height_cm) / 100.0
            bmi = round(float(s.weight_kg) / (h*h), 1)
        guardian_phone = s.student.primary_guardian.phone_e164 if s.student.primary_guardian else ""
        classroom = s.student.classroom or ""
        writer.writerow([
            s.screened_at.strftime("%Y-%m-%d %H:%M"),
            s.student.full_name,
            s.gender,
            s.age_years or "",
            str(classroom),
            guardian_phone,
            s.height_cm or "",
            s.weight_kg or "",
            bmi,
            s.risk_level,
            ";".join(s.red_flags or []),
        ])
    return response
