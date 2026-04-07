from django.contrib import admin

from .models import (
    Player,
    PlayerAvailability,
    SessionRSVP,
    SessionVote,
    SessionVoteOption,
    SessionVotePoll,
    TrainingSession,
)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'role')
    list_filter = ('role',)
    search_fields = ('name', 'email')


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
