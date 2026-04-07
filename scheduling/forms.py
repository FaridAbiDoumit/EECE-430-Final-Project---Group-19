from django import forms

from .models import Player, SessionRSVP, TrainingSession


class TrainingSessionForm(forms.ModelForm):
    class Meta:
        model = TrainingSession
        fields = ['title', 'starts_at', 'location', 'session_type', 'notes']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class SessionRSVPForm(forms.Form):
    player = forms.ModelChoiceField(queryset=Player.objects.none())
    status = forms.ChoiceField(choices=SessionRSVP.Status.choices, widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['player'].queryset = Player.objects.filter(role=Player.Role.PLAYER)
