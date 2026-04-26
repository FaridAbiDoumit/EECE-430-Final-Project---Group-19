from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class Player(models.Model):
    class Role(models.TextChoices):
        COACH = 'coach', 'Coach'
        LEAGUE_SYSTEM_HANDLER = 'league_system_handler', 'League System Handler'
        PLAYER = 'player', 'Player'

    class Status(models.TextChoices):
        ELIGIBLE = 'eligible', 'Eligible'
        INJURED = 'injured', 'Injured'
        RECOVERING = 'recovering', 'Recovering'

    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='player_profile',
        null=True,
        blank=True,
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name='members',
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.PLAYER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ELIGIBLE)
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)
    medical_certification_expiry = models.DateField(null=True, blank=True)
    contract_expiry = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffTeamAssignment(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_team_assignment',
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name='staff_assignments',
        null=True,
        blank=True,
    )
    # True for admins created directly by the league handler; False for self-registered admins awaiting approval.
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        team_name = self.team.name if self.team is not None else 'No Team'
        return f'{self.user.username} - {team_name}'


class TrainingSession(models.Model):
    class SessionType(models.TextChoices):
        PRACTICE = 'practice', 'Practice'
        FRIENDLY = 'friendly', 'Friendly'
        MATCH = 'match', 'Match'

    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=120)
    session_type = models.CharField(max_length=20, choices=SessionType.choices, default=SessionType.PRACTICE)
    notes = models.TextField(blank=True)
    cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'id']

    def __str__(self):
        return f'{self.title} @ {self.location}'

    def clean(self):
        super().clean()
        if self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'End time must be after start time.'})

    @property
    def is_upcoming(self):
        return self.starts_at >= timezone.now() and not self.cancelled


class SessionRSVP(models.Model):
    class Status(models.TextChoices):
        GOING = 'going', 'Going'
        NOT_GOING = 'not_going', 'Not Going'

    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='rsvps')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='session_rsvps')
    status = models.CharField(max_length=20, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'player'], name='unique_session_player_rsvp')
        ]
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player} - {self.get_status_display()}'


class PlayerAvailability(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='availability_slots')
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['weekday', 'start_time', 'player__name']
        constraints = [
            models.UniqueConstraint(
                fields=['player', 'weekday', 'start_time', 'end_time'],
                name='unique_player_availability_slot',
            )
        ]

    def __str__(self):
        return f'{self.player} - {self.get_weekday_display()}'


class PersonalCalendarEvent(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='personal_calendar_events')
    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'id']

    def __str__(self):
        return f'{self.player} - {self.title}'

    def clean(self):
        super().clean()
        if self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'End time must be after start time.'})


class SessionVotePoll(models.Model):
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    closes_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', 'id']

    def __str__(self):
        return self.title


class SessionVoteOption(models.Model):
    poll = models.ForeignKey(SessionVotePoll, on_delete=models.CASCADE, related_name='options')
    starts_at = models.DateTimeField()
    location = models.CharField(max_length=120)

    class Meta:
        ordering = ['starts_at', 'id']

    def __str__(self):
        return f'{self.poll.title} - {self.starts_at}'


class SessionVote(models.Model):
    poll = models.ForeignKey(SessionVotePoll, on_delete=models.CASCADE, related_name='votes')
    option = models.ForeignKey(SessionVoteOption, on_delete=models.CASCADE, related_name='votes')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='session_votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['poll', 'player'], name='unique_poll_player_vote')
        ]
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player} - {self.option}'


class SessionPlan(models.Model):
    session = models.OneToOneField(TrainingSession, on_delete=models.CASCADE, related_name='plan')
    title = models.CharField(max_length=120)
    drills = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['session__starts_at']

    def __str__(self):
        return self.title


class PersonalSessionNote(models.Model):
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='personal_notes')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='personal_notes')
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'player'], name='unique_session_player_note')
        ]
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player} - {self.session}'


class Notification(models.Model):
    class Type(models.TextChoices):
        SESSION_UPDATED = 'session_updated', 'Session Updated'
        TRAINING_CREATED = 'training_created', 'Training Session Created'
        TRYOUT_CREATED = 'tryout_created', 'Tryout Created'
        STATS_ADDED = 'stats_added', 'Stats Added'
        GENERAL = 'general', 'General'

    recipient = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=120)
    message = models.TextField()
    notification_type = models.CharField(max_length=40, choices=Type.choices, default=Type.GENERAL)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.recipient} - {self.title}'


class TryoutSession(models.Model):
    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    location = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    registration_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'id']

    def __str__(self):
        return self.title


class TryoutCandidate(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        CONVERTED = 'converted', 'Converted'

    tryout_session = models.ForeignKey(TryoutSession, on_delete=models.CASCADE, related_name='candidates')
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    notes = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.name


class Message(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name='sent_messages',
        null=True,
        blank=True,
    )
    subject = models.CharField(max_length=200)
    content = models.TextField()
    sender_is_admin = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.player} - {self.subject}'


class ChatGroup(models.Model):
    name = models.CharField(max_length=120)
    members = models.ManyToManyField(Player, related_name='chat_groups', blank=True)
    created_by_player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name='created_chat_groups',
        null=True,
        blank=True,
    )
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_chat_groups',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class GroupMessage(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name='messages')
    sender_player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name='group_messages_sent',
        null=True,
        blank=True,
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='group_messages_sent',
        null=True,
        blank=True,
    )
    sender_name = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.group} - {self.sender_name}'


