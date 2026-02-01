"""Roster domain services.

Current use:
  - Seed default Classroom rows for new SCHOOL organizations so teachers can
    immediately select Grade/Division in the "Add student" flow.
"""

from __future__ import annotations

from django.db import transaction

from accounts.models import Organization
from .models import Classroom


def _grades_nursery_to_12() -> list[str]:
    return ["Nursery", "K.G."] + [str(i) for i in range(1, 13)]


def _sections_a_to_z() -> list[str]:
    return [chr(c) for c in range(ord("A"), ord("Z") + 1)]


@transaction.atomic
def ensure_default_classrooms_for_school(org: Organization) -> int:
    """Ensure default classroom (grade/division) rows exist for a SCHOOL org.

    Creates:
      - Grades: Nursery, K.G., 1..12, Other
      - Sections: A..Z, Other (for each grade)
      - For the "Other" grade, we only create section "Other" to avoid
        meaningless combinations like "Other-A".

    Idempotent: safe to call multiple times.

    Returns:
      Number of Classroom objects attempted to be created.
    """
    if not org or org.org_type != Organization.OrgType.SCHOOL:
        return 0

    grades: list[str] = _grades_nursery_to_12() + ["Other"]
    sections: list[str] = _sections_a_to_z() + ["Other"]

    rows: list[Classroom] = []
    for grade in grades:
        if grade == "Other":
            # Keep "Other" as a valid fallback, but avoid generating 26 extra
            # combinations that have no real meaning.
            rows.append(Classroom(organization=org, grade="Other", division="Other"))
            continue

        for section in sections:
            rows.append(Classroom(organization=org, grade=grade, division=section))

    # INSERT IGNORE (MySQL) / ON CONFLICT DO NOTHING (Postgres) behavior.
    Classroom.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
    return len(rows)
