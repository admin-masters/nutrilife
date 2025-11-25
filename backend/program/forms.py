from django import forms

class ComplianceForm(forms.Form):
    CHOICES = [
        ("COMPLIANT", "Yes, we were able to give the supplement daily or almost daily."),
        ("UNABLE", "No, we were unable to comply."),
    ]
    status = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    notes = forms.CharField(widget=forms.Textarea, required=False, label="Anything you'd like to tell us? (optional)")