class Announcement(models.Model):
    title = models.CharField(max_length=120)
    content = models.TextField()
    created_by_player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name='announcements_created',
        null=True,
        blank=True,
    )
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='announcements_created',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notify_league_handler = models.BooleanField(
        default=False,
        help_text='Also send this announcement to league system handler(s).',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title


class AnnouncementReply(models.Model):
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    sender = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='announcement_replies',
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'Reply to "{self.announcement}" by {self.sender}'


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_PROGRESS = 'in_progress', 'In Progress'
        RESOLVED = 'resolved', 'Resolved'
        CLOSED = 'closed', 'Closed'

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='support_tickets')
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(
        max_length=20,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        default='medium'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.player} - {self.subject}'


class UpcomingGame(models.Model):
    home_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='home_games',
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='away_games',
    )
    scheduled_at = models.DateTimeField()
    venue = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_at', 'id']

    def __str__(self):
        return f'{self.home_team} vs {self.away_team} ({self.scheduled_at:%Y-%m-%d %H:%M})'

    def clean(self):
        if (
            self.home_team_id
            and self.away_team_id
            and self.home_team_id == self.away_team_id
        ):
            raise ValidationError('Home team and away team must be different.')


class GameAttendance(models.Model):
    class Status(models.TextChoices):
        GOING = 'going', 'Going'
        NOT_GOING = 'not_going', 'Not Going'
        INJURED = 'injured', 'Injured'
        MAYBE = 'maybe', 'Maybe'

    game = models.ForeignKey(
        UpcomingGame,
        on_delete=models.CASCADE,
        related_name='attendances',
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='game_attendances',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.MAYBE,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['game', 'player'],
                name='unique_game_player_attendance',
            )
        ]
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player} – {self.game} – {self.get_status_display()}'


class Match(models.Model):
    class Result(models.TextChoices):
        WIN = 'win', 'Win'
        LOSS = 'loss', 'Loss'
        DRAW = 'draw', 'Draw'

    opponent = models.CharField(max_length=120)
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name='matches',
        null=True,
        blank=True,
    )
    # When the match is recorded via the league handler between two known teams,
    # opponent_team links to the actual Team object of the opposing side.
    opponent_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name='opponent_matches',
        null=True,
        blank=True,
    )
    date = models.DateField()
    goals_for = models.PositiveIntegerField(default=0)
    goals_against = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        if self.team is not None:
            return f'{self.team.name} vs {self.opponent} ({self.date})'
        return f'{self.opponent} ({self.date})'

    @property
    def result(self):
        if self.goals_for > self.goals_against:
            return self.Result.WIN
        elif self.goals_for < self.goals_against:
            return self.Result.LOSS
        return self.Result.DRAW


class PlayerMatchStat(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='player_stats')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='match_stats')
    goals = models.PositiveIntegerField(default=0)
    interceptions = models.PositiveIntegerField(default=0)
    points = models.PositiveIntegerField(default=0)
    blocks = models.PositiveIntegerField(default=0)
    assists = models.PositiveIntegerField(default=0)
    aces = models.PositiveIntegerField(default=0)
    returns = models.PositiveIntegerField(default=0)
    most_recent_injury = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['match', 'player'], name='unique_match_player_stat')
        ]
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player} – {self.match}'


class TeamGoal(models.Model):
    class Metric(models.TextChoices):
        GOALS = 'goals', 'Goals'
        POINTS = 'points', 'Points'
        ASSISTS = 'assists', 'Assists'
        BLOCKS = 'blocks', 'Blocks'
        ACES = 'aces', 'Aces'
        INTERCEPTIONS = 'interceptions', 'Interceptions'
        RETURNS = 'returns', 'Returns'

    description = models.CharField(max_length=200)
    metric = models.CharField(max_length=20, choices=Metric.choices, default=Metric.POINTS)
    target_value = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.description


class PlayerSorenessReport(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='soreness_reports')
    soreness_level = models.PositiveSmallIntegerField()
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.player} soreness {self.soreness_level}'

    def clean(self):
        super().clean()
        if self.soreness_level < 1 or self.soreness_level > 10:
            raise ValidationError({'soreness_level': 'Soreness level must be between 1 and 10.'})


class TeamSubscriptionFee(models.Model):
    """Monthly subscription fee configured by a club admin for their team."""
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name='subscription_fee')
    monthly_amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.team.name} – {self.currency} {self.monthly_amount}/month'


class MembershipPayment(models.Model):
    """One payment record per player per calendar month."""

    class Method(models.TextChoices):
        CARD = 'card', 'Card'
        CASH = 'cash', 'Cash'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='membership_payments')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    period_month = models.PositiveSmallIntegerField()  # 1–12
    period_year = models.PositiveSmallIntegerField()
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    card_last4 = models.CharField(max_length=4, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_year', '-period_month', 'player']
        unique_together = [('player', 'period_month', 'period_year')]

    def __str__(self):
        return f'{self.player.name} {self.period_month}/{self.period_year} – {self.status}'
