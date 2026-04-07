from django import forms

from .models import (
    Player,
    PlayerAvailability,
    PersonalSessionNote,
    SessionRSVP,
    SessionPlan,
    SessionVote,
    SessionVoteOption,
    SessionVotePoll,
    TryoutCandidate,
    TryoutSession,
    TrainingSession,
)


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


class PlayerAvailabilityForm(forms.ModelForm):
    class Meta:
        model = PlayerAvailability
        fields = ['player', 'weekday', 'start_time', 'end_time', 'notes']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['player'].queryset = Player.objects.filter(role=Player.Role.PLAYER)

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if start_time and end_time and start_time >= end_time:
            self.add_error('end_time', 'End time must be after start time.')
        return cleaned_data


class SessionVotePollForm(forms.ModelForm):
    option_1_starts_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    option_1_location = forms.CharField(max_length=120)
    option_2_starts_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    option_2_location = forms.CharField(max_length=120)

    class Meta:
        model = SessionVotePoll
        fields = ['title', 'description', 'closes_at']
        widgets = {
            'closes_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class SessionVoteForm(forms.Form):
    player = forms.ModelChoiceField(queryset=Player.objects.none())
    option = forms.ModelChoiceField(queryset=SessionVoteOption.objects.none(), widget=forms.RadioSelect)

    def __init__(self, *args, poll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['player'].queryset = Player.objects.filter(role=Player.Role.PLAYER)
        if poll is not None:
            self.fields['option'].queryset = poll.options.all()


class SessionPlanForm(forms.ModelForm):
    class Meta:
        model = SessionPlan
        fields = ['title', 'drills']


class PersonalSessionNoteForm(forms.ModelForm):
    class Meta:
        model = PersonalSessionNote
        fields = ['player', 'content']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['player'].queryset = Player.objects.filter(role=Player.Role.PLAYER)


class TryoutSessionForm(forms.ModelForm):
    class Meta:
        model = TryoutSession
        fields = ['title', 'starts_at', 'location', 'registration_open']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class TryoutCandidateForm(forms.ModelForm):
    class Meta:
        model = TryoutCandidate
        fields = ['tryout_session', 'name', 'email', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tryout_session'].queryset = TryoutSession.objects.filter(registration_open=True)


class PlayerUpdateForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ['status', 'is_active']
