from django import forms
from roster.models import Student, Guardian
from .models import Screening
from django.core.exceptions import ValidationError

MCQ_FIELDS = [
    ("diet_diversity_low", "Does your child eat <5 kinds of vegetables/fruits per week?"),
    ("symptom_weight_loss", "Recent unintended weight loss?"),
    ("symptom_fatigue", "Fatigue / low energy?"),
    ("symptom_recurrent_illness", "Frequent illnesses?"),
    ("symptom_hair_skin", "Hair or skin issues?"),
]

class ScreeningForm(forms.ModelForm):
    # Parent phone entered at screening time (creates/links guardian if needed)
    parent_phone_e164 = forms.CharField(label="Parent WhatsApp Number (+countrycode...)", required=False)

    # MCQs (boolean checkboxes)
    for field_key, _ in MCQ_FIELDS:
        locals()[field_key] = forms.BooleanField(required=False, label=_)
    del field_key, _

    class Meta:
        model = Screening
        fields = ["height_cm", "weight_kg", "age_years", "gender", "is_low_income_at_screen"]

    def __init__(self, *args, **kwargs):
        self.student = kwargs.pop("student")
        super().__init__(*args, **kwargs)
        # default gender from student
        self.fields["gender"].initial = self.student.gender

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
    # Guardian
    guardian_full_name = forms.CharField(label="Guardian full name", max_length=255)
    guardian_phone_e164 = forms.CharField(label="Guardian WhatsApp (+countrycode…)", max_length=20)
    whatsapp_opt_in = forms.BooleanField(label="WhatsApp opt-in", required=False, initial=True)
    preferred_language = forms.ChoiceField(choices=LANG_CHOICES, initial="en")

    # Classroom
    grade = forms.CharField(label="Grade", max_length=64)
    division = forms.CharField(label="Division", max_length=64, required=False)

    # Student
    first_name = forms.CharField(label="First name", max_length=128)
    last_name = forms.CharField(label="Last name", max_length=128, required=False)
    gender = forms.ChoiceField(choices=Student.Gender.choices)
    dob = forms.DateField(label="Date of birth", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    is_low_income = forms.BooleanField(label="Low income family", required=False)
    student_code = forms.CharField(
        label="Student code (leave blank to auto-generate)",
        max_length=64,
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.org = kwargs.pop("organization")
        super().__init__(*args, **kwargs)

    def clean_guardian_phone_e164(self):
        phone = (self.cleaned_data.get("guardian_phone_e164") or "").strip()
        # Simple E.164 validation: + then 8-15 digits
        import re
        if not re.match(r"^\+\d{8,15}$", phone):
            raise ValidationError("Enter phone in E.164 format, e.g. +919876543210")
        return phone

    def clean_student_code(self):
        code = (self.cleaned_data.get("student_code") or "").strip()
        if code and Student.objects.filter(organization=self.org, student_code=code).exists():
            raise ValidationError("A student with this code already exists in your school.")
        return code

    def clean(self):
        data = super().clean()
        # Gentle duplicate check by name + DOB (does not rely on DB constraint)
        fn = (data.get("first_name") or "").strip()
        ln = (data.get("last_name") or "").strip()
        dob = data.get("dob")
        if fn and dob:
            qs = Student.objects.filter(
                organization=self.org,
                first_name__iexact=fn,
                last_name__iexact=ln,
                dob=dob
            )
            if qs.exists():
                raise ValidationError(
                    "A student with the same name and date of birth already exists in your school. "
                    "Use the list in Teacher Portal to open their screening."
                )
        return data
