from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from .models import (
    Player,
    Team,
    StaffTeamAssignment,
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
    ChatGroup,
    Announcement,
    SupportTicket,
    Match,
    PlayerMatchStat,
    TeamGoal,
    UpcomingGame,
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


class ChatGroupCreateForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={'placeholder': 'Group name', 'class': 'form-input'}),
    )
    members = forms.ModelMultipleChoiceField(
        queryset=Player.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, member_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if member_queryset is None:
            member_queryset = Player.objects.filter(is_active=True)
        self.fields['members'].queryset = member_queryset.order_by('name')

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if ChatGroup.objects.filter(name__iexact=name, is_active=True).exists():
            raise forms.ValidationError('A group with this name already exists.')
        return name

    def clean(self):
        cleaned_data = super().clean()
        members = cleaned_data.get('members')
        if not members:
            raise forms.ValidationError('Select at least one member for the group.')
        return cleaned_data


class AnnouncementCreateForm(forms.ModelForm):
    notify_league_handler = forms.BooleanField(
        required=False,
        label='Also notify league system handler(s)',
    )

    class Meta:
        model = Announcement
        fields = ['title', 'content', 'notify_league_handler']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Announcement title', 'class': 'form-input'}),
            'content': forms.Textarea(
                attrs={
                    'placeholder': 'Write your announcement...',
                    'class': 'form-textarea',
                    'rows': 3,
                }
            ),
        }

    def clean_title(self):
        return self.cleaned_data['title'].strip()


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name']
        widgets = {
            'name': forms.TextInput(
                attrs={
                    'placeholder': 'Team name',
                    'class': 'form-input',
                }
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Team.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError('A team with this name already exists.')
        return name


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
    """Legacy form kept for non-league-handler use. League handler should use LeagueMatchForm."""
    class Meta:
        model = Match
        fields = ['team', 'opponent', 'date', 'goals_for', 'goals_against', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['team'].queryset = Team.objects.filter(is_active=True).order_by('name')
        self.fields['team'].required = True


class LeagueMatchForm(forms.Form):
    """Used by the league system handler to record a match between two known league teams."""
    team_1 = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True).order_by('name'),
        label='Team 1',
        empty_label='Select team 1',
    )
    team_2 = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True).order_by('name'),
        label='Team 2',
        empty_label='Select team 2',
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    team_1_score = forms.IntegerField(min_value=0, label='Team 1 score')
    team_2_score = forms.IntegerField(min_value=0, label='Team 2 score')
    gender_category = forms.ChoiceField(
        choices=Team.GenderCategory.choices,
        label='Game category',
        initial=Team.GenderCategory.MIXED,
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}), label='Notes (optional)')

    def clean(self):
        cleaned = super().clean()
        t1 = cleaned.get('team_1')
        t2 = cleaned.get('team_2')
        if t1 and t2 and t1 == t2:
            raise forms.ValidationError('Team 1 and Team 2 must be different teams.')
        gc = cleaned.get('gender_category')
        if t1 and t2 and gc:
            for team in (t1, t2):
                tgc = team.gender_category
                if gc == Team.GenderCategory.MENS and tgc == Team.GenderCategory.WOMENS:
                    raise forms.ValidationError(
                        f'{team.name} is a women\'s team and cannot play in a men\'s game.'
                    )
                if gc == Team.GenderCategory.WOMENS and tgc == Team.GenderCategory.MENS:
                    raise forms.ValidationError(
                        f'{team.name} is a men\'s team and cannot play in a women\'s game.'
                    )
        return cleaned


