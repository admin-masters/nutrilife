from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import re

from roster.models import Student, Classroom
from .models import Screening

def _normalize_phone_to_e164(raw: str) -> str:
    raw = (raw or "").strip()
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

def _age_months(dob, as_of_date) -> int:
    if not dob:
        raise ValidationError("Date of birth is required.")
    y = as_of_date.year - dob.year
    m = as_of_date.month - dob.month
    months = y * 12 + m
    if as_of_date.day < dob.day:
        months -= 1
    return max(months, 0)

_BOOL_CHOICES = (("yes", "Yes"), ("no", "No"))

def _coerce_bool(v):
    if v in (True, "True", "true", "1", "yes", "YES", "on"):
        return True
    if v in (False, "False", "false", "0", "no", "NO", "off"):
        return False
    return None

def YesNoField(label: str, *, required: bool = True):
    return forms.TypedChoiceField(
        label=label,
        choices=_BOOL_CHOICES,
        coerce=lambda x: _coerce_bool(x),
        required=required,
        widget=forms.RadioSelect,
    )

class NewScreeningForm(forms.ModelForm):
    # SECTION A
    student_name = forms.CharField(label="Student Name", max_length=255, required=True)
    unique_student_id = forms.CharField(label="Unique Student ID", max_length=64, required=True)
    dob = forms.DateField(label="Date of Birth (DOB)", required=True,
                          widget=forms.DateInput(attrs={"type": "date"}))
    sex = forms.ChoiceField(label="Sex", choices=(("M", "Male"), ("F", "Female")), required=True)
    parent_phone_e164 = forms.CharField(label="Parent WhatsApp No.", required=True)

        # SECTION B
    # NOTE: Only ONE reading each is required (as per field feedback).
    weight_kg_r1 = forms.DecimalField(label="Weight (kg)", max_digits=5, decimal_places=2)
    height_cm_r1 = forms.DecimalField(label="Height (cm)", max_digits=5, decimal_places=2)
    muac_cm = forms.DecimalField(label="Mid-Upper Arm Circumference (MUAC) (cm)",
                                 max_digits=5, decimal_places=2, required=False)


    # SECTION C
    health_general_poor = forms.BooleanField(label="General health is poor", required=False)
    health_pallor = forms.BooleanField(label="Pallor (pale inside eyelids/palms)", required=False)
    health_fatigue_dizzy_faint = forms.BooleanField(label="Fatigue, dizziness, or fainting", required=False)
    health_breathlessness = forms.BooleanField(label="Breathlessness on exertion", required=False)
    health_frequent_infections = forms.BooleanField(label="Frequent infections (3 or more in last month)", required=False)
    health_chronic_cough_or_diarrhea = forms.BooleanField(label="Chronic cough or chronic diarrhea", required=False)
    health_visible_worms = forms.BooleanField(label="Visible worm passage", required=False)
    health_dental_or_gum_or_ulcers = forms.BooleanField(label="Dental caries, gum bleeding, or mouth ulcers", required=False)
    health_night_vision_difficulty = forms.BooleanField(label="Night vision difficulty (stumbling in dim light)", required=False)
    health_bone_or_joint_pain = forms.BooleanField(label="Bone or joint pains", required=False)

    appetite = forms.ChoiceField(
        label="Appetite",
        choices=(("GOOD", "Good"), ("NORMAL", "Normal"), ("POOR", "Poor")),
        widget=forms.RadioSelect,
        required=True,
    )

    # Girls (Age ≥10 only)
    menarche_started = forms.BooleanField(label="Has menarche started?", required=False)
    menarche_age_years = forms.DecimalField(label="Age at 1st period (years)", max_digits=4, decimal_places=1, required=False)
    pads_per_day = forms.IntegerField(label="Heavy bleeding – pads/day", required=False, min_value=0)
    bleeding_clots = forms.BooleanField(label="Heavy bleeding – passing clots", required=False)
    cycle_length_days = forms.IntegerField(label="Cycle length (days between menses)", required=False, min_value=0)

    # SECTION D
    diet_type = forms.ChoiceField(
        label="Usual Diet Type",
        choices=(("LACTO_VEG", "Lacto-vegetarian"),
                 ("LACTO_OVO", "Lacto-ovo-vegetarian (eats eggs)"),
                 ("NON_VEG", "Non-vegetarian")),
        widget=forms.RadioSelect,
        required=True,
    )

    breakfast_eaten = YesNoField("Breakfast eaten?")
    lunch_eaten = YesNoField("Lunch eaten at school?")
    green_leafy_veg = YesNoField("Green leafy veg (Palak/Methi/Amaranth)")
    other_vegetables = YesNoField("Other vegetables")
    fruits = YesNoField("Fruits")
    dal_pulses_beans = YesNoField("Dal / Pulses / Beans")
    milk_curd = YesNoField("Milk / Curd")
    egg = YesNoField("Egg")
    fish_chicken_meat = YesNoField("Fish / Chicken / Meat")
    nuts_groundnuts = YesNoField("Nuts / Groundnuts")
    millet_whole_grains = YesNoField("Millet / Whole grains")
    ssb_or_packaged_snacks = YesNoField("SSB (Sugary Drinks) or Packaged Snacks eaten?")

    # SECTION E
    deworming_taken = YesNoField("Deworming taken in last 6–12 months?")
    _DEWORMING_MONTHS_CHOICES = [
        ('', 'Select months'),
        *[(str(i), f"{i} month" if i == 1 else f"{i} months") for i in range(1, 13)],
    ]
    deworming_date = forms.TypedChoiceField(
        label="If yes, how many months ago?",
        choices=_DEWORMING_MONTHS_CHOICES,
        required=False,
        coerce=lambda x: int(x) if x else None,
        widget=forms.Select,
    )

    # SECTION F
    hunger_vital_sign = forms.ChoiceField(
        label='"We do not get enough food at home." (Last 12 months)',
        choices=(("OFTEN_TRUE", "Often true"),
                 ("SOMETIMES_TRUE", "Sometimes true"),
                 ("NEVER_TRUE", "Never true")),
        widget=forms.RadioSelect,
        required=True,
    )

    class Meta:
        model = Screening
        fields = []

    def __init__(self, *args, **kwargs):
        self.student = kwargs.pop("student", None)
        self.org = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        if self.student:
            self.fields["student_name"].initial = self.student.full_name
            self.fields["student_name"].disabled = True

            if getattr(self.student, "student_code", ""):
                self.fields["unique_student_id"].initial = self.student.student_code
            if getattr(self.student, "dob", None):
                self.fields["dob"].initial = self.student.dob
            if getattr(self.student, "gender", None) in {"M", "F"}:
                self.fields["sex"].initial = self.student.gender

            g = getattr(self.student, "primary_guardian", None)
            if g and getattr(g, "phone_e164", ""):
                self.fields["parent_phone_e164"].initial = g.phone_e164

    def clean_parent_phone_e164(self):
        return _normalize_phone_to_e164(self.cleaned_data.get("parent_phone_e164"))

    def clean_unique_student_id(self):
        code = (self.cleaned_data.get("unique_student_id") or "").strip()
        if not code:
            raise ValidationError("Unique Student ID is required.")
        if self.student:
            qs = Student.objects.filter(
                organization=self.student.organization,
                student_code__iexact=code
            ).exclude(pk=self.student.pk)
            if qs.exists():
                raise ValidationError("This Unique Student ID is already used by another student.")
        else:
            if self.org and Student.objects.filter(organization=self.org, student_code__iexact=code).exists():
                raise ValidationError("This Unique Student ID is already used by another student in your school.")
        return code

    def clean(self):
        data = super().clean()

        dob = data.get("dob")
        today = timezone.localdate()
        months = _age_months(dob, today)
        age_years = round(months / 12.0, 2)

        # NOTE: Only ONE reading each is required (as per field feedback).
        w1 = data.get("weight_kg_r1")
        h1 = data.get("height_cm_r1")

        try:
            weight_kg = float(w1)
        except Exception:
            raise ValidationError("Weight is required.")
        try:
            height_cm = float(h1)
        except Exception:
            raise ValidationError("Height is required.")


        if not (5 <= weight_kg <= 200):
            raise ValidationError("Weight seems out of range. Please re-check readings.")
        if not (50 <= height_cm <= 250):
            raise ValidationError("Height seems out of range. Please re-check readings.")

        muac = data.get("muac_cm")
        if muac is not None and not (5 <= float(muac) <= 35):
            raise ValidationError("MUAC seems out of range. Please re-check.")

        answers = {
            # A
            "student_name": data.get("student_name"),
            "unique_student_id": data.get("unique_student_id"),
            "dob": str(dob) if dob else None,
            "sex": data.get("sex"),
            "parent_phone_e164": data.get("parent_phone_e164"),

            # B
            "weight_kg_r1": str(w1) if w1 is not None else None,
            "height_cm_r1": str(h1) if h1 is not None else None,


            # C
            "health_general_poor": bool(data.get("health_general_poor")),
            "health_pallor": bool(data.get("health_pallor")),
            "health_fatigue_dizzy_faint": bool(data.get("health_fatigue_dizzy_faint")),
            "health_breathlessness": bool(data.get("health_breathlessness")),
            "health_frequent_infections": bool(data.get("health_frequent_infections")),
            "health_chronic_cough_or_diarrhea": bool(data.get("health_chronic_cough_or_diarrhea")),
            "health_visible_worms": bool(data.get("health_visible_worms")),
            "health_dental_or_gum_or_ulcers": bool(data.get("health_dental_or_gum_or_ulcers")),
            "health_night_vision_difficulty": bool(data.get("health_night_vision_difficulty")),
            "health_bone_or_joint_pain": bool(data.get("health_bone_or_joint_pain")),
            "appetite": data.get("appetite"),

            "menarche_started": bool(data.get("menarche_started")),
            "menarche_age_years": float(data.get("menarche_age_years")) if data.get("menarche_age_years") is not None else None,
            "pads_per_day": data.get("pads_per_day"),
            "bleeding_clots": bool(data.get("bleeding_clots")),
            "cycle_length_days": data.get("cycle_length_days"),

            # D
            "diet_type": data.get("diet_type"),
            "breakfast_eaten": data.get("breakfast_eaten"),
            "lunch_eaten": data.get("lunch_eaten"),
            "green_leafy_veg": data.get("green_leafy_veg"),
            "other_vegetables": data.get("other_vegetables"),
            "fruits": data.get("fruits"),
            "dal_pulses_beans": data.get("dal_pulses_beans"),
            "milk_curd": data.get("milk_curd"),
            "egg": data.get("egg"),
            "fish_chicken_meat": data.get("fish_chicken_meat"),
            "nuts_groundnuts": data.get("nuts_groundnuts"),
            "millet_whole_grains": data.get("millet_whole_grains"),
            "ssb_or_packaged_snacks": data.get("ssb_or_packaged_snacks"),

            # E
            "deworming_taken": data.get("deworming_taken"),
            "deworming_date": data.get("deworming_date"),

            # F
            "hunger_vital_sign": data.get("hunger_vital_sign"),
        }

        data["_derived"] = {
            "age_months": months,
            "age_years": age_years,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "muac_cm": float(muac) if muac is not None else None,
        }
        data["answers"] = answers
        return data

