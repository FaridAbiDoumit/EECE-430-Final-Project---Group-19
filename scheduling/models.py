from django.conf import settings
from django.db import models
from django.utils import timezone


class Player(models.Model):
    class Role(models.TextChoices):
        COACH = 'coach', 'Coach'
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
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PLAYER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ELIGIBLE)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TrainingSession(models.Model):
    class SessionType(models.TextChoices):
        PRACTICE = 'practice', 'Practice'
        FRIENDLY = 'friendly', 'Friendly'
        MATCH = 'match', 'Match'

    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    location = models.CharField(max_length=120)
    session_type = models.CharField(max_length=20, choices=SessionType.choices, default=SessionType.PRACTICE)
    notes = models.TextField(blank=True)
    cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'id']

    def __str__(self):
        return f'{self.title} @ {self.location}'

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
