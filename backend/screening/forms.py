from django import forms
from roster.models import Student, Guardian
from .models import Screening

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