class AddStudentForm(forms.Form):
    grade = forms.ChoiceField(choices=[])
    division = forms.ChoiceField(choices=[])
    is_low_income = forms.BooleanField(label="Low income family", required=False)

    def __init__(self, *args, **kwargs):
        self.org = kwargs.pop("organization")
        super().__init__(*args, **kwargs)

        grades_qs = (
            Classroom.objects.filter(organization=self.org)
            .values_list("grade", flat=True)
            .distinct()
            .order_by("grade")
        )
        self.fields["grade"].choices = [("", "Select grade")] + [(g, g) for g in grades_qs]

        initial_grade = self.initial.get("grade") or (grades_qs.first() if hasattr(grades_qs, "first") else None)
        div_qs = (
            Classroom.objects.filter(organization=self.org, grade=initial_grade)
            .values_list("division", flat=True)
            .order_by("division")
            .distinct()
        )
        self.fields["division"].choices = [("", "Select division")] + [(d, d or "—") for d in div_qs]

    def clean(self):
        data = super().clean()
        grade = data.get("grade") or ""
        division = data.get("division") or ""
        if grade and not Classroom.objects.filter(organization=self.org, grade=grade, division=division).exists():
            raise ValidationError("Selected Grade/Division does not exist. Please ask admin to create the class first.")
        return data