class PlayerMatchStatForm(forms.ModelForm):
    class Meta:
        model = PlayerMatchStat
        fields = ['player', 'goals', 'interceptions', 'points', 'blocks', 'assists', 'aces', 'returns', 'most_recent_injury']

    def __init__(self, *args, team=None, gender_category=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Player.objects.filter(role=Player.Role.PLAYER, is_active=True)
        if team is not None:
            queryset = queryset.filter(team=team)
        if gender_category == Team.GenderCategory.MENS:
            queryset = queryset.filter(gender=Player.Gender.MALE)
        elif gender_category == Team.GenderCategory.WOMENS:
            queryset = queryset.filter(gender=Player.Gender.FEMALE)
        self.fields['player'].queryset = queryset


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
        ('club_admin', 'Team Admin'),
    ]

    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)
    gender = forms.ChoiceField(choices=Player.Gender.choices, widget=forms.RadioSelect, initial=Player.Gender.MALE)
    team = forms.ModelChoiceField(queryset=Team.objects.none(), empty_label='Select a team', required=False)

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
        self.fields['team'].queryset = Team.objects.filter(is_active=True).order_by('name')
        self.fields['team'].widget.attrs.update({'class': input_class})

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(
            email__iexact=email
        ).exists():
            raise forms.ValidationError('An account with this email already exists.')
        if Player.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('This email is already assigned to a player profile.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        team = cleaned_data.get('team')

        if role == 'league_system_handler':
            cleaned_data['team'] = None
            return cleaned_data

        if role in {'player', 'coach', 'club_admin'} and team is None:
            self.add_error('team', 'Please select the team you are registering to.')

        if role in {'player', 'coach', 'club_admin'} and not Team.objects.filter(is_active=True).exists():
            self.add_error('team', 'No teams are available yet. Please ask the league system handler to add teams first.')

        gender = cleaned_data.get('gender')
        team = cleaned_data.get('team')
        if team is not None and gender:
            if team.gender_category == Team.GenderCategory.MENS and gender == Player.Gender.FEMALE:
                self.add_error('gender', "This is a Men's team. Female players are not eligible to register for it.")
            if team.gender_category == Team.GenderCategory.WOMENS and gender == Player.Gender.MALE:
                self.add_error('gender', "This is a Women's team. Male players are not eligible to register for it.")

        return cleaned_data

    def save(self):
        name = self.cleaned_data['name'].strip()
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        role = self.cleaned_data['role']
        team = self.cleaned_data.get('team')

        if role == 'club_admin':
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name,
                is_staff=True,
            )
            StaffTeamAssignment.objects.create(user=user, team=team, is_approved=False)
            return user

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=name,
        )

        if role == 'coach':
            player_role = Player.Role.COACH
        elif role == 'league_system_handler':
            player_role = Player.Role.LEAGUE_SYSTEM_HANDLER
        else:
            player_role = Player.Role.PLAYER
        assigned_team = team if role in {'player', 'coach'} else None
        # League system handlers are auto-approved — they are the top of the hierarchy with no one to approve them.
        auto_approved = role == 'league_system_handler'
        gender = self.cleaned_data.get('gender', Player.Gender.MALE)
        Player.objects.create(user=user, name=name, email=email, role=player_role, team=assigned_team, is_approved=auto_approved, gender=gender)

        return user


class ClubAdminCreateForm(forms.Form):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput(render_value=False))
    team = forms.ModelChoiceField(queryset=Team.objects.none(), empty_label='Select a team')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = 'auth-input'
        self.fields['name'].widget.attrs.update({'class': input_class, 'placeholder': 'Full name'})
        self.fields['email'].widget.attrs.update({'class': input_class, 'placeholder': 'Email'})
        self.fields['password'].widget.attrs.update({'class': input_class, 'placeholder': 'Password'})
        self.fields['team'].queryset = Team.objects.filter(is_active=True).order_by('name')
        self.fields['team'].widget.attrs.update({'class': input_class})

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def save(self):
        name = self.cleaned_data['name'].strip()
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        team = self.cleaned_data['team']

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=name,
            is_staff=True,
        )
        StaffTeamAssignment.objects.create(user=user, team=team)
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


class UpcomingGameForm(forms.ModelForm):
    class Meta:
        model = UpcomingGame
        fields = ['home_team', 'away_team', 'gender_category', 'scheduled_at', 'venue', 'notes']
        widgets = {
            'scheduled_at': forms.DateTimeInput(
                attrs={'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'venue': forms.TextInput(
                attrs={'placeholder': 'Stadium / venue name (optional)'}
            ),
            'notes': forms.Textarea(
                attrs={'rows': 3, 'placeholder': 'Additional notes (optional)'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_teams = Team.objects.filter(is_active=True).order_by('name')
        self.fields['home_team'].queryset = active_teams
        self.fields['away_team'].queryset = active_teams

    def clean(self):
        cleaned_data = super().clean()
        home = cleaned_data.get('home_team')
        away = cleaned_data.get('away_team')
        if home and away and home == away:
            raise forms.ValidationError('Home team and away team must be different.')
        gc = cleaned_data.get('gender_category')
        if home and away and gc:
            for team in (home, away):
                tgc = team.gender_category
                if gc == Team.GenderCategory.MENS and tgc == Team.GenderCategory.WOMENS:
                    raise forms.ValidationError(
                        f'{team.name} is a women\'s team and cannot play in a men\'s game.'
                    )
                if gc == Team.GenderCategory.WOMENS and tgc == Team.GenderCategory.MENS:
                    raise forms.ValidationError(
                        f'{team.name} is a men\'s team and cannot play in a women\'s game.'
                    )
        return cleaned_data
