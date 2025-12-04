from django import forms
from roster.models import Student, Classroom
from .models import Screening
from django.core.exceptions import ValidationError
import re
MCQ_FIELDS = [
    ("diet_diversity_low", "Does your child eat <5 kinds of vegetables/fruits per week?"),
    ("symptom_weight_loss", "Recent unintended weight loss?"),
    ("symptom_fatigue", "Fatigue / low energy?"),
    ("symptom_recurrent_illness", "Frequent illnesses?"),
    ("symptom_hair_skin", "Hair or skin issues?"),
]

class ScreeningForm(forms.ModelForm):
    # Parent phone entered once; accept 10-digit India mobile and normalize to +91...
    parent_phone_e164 = forms.CharField(label="Parent WhatsApp Number", required=False)

    # MCQs (boolean checkboxes)
    for field_key, _ in MCQ_FIELDS:
        locals()[field_key] = forms.BooleanField(required=False, label=_)
    del field_key, _

    class Meta:
        model = Screening
        fields = ["height_cm", "weight_kg", "age_years", "gender", "is_low_income_at_screen"]

    def __init__(self, *args, **kwargs):
        # student is OPTIONAL now; used only to prefill gender when available
        self.student = kwargs.pop("student", None)
        super().__init__(*args, **kwargs)
        if self.student:
            self.fields["gender"].initial = self.student.gender

    def clean_parent_phone_e164(self):
        raw = (self.cleaned_data.get("parent_phone_e164") or "").strip()
        if not raw:
            return ""
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10:
            return f"+91{digits}"
        if raw.startswith("+") and re.match(r"^\+\d{8,15}$", raw):
            return raw
        raise ValidationError("Enter a valid 10-digit Indian mobile number.")

    def clean(self):
        data = super().clean()
        # pack MCQs into answers JSON
        answers = {}
        for field_key, _label in MCQ_FIELDS:
            answers[field_key] = bool(self.cleaned_data.get(field_key))
        data["answers"] = answers
        return data



LANG_CHOICES = (
    ("en", "English"),
    ("hi", "Hindi"),
    ("local", "Local language"),
)

class AddStudentForm(forms.Form):
    """
    Minimal student+classroom information for the combined Add & Screen page.
    Guardian fields and student_code are intentionally omitted.
    Grade/Division are constrained to existing classrooms.
    """
    # Classroom (dropdowns)
    grade = forms.ChoiceField(choices=[])
    division = forms.ChoiceField(choices=[])

    # Student (master)
    first_name = forms.CharField(label="First name", max_length=128)
    last_name = forms.CharField(label="Last name", max_length=128, required=False)
    dob = forms.DateField(label="Date of birth", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    is_low_income = forms.BooleanField(label="Low income family (master)", required=False)

    def __init__(self, *args, **kwargs):
        self.org = kwargs.pop("organization")
        super().__init__(*args, **kwargs)

        # Build Grade choices from existing classrooms
        grades_qs = (
            Classroom.objects.filter(organization=self.org)
            .values_list("grade", flat=True)
            .distinct()
            .order_by("grade")
        )
        grade_choices = [("", "Select grade")]
        grade_choices += [(g, g) for g in grades_qs]
        self.fields["grade"].choices = grade_choices

        # Division for the initial grade (client-side JS will update on change)
        initial_grade = self.initial.get("grade") or (grades_qs.first() if hasattr(grades_qs, "first") else None)
        div_qs = (
            Classroom.objects.filter(organization=self.org, grade=initial_grade)
            .values_list("division", flat=True)
            .order_by("division")
            .distinct()
        )
        div_choices = [("", "Select division")]
        div_choices += [(d, d or "—") for d in div_qs]
        self.fields["division"].choices = div_choices

    def clean(self):
        data = super().clean()
        grade = data.get("grade") or ""
        division = data.get("division") or ""
        if grade:
            exists = Classroom.objects.filter(
                organization=self.org, grade=grade, division=division
            ).exists()
            if not exists:
                raise ValidationError("Selected Grade/Division does not exist. Please ask admin to create the class first.")

        # Gentle duplicate check by name + DOB
        fn = (data.get("first_name") or "").strip()
        ln = (data.get("last_name") or "").strip()
        dob = data.get("dob")
        if fn and dob:
            if Student.objects.filter(
                organization=self.org,
                first_name__iexact=fn,
                last_name__iexact=ln,
                dob=dob,
            ).exists():
                raise ValidationError("A student with the same name and date of birth already exists in your school.")
        return data