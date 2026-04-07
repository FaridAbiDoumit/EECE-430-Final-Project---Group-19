from django.contrib import admin

from .models import Player, SessionRSVP, TrainingSession


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
