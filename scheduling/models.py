from django.db import models
from django.utils import timezone


class Player(models.Model):
    class Role(models.TextChoices):
        COACH = 'coach', 'Coach'
        PLAYER = 'player', 'Player'

    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PLAYER)

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
