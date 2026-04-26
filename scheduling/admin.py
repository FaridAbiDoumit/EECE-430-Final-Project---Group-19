from django.contrib import admin

from .models import (
    Notification,
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


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'user', 'role', 'gender', 'status', 'is_active')
    list_filter = ('role', 'gender', 'status', 'is_active')
    search_fields = ('name', 'email', 'user__username')


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'starts_at', 'location', 'session_type', 'cancelled')
    list_filter = ('session_type', 'cancelled')
    search_fields = ('title', 'location')


@admin.register(SessionRSVP)
class SessionRSVPAdmin(admin.ModelAdmin):
    list_display = ('session', 'player', 'status', 'updated_at')
    list_filter = ('status',)
    search_fields = ('session__title', 'player__name')


@admin.register(PlayerAvailability)
class PlayerAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('player', 'weekday', 'start_time', 'end_time')
    list_filter = ('weekday',)
    search_fields = ('player__name', 'notes')


@admin.register(SessionVotePoll)
class SessionVotePollAdmin(admin.ModelAdmin):
    list_display = ('title', 'closes_at', 'created_at')
    search_fields = ('title',)


@admin.register(SessionVoteOption)
class SessionVoteOptionAdmin(admin.ModelAdmin):
    list_display = ('poll', 'starts_at', 'location')
    search_fields = ('poll__title', 'location')


@admin.register(SessionVote)
class SessionVoteAdmin(admin.ModelAdmin):
    list_display = ('poll', 'option', 'player', 'created_at')
    search_fields = ('poll__title', 'player__name')


@admin.register(SessionPlan)
class SessionPlanAdmin(admin.ModelAdmin):
    list_display = ('session', 'title', 'updated_at')
    search_fields = ('session__title', 'title')


@admin.register(PersonalSessionNote)
class PersonalSessionNoteAdmin(admin.ModelAdmin):
    list_display = ('session', 'player', 'updated_at')
    search_fields = ('session__title', 'player__name')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'notification_type', 'created_at', 'read_at')
    list_filter = ('notification_type',)
    search_fields = ('recipient__name', 'title', 'message')


@admin.register(TryoutSession)
class TryoutSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'starts_at', 'location', 'registration_open')
    list_filter = ('registration_open',)
    search_fields = ('title', 'location')


@admin.register(TryoutCandidate)
class TryoutCandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'tryout_session', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'email', 'tryout_session__title')
