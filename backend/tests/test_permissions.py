import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Organization, OrgMembership, Role

User = get_user_model()

@pytest.mark.django_db
def test_org_admin_can_see_school_reporting(client):
    org = Organization.objects.create(name="Test School", screening_link_token="test-123")
    u = User.objects.create_user(email="admin@test", password="x")
    OrgMembership.objects.create(user=u, organization=org, role=Role.ORG_ADMIN)
    client.login(email="admin@test", password="x")
    resp = client.get(reverse("reporting:school_dashboard") + f"?org={org.id}")
    assert resp.status_code in (200, 302)

@pytest.mark.django_db
def test_teacher_cannot_see_inditech_console(client):
    org = Organization.objects.create(name="Test School", screening_link_token="test-123")
    u = User.objects.create_user(email="t@test", password="x")
    OrgMembership.objects.create(user=u, organization=org, role=Role.TEACHER)
    client.login(email="t@test", password="x")
    resp = client.get(reverse("reporting:inditech_console"))
    assert resp.status_code == 403

@pytest.mark.django_db
def test_suspended_school_blocked_delivery(client):
    from program.models import Enrollment, MonthlySupply
    org = Organization.objects.create(name="Test School", screening_link_token="t-1", assistance_suspended=True)
    u = User.objects.create_user(email="admin@test", password="x", is_staff=True)
    OrgMembership.objects.create(user=u, organization=org, role=Role.ORG_ADMIN)
    client.login(email="admin@test", password="x")
    # fake supply row
    from roster.models import Student
    st = Student.objects.create(organization=org, first_name="A", gender="M")
    from assist.models import Application
    app = Application.objects.create(organization=org, student=st, status="APPROVED")
    from program.models import Enrollment
    e = Enrollment.objects.create(organization=org, application=app, student=st, start_date="2024-01-01", end_date="2024-07-01")
    from program.models import MonthlySupply
    ms = MonthlySupply.objects.create(enrollment=e, month_index=1, qr_token="q", delivered_on=None)
    resp = client.post(reverse("program:mark_delivered", args=[ms.id]) + f"?org={org.id}")
    assert resp.status_code == 403
