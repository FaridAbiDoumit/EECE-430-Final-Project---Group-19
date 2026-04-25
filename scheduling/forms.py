from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from .models import (
    Player,
    PlayerAvailability,
    PlayerSorenessReport,
    PersonalSessionNote,
    SessionRSVP,
    SessionPlan,
    SessionVote,
    SessionVoteOption,
    SessionVotePoll,
    TryoutCandidate,
    TryoutSession,
    TrainingSession,
    Message,
    SupportTicket,
    Match,
    PlayerMatchStat,
    TeamGoal,
)


User = get_user_model()


class TrainingSessionForm(forms.ModelForm):
    class Meta:
        model = TrainingSession
        fields = ['title', 'starts_at', 'ends_at', 'location', 'session_type', 'notes']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get('starts_at')
        ends_at = cleaned_data.get('ends_at')
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error('ends_at', 'End time must be after start time.')
        return cleaned_data


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
    option = forms.ModelChoiceField(queryset=SessionVoteOption.objects.none(), widget=forms.RadioSelect)

    def __init__(self, *args, poll=None, **kwargs):
        super().__init__(*args, **kwargs)
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
        fields = ['title', 'starts_at', 'location', 'description', 'registration_open']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].widget.attrs.update({'class': 'auth-input', 'placeholder': 'Tryout title'})
        self.fields['starts_at'].widget.attrs.update({'class': 'auth-input'})
        self.fields['location'].widget.attrs.update({'class': 'auth-input', 'placeholder': 'Location'})
        self.fields['description'].widget.attrs.update(
            {
                'class': 'auth-textarea',
                'placeholder': 'Details for players: what to bring, arrival time, expectations, and any notes.',
            }
        )

    def clean_starts_at(self):
        starts_at = self.cleaned_data['starts_at']
        if starts_at <= timezone.now():
            raise forms.ValidationError('Tryout date and time must be in the future.')
        return starts_at


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
        fields = ['status', 'medical_certification_expiry', 'contract_expiry']
        widgets = {
            'medical_certification_expiry': forms.DateInput(attrs={'type': 'date'}),
            'contract_expiry': forms.DateInput(attrs={'type': 'date'}),
        }


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['subject', 'content']
        widgets = {
            'subject': forms.TextInput(attrs={'placeholder': 'Message subject', 'class': 'form-input'}),
            'content': forms.Textarea(attrs={'placeholder': 'Type your message...', 'class': 'form-textarea', 'rows': 4}),
        }


class ChatMessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'placeholder': 'Write your message...', 'class': 'form-textarea', 'rows': 4}),
        }


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['subject', 'message', 'priority']
        widgets = {
            'subject': forms.TextInput(attrs={'placeholder': 'Support subject', 'class': 'form-input'}),
            'message': forms.Textarea(attrs={'placeholder': 'Describe your issue...', 'class': 'form-textarea', 'rows': 4}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
        }


class MatchForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = ['opponent', 'date', 'goals_for', 'goals_against', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class PlayerMatchStatForm(forms.ModelForm):
    class Meta:
        model = PlayerMatchStat
        fields = ['player', 'goals', 'interceptions', 'points', 'blocks', 'assists', 'aces', 'returns', 'most_recent_injury']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['player'].queryset = Player.objects.filter(role=Player.Role.PLAYER)


class TeamGoalForm(forms.ModelForm):
    class Meta:
        model = TeamGoal
        fields = ['description', 'metric', 'target_value']
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'Shared team objective'}),
            'target_value': forms.NumberInput(attrs={'min': 1}),
        }


class PlayerSorenessReportForm(forms.ModelForm):
    class Meta:
        model = PlayerSorenessReport
        fields = ['soreness_level', 'notes']
        widgets = {
            'soreness_level': forms.NumberInput(attrs={'min': 1, 'max': 10}),
            'notes': forms.TextInput(attrs={'placeholder': 'Optional note for today'}),
        }

    def clean_soreness_level(self):
        soreness_level = self.cleaned_data['soreness_level']
        if soreness_level < 1 or soreness_level > 10:
            raise forms.ValidationError('Soreness level must be between 1 and 10.')
        return soreness_level


class SignUpForm(forms.Form):
    ROLE_CHOICES = [
        ('player', 'Player'),
        ('coach', 'Coach'),
        ('admin', 'Admin'),
    ]

    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = 'auth-input'
        self.fields['name'].widget.attrs.update({'class': input_class, 'placeholder': 'Name'})
        self.fields['email'].widget.attrs.update(
            {'class': input_class, 'placeholder': 'Email', 'autocomplete': 'email'}
        )
        self.fields['password'].widget.attrs.update(
            {
                'class': input_class,
                'placeholder': 'Password',
                'autocomplete': 'new-password',
                'id': 'id_signup_password',
            }
        )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(
            email__iexact=email
        ).exists():
            raise forms.ValidationError('An account with this email already exists.')
        if Player.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('This email is already assigned to a player profile.')
        return email

    def save(self):
        name = self.cleaned_data['name'].strip()
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        role = self.cleaned_data['role']

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=name,
        )

        if role == 'admin':
            user.is_staff = True
            user.save(update_fields=['is_staff'])
        else:
            player_role = Player.Role.COACH if role == 'coach' else Player.Role.PLAYER
            Player.objects.create(user=user, name=name, email=email, role=player_role)

        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label='Email')

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        input_class = 'auth-input'
        self.fields['username'].widget.attrs.update(
            {'class': input_class, 'placeholder': 'Email', 'autocomplete': 'email'}
        )
        self.fields['password'].widget.attrs.update(
            {
                'class': input_class,
                'placeholder': 'Password',
                'autocomplete': 'current-password',
                'id': 'id_login_password',
            }
        )

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError('This account has been deactivated. Please contact an admin.')
        super().confirm_login_allowed(user)
