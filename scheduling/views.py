import calendar
from datetime import date, datetime, time, timedelta

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.sessions.models import Session
from django.db.models import Avg, Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from urllib.parse import urlencode

from .forms import (
    EmailAuthenticationForm,
    PlayerAvailabilityForm,
    PlayerSorenessReportForm,
    PersonalSessionNoteForm,
    PlayerUpdateForm,
    SessionRSVPForm,
    SessionPlanForm,
    SignUpForm,
    SessionVoteForm,
    SessionVotePollForm,
    TrainingSessionForm,
    TryoutCandidateForm,
    TryoutSessionForm,
    MessageForm,
    ChatMessageForm,
    ChatGroupCreateForm,
    AnnouncementCreateForm,
    SupportTicketForm,
    MatchForm,
    LeagueMatchForm,
    PlayerMatchStatForm,
    TeamGoalForm,
    TeamCreateForm,
    UpcomingGameForm,
)
from .ai_analytics import build_ai_analytics_context, generate_scouting_narrative, generate_opponent_analysis
from .models import (
    Notification,
    Player,
    Team,
    ChatGroup,
    Announcement,
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
    Message,
    GroupMessage,
    SupportTicket,
    Match,
    PlayerMatchStat,
    PlayerSorenessReport,
    TeamGoal,
    PersonalCalendarEvent,
    AnnouncementReply,
    UpcomingGame,
    GameAttendance,
    StaffTeamAssignment,
)


TEAM_STAT_METRICS = {
    'goals': 'Goals',
    'points': 'Points',
    'assists': 'Assists',
    'blocks': 'Blocks',
    'aces': 'Aces',
    'interceptions': 'Interceptions',
    'returns': 'Returns',
}


def _post_login_route_for(user):
    player = getattr(user, 'player_profile', None)
    if player is not None:
        if player.role == Player.Role.PLAYER:
            return 'scheduling:player_home'
        if player.role == Player.Role.COACH:
            return 'scheduling:coach_home'
        if player.role == Player.Role.LEAGUE_SYSTEM_HANDLER:
            return 'scheduling:league_system_handler_home'
    if user.is_staff:
        return 'scheduling:admin_home'
    return 'scheduling:dashboard'


def _can_manage_training_sessions(user):
    profile = getattr(user, 'player_profile', None)
    return user.is_authenticated and (
        user.is_staff or (profile is not None and profile.role == Player.Role.COACH)
    )


def _can_manage_stats_entries(profile):
    return profile is not None and profile.role == Player.Role.LEAGUE_SYSTEM_HANDLER


def _logout_user_sessions(user):
    if user is None:
        return

    user_id = str(user.pk)
    for session in Session.objects.all():
        try:
            session_data = session.get_decoded()
        except Exception:
            continue
        if session_data.get('_auth_user_id') == user_id:
            session.delete()


def _sync_linked_user_access(player):
    linked_user = getattr(player, 'user', None)
    if linked_user is None:
        return

    if linked_user.is_active != player.is_active:
        linked_user.is_active = player.is_active
        linked_user.save(update_fields=['is_active'])

    if not player.is_active:
        _logout_user_sessions(linked_user)


def _new_session_notification_payload(session):
    if session.session_type == TrainingSession.SessionType.MATCH:
        title = 'New Match'
        kind = 'match'
    elif session.session_type == TrainingSession.SessionType.FRIENDLY:
        title = 'New Friendly'
        kind = 'friendly'
    else:
        title = 'New Practice Session'
        kind = 'practice session'

    message = (
        f'A new {kind} "{session.title}" has been scheduled'
        f' for {session.starts_at.strftime("%b %d, %Y at %H:%M")}'
        f' at {session.location}.'
    )
    return title, message


def _notify_coaches_of_player_rsvp(player, session, rsvp_status):
    status_label = 'accepted' if rsvp_status == SessionRSVP.Status.GOING else 'declined'
    local_starts = timezone.localtime(session.starts_at)
    starts_label = local_starts.strftime('%b %d, %Y at %H:%M')
    recipients = list(Player.objects.filter(role=Player.Role.COACH, is_active=True).exclude(pk=player.pk))
    if not recipients:
        return

    Notification.objects.bulk_create(
        [
            Notification(
                recipient=coach,
                title=f'RSVP update: {player.name}',
                message=(
                    f'{player.name} {status_label} "{session.title}" '
                    f'({starts_label} at {session.location}).'
                ),
                notification_type=Notification.Type.GENERAL,
            )
            for coach in recipients
        ]
    )


def _player_metric_rankings(metric_key, descending=True, limit=5, team=None):
    metric_key = metric_key if metric_key in TEAM_STAT_METRICS else 'points'
    order_prefix = '-' if descending else ''
    queryset = Player.objects.filter(role=Player.Role.PLAYER, is_active=True)
    metric_sum = Sum(f'match_stats__{metric_key}')
    if team is not None:
        queryset = queryset.filter(team=team)
        metric_sum = Sum(f'match_stats__{metric_key}', filter=Q(match_stats__match__team=team))

    return list(
        queryset
        .annotate(metric_total=Coalesce(metric_sum, Value(0)))
        .order_by(f'{order_prefix}metric_total', 'name')[:limit]
    )


def _season_metric_totals(stats_queryset=None):
    if stats_queryset is None:
        stats_queryset = PlayerMatchStat.objects.all()

    totals = stats_queryset.aggregate(
        total_goals=Coalesce(Sum('goals'), Value(0)),
        total_points=Coalesce(Sum('points'), Value(0)),
        total_assists=Coalesce(Sum('assists'), Value(0)),
        total_blocks=Coalesce(Sum('blocks'), Value(0)),
        total_aces=Coalesce(Sum('aces'), Value(0)),
        total_interceptions=Coalesce(Sum('interceptions'), Value(0)),
        total_returns=Coalesce(Sum('returns'), Value(0)),
    )
    return {
        'goals': totals['total_goals'],
        'points': totals['total_points'],
        'assists': totals['total_assists'],
        'blocks': totals['total_blocks'],
        'aces': totals['total_aces'],
        'interceptions': totals['total_interceptions'],
        'returns': totals['total_returns'],
    }


def landing_page(request):
    if request.user.is_authenticated:
        return redirect(_post_login_route_for(request.user))
    return render(request, 'scheduling/landing.html')


def signup(request):
    if request.user.is_authenticated:
        return redirect(_post_login_route_for(request.user))

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            profile = getattr(user, 'player_profile', None)
            if profile is not None and not profile.is_approved:
                auth_login(request, user)
                messages.success(request, 'Registration submitted! Waiting for your club admin to approve your account.')
                return redirect('scheduling:pending_approval')
            auth_login(request, user)
            messages.success(request, 'Account created successfully.')
            return redirect(_post_login_route_for(user))
    else:
        form = SignUpForm(initial={'role': 'player'})

    return render(request, 'scheduling/signup.html', {'form': form})


@login_required(login_url='scheduling:login')
def pending_approval(request):
    # Staff (club admin) pending case
    if request.user.is_staff:
        assignment = getattr(request.user, 'staff_team_assignment', None)
        if assignment is None or assignment.is_approved:
            return redirect(_post_login_route_for(request.user))
        return render(request, 'scheduling/pending_approval.html', {
            'is_staff_pending': True,
            'team': assignment.team,
        })
    # Player/Coach pending case
    profile = getattr(request.user, 'player_profile', None)
    if profile is None or profile.is_approved:
        return redirect(_post_login_route_for(request.user))
    return render(request, 'scheduling/pending_approval.html', {'profile': profile})


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_route_for(request.user))

    if request.method == 'POST':
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            profile = getattr(user, 'player_profile', None)
            if profile is not None and not profile.is_active:
                form.add_error(None, 'This account has been deactivated. Please contact an admin.')
            elif profile is not None and not profile.is_approved:
                auth_login(request, user)
                return redirect('scheduling:pending_approval')
            else:
                auth_login(request, user)
                messages.success(request, 'Signed in successfully.')
                return redirect(_post_login_route_for(user))
    else:
        form = EmailAuthenticationForm(request)

    return render(request, 'scheduling/login.html', {'form': form})


def logout_view(request):
    if request.method == 'POST':
        auth_logout(request)
        messages.success(request, 'Signed out successfully.')
    return redirect('scheduling:login')


@login_required(login_url='scheduling:login')
def player_home(request):
    player = getattr(request.user, 'player_profile', None)
    if player is None or player.role != Player.Role.PLAYER:
        messages.info(request, 'This page is currently available only for player accounts.')
        return redirect('scheduling:dashboard')

    next_session = (
        TrainingSession.objects.filter(starts_at__gte=timezone.now(), cancelled=False)
        .order_by('starts_at')
        .first()
    )
    next_session_rsvp = None
    if next_session is not None:
        next_session_rsvp = (
            SessionRSVP.objects.filter(session=next_session, player=player)
            .values_list('status', flat=True)
            .first()
        )
    latest_soreness = player.soreness_reports.first()

    context = {
        'player': player,
        'welcome_name': player.name,
        'next_session': next_session,
        'next_session_rsvp': next_session_rsvp,
        'latest_soreness': latest_soreness,
        'unread_notifications': player.notifications.filter(read_at__isnull=True).count(),
        'rsvp_count': player.session_rsvps.count(),
        'availability_count': player.availability_slots.count(),
    }
    return render(request, 'scheduling/player_home.html', context)


@login_required(login_url='scheduling:login')
def player_messages(request):
    player = getattr(request.user, 'player_profile', None)
    if player is None or player.role != Player.Role.PLAYER:
        messages.info(request, 'This page is currently available only for player accounts.')
        return redirect('scheduling:dashboard')
    
    # Get all messages for this player
    player_msgs = Message.objects.filter(player=player).order_by('-created_at')
    
    # Mark as read
    unread_messages = player_msgs.filter(is_read=False)
    unread_messages.update(is_read=True)
    
    context = {
        'player': player,
        'messages': player_msgs,
    }
    return render(request, 'scheduling/player_messages.html', context)


@login_required(login_url='scheduling:login')
def log_player_soreness(request):
    player = getattr(request.user, 'player_profile', None)
    if player is None or player.role != Player.Role.PLAYER:
        messages.info(request, 'This page is currently available only for player accounts.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        form = PlayerSorenessReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.player = player
            report.save()
            messages.success(request, 'Daily soreness saved.')
            return redirect('scheduling:log_player_soreness')
    else:
        form = PlayerSorenessReportForm()

    recent_reports = player.soreness_reports.all()[:5]
    return render(
        request,
        'scheduling/log_soreness.html',
        {
            'player': player,
            'form': form,
            'recent_reports': recent_reports,
        },
    )


@login_required(login_url='scheduling:login')
def coach_home(request):
    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    next_session = (
        TrainingSession.objects.filter(starts_at__gte=timezone.now(), cancelled=False)
        .order_by('starts_at')
        .first()
    )
    context = {
        'coach': coach,
        'welcome_name': coach.name,
        'next_session': next_session,
        'unread_notifications': coach.notifications.filter(read_at__isnull=True).count(),
        'open_tryouts': TryoutSession.objects.filter(registration_open=True).count(),
        'poll_count': SessionVotePoll.objects.count(),
        'session_count': TrainingSession.objects.count(),
    }
    return render(request, 'scheduling/coach_home.html', context)


@login_required(login_url='scheduling:login')
def league_system_handler_home(request):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.info(request, 'This page is currently available only for league system handler accounts.')
        return redirect('scheduling:dashboard')

    teams = Team.objects.filter(is_active=True).order_by('name')

    context = {
        'handler': handler,
        'welcome_name': handler.name,
        'unread_notifications': handler.notifications.filter(read_at__isnull=True).count(),
        'match_count': Match.objects.count(),
        'team_goal_count': TeamGoal.objects.count(),
        'team_count': teams.count(),
        'teams': teams,
        'pending_admin_count': StaffTeamAssignment.objects.filter(is_approved=False).count(),
    }
    return render(request, 'scheduling/league_system_handler_home.html', context)


@login_required(login_url='scheduling:login')
def league_handler_manage_teams(request):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.info(request, 'This page is currently available only for league system handler accounts.')
        return redirect('scheduling:dashboard')

    teams = Team.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        team_form = TeamCreateForm(request.POST)
        if team_form.is_valid():
            team = team_form.save()
            messages.success(request, f'Team "{team.name}" added to the league.')
            # Notify all OTHER active league handlers about the new team
            other_handlers = Player.objects.filter(
                is_active=True,
                role=Player.Role.LEAGUE_SYSTEM_HANDLER,
            ).exclude(pk=handler.pk)
            Notification.objects.bulk_create([
                Notification(
                    recipient=lh,
                    title='New Team Added to League',
                    message=f'A new team "{team.name}" has been added to the league.',
                    notification_type=Notification.Type.GENERAL,
                )
                for lh in other_handlers
            ])
            return redirect('scheduling:league_handler_manage_teams')
        messages.error(request, 'Could not add team. Please fix the form errors below.')
    else:
        team_form = TeamCreateForm()

    return render(
        request,
        'scheduling/league_handler_manage_teams.html',
        {
            'handler': handler,
            'team_form': team_form,
            'teams': teams,
            'team_count': teams.count(),
            'home_url': reverse('scheduling:league_system_handler_home'),
        },
    )


@login_required(login_url='scheduling:login')
def tryout_list(request):
    if request.user.is_staff:
        messages.info(request, 'Tryouts are not available for admin accounts.')
        return redirect('scheduling:admin_home')

    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    tryouts = TryoutSession.objects.all()
    return render(
        request,
        'scheduling/tryout_list.html',
        {
            'coach': coach,
            'tryouts': tryouts,
        },
    )


@login_required(login_url='scheduling:login')
def player_tryout_list(request):
    player = getattr(request.user, 'player_profile', None)
    if player is None or player.role != Player.Role.PLAYER:
        messages.info(request, 'This page is currently available only for player accounts.')
        return redirect('scheduling:dashboard')

    tryouts = TryoutSession.objects.order_by('starts_at')
    player_candidate = TryoutCandidate.objects.filter(email__iexact=player.email).first()
    registered_tryout_id = player_candidate.tryout_session_id if player_candidate is not None else None
    registered_tryout_status = player_candidate.status if player_candidate is not None else None
    open_tryout_count = tryouts.filter(registration_open=True).count()
    return render(
        request,
        'scheduling/player_tryout_list.html',
        {
            'player': player,
            'tryouts': tryouts,
            'open_tryout_count': open_tryout_count,
            'registered_tryout_id': registered_tryout_id,
            'registered_tryout_status': registered_tryout_status,
        },
    )


@login_required(login_url='scheduling:login')
def player_tryout_registration_toggle(request, tryout_session_id):
    if request.method != 'POST':
        return redirect('scheduling:player_tryout_list')

    player = getattr(request.user, 'player_profile', None)
    if player is None or player.role != Player.Role.PLAYER:
        messages.info(request, 'This page is currently available only for player accounts.')
        return redirect('scheduling:dashboard')

    tryout = get_object_or_404(TryoutSession, pk=tryout_session_id)
    action = request.POST.get('action')
    existing_for_player = TryoutCandidate.objects.filter(email__iexact=player.email).first()

    if action == 'cancel':
        if existing_for_player is None or existing_for_player.tryout_session_id != tryout.id:
            messages.info(request, 'You are not registered for this tryout.')
            return redirect('scheduling:player_tryout_list')
        existing_for_player.delete()
        messages.success(request, 'Your tryout registration has been cancelled.')
        return redirect('scheduling:player_tryout_list')

    if action == 'register':
        if not tryout.registration_open:
            messages.error(request, 'Registration is closed for this tryout.')
            return redirect('scheduling:player_tryout_list')

        if existing_for_player is not None and existing_for_player.tryout_session_id == tryout.id:
            messages.info(request, 'You are already registered for this tryout.')
            return redirect('scheduling:player_tryout_list')

        if existing_for_player is not None and existing_for_player.tryout_session_id != tryout.id:
            messages.error(
                request,
                'You are already registered for another tryout. Cancel it first before registering again.',
            )
            return redirect('scheduling:player_tryout_list')

        TryoutCandidate.objects.create(
            tryout_session=tryout,
            name=player.name,
            email=player.email,
            notes='Registered from player tryouts page.',
        )
        messages.success(request, 'Tryout registration submitted.')
        return redirect('scheduling:player_tryout_list')

    messages.error(request, 'Invalid registration action.')
    return redirect('scheduling:player_tryout_list')


@login_required(login_url='scheduling:login')
def admin_home(request):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    admin_team = None
    assignment = getattr(request.user, 'staff_team_assignment', None)
    if assignment is not None:
        admin_team = assignment.team

    welcome_name = request.user.first_name or request.user.username
    context = {
        'welcome_name': welcome_name,
        'active_players': Player.objects.filter(role=Player.Role.PLAYER, is_active=True, team=admin_team).count(),
        'coach_count': Player.objects.filter(role=Player.Role.COACH, is_active=True, team=admin_team).count(),
        'open_tryouts': TryoutSession.objects.filter(registration_open=True).count(),
        'session_count': TrainingSession.objects.count(),
        'notification_count': Notification.objects.count(),
        'poll_count': SessionVotePoll.objects.count(),
        'pending_count': Player.objects.filter(team=admin_team, is_approved=False).count(),
    }
    return render(request, 'scheduling/admin_home.html', context)


def _get_admin_team(user):
    """Return the Team for a staff user, or None."""
    assignment = getattr(user, 'staff_team_assignment', None)
    return assignment.team if assignment is not None else None


@login_required(login_url='scheduling:login')
def pending_members(request):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    admin_team = _get_admin_team(request.user)
    pending = Player.objects.filter(team=admin_team, is_approved=False).order_by('name')
    return render(request, 'scheduling/pending_members.html', {
        'pending': pending,
        'admin_team': admin_team,
    })


@login_required(login_url='scheduling:login')
def approve_member(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    if request.method != 'POST':
        return redirect('scheduling:pending_members')

    admin_team = _get_admin_team(request.user)
    player = get_object_or_404(Player, pk=player_id, team=admin_team, is_approved=False)
    player.is_approved = True
    player.save(update_fields=['is_approved'])
    Notification.objects.create(
        recipient=player,
        title='Registration approved',
        message=f'Your registration to {admin_team.name if admin_team else "the club"} has been approved. Welcome!',
        notification_type='general',
    )
    # Notify all active league handlers about the newly approved player
    league_handlers = Player.objects.filter(
        is_active=True,
        role=Player.Role.LEAGUE_SYSTEM_HANDLER,
    )
    team_label = admin_team.name if admin_team else 'the club'
    Notification.objects.bulk_create([
        Notification(
            recipient=lh,
            title='New Player Approved',
            message=f'{player.name} has been approved and joined {team_label}.',
            notification_type=Notification.Type.GENERAL,
        )
        for lh in league_handlers
    ])
    messages.success(request, f'{player.name} has been approved.')
    next_url = request.POST.get('next', '')
    if next_url not in ('scheduling:pending_members', 'scheduling:player_status_list'):
        next_url = 'scheduling:pending_members'
    return redirect(next_url)


@login_required(login_url='scheduling:login')
def reject_member(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    if request.method != 'POST':
        return redirect('scheduling:pending_members')

    admin_team = _get_admin_team(request.user)
    player = get_object_or_404(Player, pk=player_id, team=admin_team, is_approved=False)
    player_name = player.name
    linked_user = player.user
    player.delete()
    if linked_user is not None:
        linked_user.delete()
    messages.success(request, f'Registration for {player_name} has been rejected and removed.')
    next_url = request.POST.get('next', '')
    if next_url not in ('scheduling:pending_members', 'scheduling:player_status_list'):
        next_url = 'scheduling:pending_members'
    return redirect(next_url)


@login_required(login_url='scheduling:login')
def create_club_admin(request):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.info(request, 'This page is currently available only for league system handler accounts.')
        return redirect('scheduling:dashboard')

    from .forms import ClubAdminCreateForm
    if request.method == 'POST':
        form = ClubAdminCreateForm(request.POST)
        if form.is_valid():
            admin_user = form.save()
            messages.success(request, f'Club admin account for {admin_user.first_name} created successfully.')
            return redirect('scheduling:league_handler_manage_teams')
    else:
        form = ClubAdminCreateForm()

    return render(request, 'scheduling/create_club_admin.html', {'form': form, 'handler': handler})


@login_required(login_url='scheduling:login')
def dashboard(request):
    sessions = TrainingSession.objects.all()
    upcoming_session = (
        TrainingSession.objects.filter(starts_at__gte=timezone.now(), cancelled=False)
        .order_by('starts_at')
        .first()
    )
    return render(
        request,
        'scheduling/dashboard.html',
        {
            'sessions': sessions,
            'upcoming_session': upcoming_session,
            'availability_count': PlayerAvailability.objects.count(),
            'poll_count': SessionVotePoll.objects.count(),
            'notification_count': Notification.objects.count(),
            'tryout_count': TryoutSession.objects.count(),
        },
    )


def _role_label_for(user):
    profile = getattr(user, 'player_profile', None)
    if profile is not None:
        return profile.get_role_display()
    if user.is_staff:
        return 'Admin'
    return 'Member'


def _chat_contact_status(contact):
    linked_user = getattr(contact, 'user', None)
    if linked_user is not None and linked_user.is_staff:
        return 'admin'
    if contact.role == Player.Role.LEAGUE_SYSTEM_HANDLER:
        return 'league system handler'
    if contact.role == Player.Role.COACH:
        return 'coach'
    return 'player'


def _chat_sender_name(user, profile=None):
    if profile is not None:
        return profile.name
    return user.get_full_name().strip() or user.username or 'Admin'


def _create_chat_notification(recipient, sender_name, content):
    preview = ' '.join((content or '').split())
    if len(preview) > 120:
        preview = f'{preview[:117]}...'

    message_body = f'{sender_name} sent you a new message.'
    if preview:
        message_body = f'{message_body} "{preview}"'

    Notification.objects.create(
        recipient=recipient,
        title=f'New message from {sender_name}',
        message=message_body,
        notification_type=Notification.Type.GENERAL,
    )


def _chat_groups_for_user(user, profile):
    groups = ChatGroup.objects.filter(is_active=True)
    if profile is not None:
        return groups.filter(members=profile).distinct()
    if user.is_staff:
        return groups.filter(created_by_user=user).distinct()
    return groups.none()


def _build_direct_conversation_messages(user_profile, selected_user, is_admin, request_user):
    """Fetch Message + AnnouncementReply records for a 1:1 chat and return a merged, sorted, serialized list."""
    if user_profile is not None:
        raw_messages = list(
            Message.objects.filter(
                Q(player=selected_user, sender=user_profile)
                | Q(player=user_profile, sender=selected_user)
            ).order_by('created_at').select_related('sender')
        )
        ann_replies = list(
            AnnouncementReply.objects.filter(
                Q(sender=user_profile, announcement__created_by_player=selected_user)
                | Q(sender=selected_user, announcement__created_by_player=user_profile)
            ).select_related('announcement', 'sender').order_by('created_at')
        )
    elif is_admin:
        raw_messages = list(
            Message.objects.filter(
                player=selected_user,
                sender_is_admin=True,
            ).order_by('created_at').select_related('sender')
        )
        ann_replies = list(
            AnnouncementReply.objects.filter(
                sender=selected_user,
                announcement__created_by_player=None,
                announcement__created_by_user=request_user,
            ).select_related('announcement', 'sender').order_by('created_at')
        )
    else:
        raw_messages = list(
            Message.objects.filter(player=selected_user).order_by('created_at').select_related('sender')
        )
        ann_replies = []

    combined = []
    for msg in raw_messages:
        is_sent = (
            (user_profile is not None and msg.sender_id == user_profile.id)
            or (is_admin and msg.sender_is_admin)
        )
        combined.append({
            'id': f'msg_{msg.id}',
            'author': 'You' if is_sent else (msg.sender.name if msg.sender else selected_user.name),
            'content': msg.content,
            'created_at': msg.created_at,
            'sent_by_current_user': is_sent,
            'announcement_context': None,
        })

    for reply in ann_replies:
        is_sent = user_profile is not None and reply.sender_id == user_profile.id
        combined.append({
            'id': f'ann_{reply.id}',
            'author': 'You' if is_sent else reply.sender.name,
            'content': reply.content,
            'created_at': reply.created_at,
            'sent_by_current_user': is_sent,
            'announcement_context': reply.announcement.title,
        })

    combined.sort(key=lambda x: x['created_at'])
    for item in combined:
        item['created_at'] = item['created_at'].strftime('%b %d, %Y - %H:%M')
    return combined


def _serialize_direct_messages(conversation_messages, selected_user, user_profile, is_admin):
    messages_data = []
    for message in conversation_messages:
        is_sent = (
            (user_profile is not None and message.sender_id == user_profile.id)
            or (is_admin and message.sender_is_admin)
        )
        if is_sent:
            author = 'You'
        elif message.sender is not None:
            author = message.sender.name
        else:
            author = selected_user.name

        messages_data.append({
            'id': message.id,
            'author': author,
            'content': message.content,
            'created_at': message.created_at.strftime('%b %d, %Y - %H:%M'),
            'sent_by_current_user': is_sent,
        })
    return messages_data


def _serialize_group_messages(group_messages, user, profile):
    messages_data = []
    for message in group_messages:
        is_sent = (
            (profile is not None and message.sender_player_id == profile.id)
            or (profile is None and message.sender_user_id == user.id)
        )
        messages_data.append({
            'id': message.id,
            'author': 'You' if is_sent else message.sender_name,
            'content': message.content,
            'created_at': message.created_at.strftime('%b %d, %Y - %H:%M'),
            'sent_by_current_user': is_sent,
        })
    return messages_data


def _create_group_chat_notifications(group, sender_profile, sender_name, content):
    preview = ' '.join((content or '').split())
    if len(preview) > 120:
        preview = f'{preview[:117]}...'

    recipients = group.members.filter(is_active=True)
    if sender_profile is not None:
        recipients = recipients.exclude(pk=sender_profile.pk)

    notifications = []
    for recipient in recipients:
        body = f'New message in {group.name} from {sender_name}.'
        if preview:
            body = f'{body} "{preview}"'
        notifications.append(
            Notification(
                recipient=recipient,
                title=f'New group message: {group.name}',
                message=body,
                notification_type=Notification.Type.GENERAL,
            )
        )

    if notifications:
        Notification.objects.bulk_create(notifications)


def _can_manage_announcements(user, profile):
    return user.is_staff or (profile is not None and profile.role == Player.Role.COACH)


def _create_announcement_notifications(announcement, sender_name):
    recipients = Player.objects.filter(is_active=True)
    if announcement.created_by_player is not None:
        recipients = recipients.exclude(pk=announcement.created_by_player.pk)
    if announcement.created_by_user is not None:
        recipients = recipients.exclude(user=announcement.created_by_user)

    # League handlers only receive announcements explicitly opted-in by the sender
    if not announcement.notify_league_handler:
        recipients = recipients.exclude(role=Player.Role.LEAGUE_SYSTEM_HANDLER)

    notifications = [
        Notification(
            recipient=recipient,
            title=f'Announcement: {announcement.title}',
            message=f'{sender_name}: {announcement.content}',
            notification_type=Notification.Type.GENERAL,
        )
        for recipient in recipients
    ]
    if notifications:
        Notification.objects.bulk_create(notifications)


@login_required(login_url='scheduling:login')
def chatting_hub(request):
    user_profile = getattr(request.user, 'player_profile', None)
    is_admin = request.user.is_staff
    can_manage_announcements = _can_manage_announcements(request.user, user_profile)

    all_contacts = Player.objects.filter(is_active=True)
    if user_profile is not None:
        all_contacts = all_contacts.exclude(pk=user_profile.pk)

    search_query = request.GET.get('search', '').strip()
    contacts = all_contacts
    if search_query:
        contacts = contacts.filter(
            Q(name__icontains=search_query) | Q(email__icontains=search_query)
        )

    contacts = contacts.order_by('name')
    group_member_queryset = all_contacts.order_by('name')

    accessible_groups = _chat_groups_for_user(request.user, user_profile).prefetch_related('members').order_by('name')
    groups = accessible_groups
    if search_query:
        groups = groups.filter(name__icontains=search_query)

    unread_contact_ids = []
    if user_profile is not None:
        unread_contact_ids = list(
            Message.objects.filter(
                player=user_profile,
                sender__in=all_contacts,
                is_read=False,
            )
            .values_list('sender_id', flat=True)
            .distinct()
        )

    message_form = ChatMessageForm()
    group_form = ChatGroupCreateForm(member_queryset=group_member_queryset)
    show_group_form = False
    announcement_form = AnnouncementCreateForm()
    show_announcement_form = False
    announcements = list(
        Announcement.objects.select_related('created_by_player', 'created_by_user').prefetch_related('replies__sender').all()[:60]
    )

    # Determine reply permissions
    player_can_reply = not can_manage_announcements and user_profile is not None

    # For announcement authors: attach their incoming replies to each announcement object
    if can_manage_announcements:
        for ann in announcements:
            if user_profile is not None and ann.created_by_player == user_profile:
                ann.my_replies = list(ann.replies.select_related('sender').order_by('created_at'))
            elif request.user.is_staff and ann.created_by_user_id == request.user.pk and ann.created_by_player is None:
                ann.my_replies = list(ann.replies.select_related('sender').order_by('created_at'))
            else:
                ann.my_replies = []
        # Mark unread replies as read
        if user_profile is not None:
            AnnouncementReply.objects.filter(
                announcement__created_by_player=user_profile, is_read=False
            ).update(is_read=True)
        elif request.user.is_staff:
            AnnouncementReply.objects.filter(
                announcement__created_by_user=request.user,
                announcement__created_by_player=None,
                is_read=False,
            ).update(is_read=True)
    else:
        for ann in announcements:
            ann.my_replies = []

    selected_group_id = request.GET.get('group')
    selected_group = None
    if selected_group_id:
        selected_group = accessible_groups.filter(pk=selected_group_id).first()
        if selected_group is not None:
            selected_group.member_count = selected_group.members.count()

    selected_id = request.GET.get('selected')
    selected_user = None
    if selected_group is None and selected_id:
        selected_user = contacts.filter(pk=selected_id).first()

    if selected_group is None and selected_user is None and contacts.exists():
        selected_user = contacts.first()

    if request.method == 'POST':
        action = request.POST.get('chat_action', 'send_individual')
        if action == 'reply_announcement':
            if user_profile is None:
                messages.error(request, 'Only players can reply to announcements.')
            else:
                ann_id = request.POST.get('announcement_id')
                announcement_obj = Announcement.objects.filter(pk=ann_id).first()
                if announcement_obj is None:
                    messages.error(request, 'Announcement not found.')
                else:
                    reply_content = request.POST.get('reply_content', '').strip()
                    if not reply_content:
                        messages.error(request, 'Reply cannot be empty.')
                    else:
                        AnnouncementReply.objects.create(
                            announcement=announcement_obj,
                            sender=user_profile,
                            content=reply_content,
                        )
                        author = announcement_obj.created_by_player
                        if author is not None and author != user_profile:
                            Notification.objects.create(
                                recipient=author,
                                title='Private reply to your announcement',
                                message=f'{user_profile.name} replied to "{announcement_obj.title}": {reply_content[:100]}',
                                notification_type=Notification.Type.GENERAL,
                            )
                        messages.success(request, 'Your private reply was sent.')

                params = {}
                author_player = announcement_obj.created_by_player
                if author_player is not None and author_player != user_profile:
                    params['selected'] = author_player.id
                elif selected_group is not None:
                    params['group'] = selected_group.id
                elif selected_user is not None:
                    params['selected'] = selected_user.id
                if search_query:
                    params['search'] = search_query
                target = reverse('scheduling:chatting_hub')
                if params:
                    target = f"{target}?{urlencode(params)}"
                return redirect(target)

        elif action == 'create_announcement':
            if not can_manage_announcements:
                messages.error(request, 'Only coaches and admins can post announcements.')
            else:
                show_announcement_form = True
                announcement_form = AnnouncementCreateForm(request.POST)
                if announcement_form.is_valid():
                    announcement = announcement_form.save(commit=False)
                    announcement.created_by_player = user_profile
                    announcement.created_by_user = request.user
                    announcement.save()
                    sender_name = _chat_sender_name(request.user, user_profile)
                    _create_announcement_notifications(announcement, sender_name)
                    messages.success(request, 'Announcement sent and notifications delivered.')

                    params = {}
                    if selected_group is not None:
                        params['group'] = selected_group.id
                    elif selected_user is not None:
                        params['selected'] = selected_user.id
                    if search_query:
                        params['search'] = search_query

                    target = reverse('scheduling:chatting_hub')
                    if params:
                        target = f"{target}?{urlencode(params)}"
                    return redirect(target)

        elif action == 'create_group':
            show_group_form = True
            group_form = ChatGroupCreateForm(request.POST, member_queryset=group_member_queryset)
            if group_form.is_valid():
                new_group = ChatGroup.objects.create(
                    name=group_form.cleaned_data['name'],
                    created_by_player=user_profile,
                    created_by_user=request.user,
                )
                members = list(group_form.cleaned_data['members'])
                if user_profile is not None and user_profile not in members:
                    members.append(user_profile)

                if not members:
                    new_group.delete()
                    group_form.add_error('members', 'Select at least one member for the group.')
                else:
                    new_group.members.add(*members)
                    messages.success(request, f'Group "{new_group.name}" created.')
                    params = {'group': new_group.id}
                    if search_query:
                        params['search'] = search_query
                    return redirect(f"{reverse('scheduling:chatting_hub')}?{urlencode(params)}")

        elif action == 'send_group':
            selected_group_id = request.POST.get('group_id')
            selected_group = accessible_groups.filter(pk=selected_group_id).first()
            message_form = ChatMessageForm(request.POST)
            if selected_group is None:
                messages.error(request, 'Please select a group to send your message.')
            elif message_form.is_valid():
                sender_name = _chat_sender_name(request.user, user_profile)
                group_message = GroupMessage.objects.create(
                    group=selected_group,
                    sender_player=user_profile,
                    sender_user=request.user if user_profile is None else None,
                    sender_name=sender_name,
                    content=message_form.cleaned_data['content'],
                )
                _create_group_chat_notifications(
                    group=selected_group,
                    sender_profile=user_profile,
                    sender_name=sender_name,
                    content=group_message.content,
                )
                params = {'group': selected_group.id}
                if search_query:
                    params['search'] = search_query
                return redirect(f"{reverse('scheduling:chatting_hub')}?{urlencode(params)}")

        else:
            selected_id = request.POST.get('selected_id')
            selected_user = all_contacts.filter(pk=selected_id).first()
            message_form = ChatMessageForm(request.POST)
            if selected_user is None:
                messages.error(request, 'Please select a contact to send your message.')
            elif message_form.is_valid():
                message = message_form.save(commit=False)
                message.player = selected_user
                message.subject = f'Chat with {selected_user.name}'
                message.sender_is_admin = is_admin
                message.sender = user_profile if user_profile is not None else None
                message.save()

                if user_profile is None or selected_user.pk != user_profile.pk:
                    _create_chat_notification(
                        recipient=selected_user,
                        sender_name=_chat_sender_name(request.user, user_profile),
                        content=message.content,
                    )

                params = {'selected': selected_user.id}
                if search_query:
                    params['search'] = search_query
                return redirect(f"{reverse('scheduling:chatting_hub')}?{urlencode(params)}")

    if selected_group is None and selected_user is not None and user_profile is not None:
        Message.objects.filter(
            player=user_profile,
            sender=selected_user,
            is_read=False,
        ).update(is_read=True)

    conversation_messages = []
    if selected_group is not None:
        group_messages = GroupMessage.objects.filter(group=selected_group).order_by('created_at')
        conversation_messages = _serialize_group_messages(group_messages, request.user, user_profile)
    elif selected_user is not None:
        conversation_messages = _build_direct_conversation_messages(
            user_profile=user_profile,
            selected_user=selected_user,
            is_admin=is_admin,
            request_user=request.user,
        )

    contact_list = list(contacts)
    for contact in contact_list:
        contact.chat_status = _chat_contact_status(contact)

    group_list = list(groups)
    for group in group_list:
        group.member_count = group.members.count()

    if selected_group is not None and not hasattr(selected_group, 'member_count'):
        selected_group.member_count = selected_group.members.count()

    context = {
        'home_url': reverse(_post_login_route_for(request.user)),
        'role_label': _role_label_for(request.user),
        'contacts': contact_list,
        'groups': group_list,
        'selected_user': selected_user,
        'selected_group': selected_group,
        'selected_user_status': _chat_contact_status(selected_user) if selected_user is not None else None,
        'conversation_messages': conversation_messages,
        'search_query': search_query,
        'form': message_form,
        'group_form': group_form,
        'show_group_form': show_group_form,
        'announcements': announcements,
        'announcement_form': announcement_form,
        'show_announcement_form': show_announcement_form,
        'can_manage_announcements': can_manage_announcements,
        'player_can_reply': player_can_reply,
        'is_admin': is_admin,
        'unread_contact_ids': unread_contact_ids,
    }
    return render(request, 'scheduling/chatting_hub.html', context)


@login_required(login_url='scheduling:login')
def chatting_messages(request):
    user_profile = getattr(request.user, 'player_profile', None)
    is_admin = request.user.is_staff

    group_id = request.GET.get('group')
    if group_id:
        selected_group = _chat_groups_for_user(request.user, user_profile).filter(pk=group_id).first()
        if selected_group is None:
            return JsonResponse({'messages': []})

        group_messages = GroupMessage.objects.filter(group=selected_group).order_by('created_at')
        messages_data = _serialize_group_messages(group_messages, request.user, user_profile)
        return JsonResponse({'messages': messages_data})

    selected_id = request.GET.get('selected')
    selected_user = None
    if selected_id:
        selected_user = Player.objects.filter(pk=selected_id, is_active=True).first()

    if selected_user is None:
        return JsonResponse({'messages': []})

    messages_data = _build_direct_conversation_messages(
        user_profile=user_profile,
        selected_user=selected_user,
        is_admin=is_admin,
        request_user=request.user,
    )
    return JsonResponse({'messages': messages_data})


@login_required(login_url='scheduling:login')
def chatting_unread_status(request):
    user_profile = getattr(request.user, 'player_profile', None)
    unread_contact_ids = []

    if user_profile is not None:
        contacts = Player.objects.filter(is_active=True).exclude(pk=user_profile.pk)
        unread_contact_ids = list(
            Message.objects.filter(
                player=user_profile,
                sender__in=contacts,
                is_read=False,
            )
            .values_list('sender_id', flat=True)
            .distinct()
        )

    return JsonResponse({'unread_contact_ids': unread_contact_ids})


@login_required(login_url='scheduling:login')
def ai_analytics_hub(request):
    if request.user.is_staff:
        messages.info(request, 'AI analytics is not available for admin accounts.')
        return redirect('scheduling:admin_home')

    analytics_context = build_ai_analytics_context(request.user)
    return render(
        request,
        'scheduling/ai_analytics_hub.html',
        {
            **analytics_context,
            'home_url': reverse(_post_login_route_for(request.user)),
            'role_label': _role_label_for(request.user),
        },
    )


@login_required(login_url='scheduling:login')
def create_session(request):
    if request.user.is_staff:
        messages.info(request, 'Scheduling is not available for admin accounts.')
        return redirect('scheduling:admin_home')

    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        form = TrainingSessionForm(request.POST)
        if form.is_valid():
            session = form.save()
            notification_title, notification_message = _new_session_notification_payload(session)
            qs = Player.objects.filter(is_active=True).exclude(pk=coach.pk)
            Notification.objects.bulk_create([
                Notification(
                    recipient=p,
                    title=notification_title,
                    message=notification_message,
                    notification_type=Notification.Type.TRAINING_CREATED,
                )
                for p in qs
            ])
            messages.success(request, 'Training session created.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        form = TrainingSessionForm()

    return render(request, 'scheduling/create_session.html', {'form': form})


@login_required(login_url='scheduling:login')
def edit_session(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)

    if not _can_manage_training_sessions(request.user):
        messages.error(request, 'Only coach or admin accounts can edit session details.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        form = TrainingSessionForm(request.POST, instance=session)
        if form.is_valid():
            session = form.save()
            editor = getattr(request.user, 'player_profile', None)
            qs = Player.objects.filter(is_active=True)
            if editor:
                qs = qs.exclude(pk=editor.pk)
            Notification.objects.bulk_create(
                [
                    Notification(
                        recipient=player,
                        title='Session Updated',
                        message=f'{session.title} was updated for {session.starts_at} at {session.location}.',
                        notification_type=Notification.Type.SESSION_UPDATED,
                    )
                    for player in qs
                ]
            )
            messages.success(request, 'Training session updated.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        form = TrainingSessionForm(instance=session)

    return render(request, 'scheduling/edit_session.html', {'form': form, 'session': session})


@login_required(login_url='scheduling:login')
def cancel_session(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)
    actor_profile = getattr(request.user, 'player_profile', None) if request.user.is_authenticated else None
    can_delete = request.user.is_staff or (
        actor_profile is not None and actor_profile.role == Player.Role.COACH
    )

    if not can_delete:
        messages.error(request, 'Only coach or admin accounts can delete sessions.')
        return redirect('scheduling:session_detail', session_id=session.id)

    if request.method == 'POST':
        deleted_by = actor_profile.name if actor_profile is not None else (request.user.get_username() or 'Admin')
        starts_label = timezone.localtime(session.starts_at).strftime('%b %d, %Y at %H:%M')
        title = session.title
        location = session.location

        recipients = list(Player.objects.filter(role=Player.Role.PLAYER, is_active=True))
        if recipients:
            Notification.objects.bulk_create(
                [
                    Notification(
                        recipient=recipient,
                        title='Training Session Deleted',
                        message=(
                            f'The training session "{title}" scheduled for {starts_label} at {location} '
                            f'was deleted by {deleted_by}.'
                        ),
                        notification_type=Notification.Type.SESSION_UPDATED,
                    )
                    for recipient in recipients
                ]
            )

        session.delete()
        messages.success(request, 'Training session deleted and notifications sent.')
        return redirect('scheduling:sessions_calendar')

    return render(request, 'scheduling/cancel_session.html', {'session': session})


@login_required(login_url='scheduling:login')
def next_session(request):
    session = (
        TrainingSession.objects.filter(starts_at__gte=timezone.now(), cancelled=False)
        .order_by('starts_at')
        .first()
    )

    if session is not None:
        local_start = timezone.localtime(session.starts_at)
        calendar_url = (
            f"{reverse('scheduling:sessions_calendar')}"
            f"?year={local_start.year}&month={local_start.month}&day={local_start.day}"
        )
    else:
        today = timezone.localdate()
        calendar_url = (
            f"{reverse('scheduling:sessions_calendar')}"
            f"?year={today.year}&month={today.month}&day={today.day}"
        )

    return render(
        request,
        'scheduling/next_session.html',
        {
            'session': session,
            'home_url': _post_login_route_for(request.user),
            'calendar_url': calendar_url,
        },
    )


@login_required(login_url='scheduling:login')
def sessions_calendar(request):
    if request.user.is_staff:
        messages.info(request, 'Scheduling is not available for admin accounts.')
        return redirect('scheduling:admin_home')

    profile = getattr(request.user, 'player_profile', None)
    can_rsvp = profile is not None and profile.role == Player.Role.PLAYER
    can_add_sessions = request.user.is_staff or (
        profile is not None and profile.role == Player.Role.COACH
    )
    can_add_personal_events = profile is not None and profile.role == Player.Role.PLAYER
    can_add_events = can_add_sessions or can_add_personal_events

    today = timezone.localdate()
    default_year = today.year
    default_month = today.month
    default_day = today.day

    date_params = request.POST if request.method == 'POST' else request.GET

    try:
        year = int(date_params.get('year', default_year))
        month = int(date_params.get('month', default_month))
        if month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        year = default_year
        month = default_month

    month_start = date(year, month, 1)
    next_month = date(year + (month // 12), (month % 12) + 1, 1)
    month_end_day = calendar.monthrange(year, month)[1]

    try:
        selected_day = int(date_params.get('day', default_day))
    except (TypeError, ValueError):
        selected_day = default_day
    selected_day = max(1, min(selected_day, month_end_day))
    selected_date = date(year, month, selected_day)

    local_tz = timezone.get_current_timezone()
    selected_query = f"{reverse('scheduling:sessions_calendar')}?year={year}&month={month}&day={selected_day}"

    action = request.POST.get('calendar_action') if request.method == 'POST' else ''

    quick_add = {
        'title': request.POST.get('quick_title', '').strip() if action == 'quick_add' else '',
        'start_time': request.POST.get('quick_start_time', '') if action == 'quick_add' else '',
        'end_time': request.POST.get('quick_end_time', '') if action == 'quick_add' else '',
        'location': request.POST.get('quick_location', '').strip() if action == 'quick_add' else '',
        'session_type': (
            request.POST.get('quick_session_type', TrainingSession.SessionType.PRACTICE)
            if action == 'quick_add'
            else TrainingSession.SessionType.PRACTICE
        ),
    }

    if request.method == 'POST':
        if action == 'rsvp':
            session_id = request.POST.get('session_id')
            rsvp_status = request.POST.get('rsvp_status')
            if not can_rsvp:
                messages.error(request, 'Only player accounts can accept or decline sessions.')
            elif rsvp_status not in {SessionRSVP.Status.GOING, SessionRSVP.Status.NOT_GOING}:
                messages.error(request, 'Invalid RSVP action.')
            else:
                target_session = TrainingSession.objects.filter(pk=session_id, cancelled=False).first()
                if target_session is None:
                    messages.error(request, 'Session is no longer available for RSVP.')
                else:
                    existing_rsvp = SessionRSVP.objects.filter(session=target_session, player=profile).first()
                    previous_status = existing_rsvp.status if existing_rsvp is not None else None

                    SessionRSVP.objects.update_or_create(
                        session=target_session,
                        player=profile,
                        defaults={'status': rsvp_status},
                    )

                    if previous_status != rsvp_status:
                        _notify_coaches_of_player_rsvp(profile, target_session, rsvp_status)

                    messages.success(request, 'RSVP updated.')
            return redirect(selected_query)

        if action == 'quick_add':
            if not can_add_events:
                messages.error(request, 'This account cannot add events.')
            else:
                title = quick_add['title']
                location = quick_add['location']
                start_time_raw = quick_add['start_time']
                end_time_raw = quick_add['end_time']
                session_type = quick_add['session_type']

                if not title or not location or not start_time_raw or not end_time_raw:
                    messages.error(request, 'Please fill in session name, start time, end time, and location.')
                elif can_add_sessions and session_type not in {
                    TrainingSession.SessionType.PRACTICE,
                    TrainingSession.SessionType.FRIENDLY,
                    TrainingSession.SessionType.MATCH,
                }:
                    messages.error(request, 'Please choose a valid session type.')
                else:
                    try:
                        start_clock = time.fromisoformat(start_time_raw)
                        end_clock = time.fromisoformat(end_time_raw)
                    except ValueError:
                        messages.error(request, 'Please use valid time values for start and end.')
                    else:
                        if end_clock <= start_clock:
                            messages.error(request, 'End time must be later than start time.')
                        else:
                            starts_at_local = timezone.make_aware(datetime.combine(selected_date, start_clock), local_tz)
                            ends_at_local = timezone.make_aware(datetime.combine(selected_date, end_clock), local_tz)
                            if can_add_sessions:
                                session = TrainingSession.objects.create(
                                    title=title,
                                    starts_at=starts_at_local,
                                    ends_at=ends_at_local,
                                    location=location,
                                    session_type=session_type,
                                    notes='Calendar quick-add.',
                                )
                                notification_title, notification_message = _new_session_notification_payload(session)
                                qs = Player.objects.filter(is_active=True)
                                if profile:
                                    qs = qs.exclude(pk=profile.pk)
                                Notification.objects.bulk_create([
                                    Notification(
                                        recipient=p,
                                        title=notification_title,
                                        message=notification_message,
                                        notification_type=Notification.Type.TRAINING_CREATED,
                                    )
                                    for p in qs
                                ])
                                messages.success(request, 'Session added to the team schedule.')
                            elif can_add_personal_events:
                                PersonalCalendarEvent.objects.create(
                                    player=profile,
                                    title=title,
                                    starts_at=starts_at_local,
                                    ends_at=ends_at_local,
                                    location=location,
                                    notes='Personal calendar event.',
                                )
                                messages.success(request, 'Event added to your personal calendar.')
                            return redirect(selected_query)

    month_start_dt = timezone.make_aware(datetime.combine(month_start, time.min), local_tz)
    next_month_dt = timezone.make_aware(datetime.combine(next_month, time.min), local_tz)

    month_sessions = list(
        TrainingSession.objects.filter(
            starts_at__gte=month_start_dt,
            starts_at__lt=next_month_dt,
            cancelled=False,
        ).order_by('starts_at')
    )
    month_personal_events = []
    if can_add_personal_events:
        month_personal_events = list(
            PersonalCalendarEvent.objects.filter(
                player=profile,
                starts_at__gte=month_start_dt,
                starts_at__lt=next_month_dt,
            ).order_by('starts_at')
        )

    sessions_by_day = {}
    for training_session in month_sessions:
        local_starts = timezone.localtime(training_session.starts_at, local_tz)
        day_key = local_starts.date()
        sessions_by_day.setdefault(day_key, []).append(
            {
                'id': training_session.id,
                'title': training_session.title,
                'location': training_session.location,
                'starts_at': training_session.starts_at,
                'ends_at': training_session.ends_at,
                'is_personal': False,
            }
        )

    for personal_event in month_personal_events:
        local_starts = timezone.localtime(personal_event.starts_at, local_tz)
        day_key = local_starts.date()
        sessions_by_day.setdefault(day_key, []).append(
            {
                'id': personal_event.id,
                'title': personal_event.title,
                'location': personal_event.location,
                'starts_at': personal_event.starts_at,
                'ends_at': personal_event.ends_at,
                'is_personal': True,
            }
        )

    for day_events in sessions_by_day.values():
        day_events.sort(key=lambda item: item['starts_at'])

    calendar_weeks = []
    cal = calendar.Calendar(firstweekday=6)
    for week in cal.monthdatescalendar(year, month):
        week_days = []
        for week_day in week:
            event_count = len(sessions_by_day.get(week_day, []))
            week_days.append(
                {
                    'day': week_day.day,
                    'date': week_day,
                    'in_month': week_day.month == month,
                    'is_today': week_day == today,
                    'is_selected': week_day == selected_date,
                    'event_count': event_count,
                }
            )
        calendar_weeks.append(week_days)

    selected_day_sessions = sessions_by_day.get(selected_date, [])
    timeline_start_hour = 0
    timeline_end_hour = 24
    timeline_pixels_per_hour = 72
    timeline_total_minutes = (timeline_end_hour - timeline_start_hour) * 60
    timeline_canvas_height = int((timeline_total_minutes / 60) * timeline_pixels_per_hour)

    raw_timeline_events = []
    for timeline_event in selected_day_sessions:
        local_start = timezone.localtime(timeline_event['starts_at'], local_tz)
        local_end = timezone.localtime(timeline_event['ends_at'], local_tz)
        start_minutes = int((local_start.hour - timeline_start_hour) * 60 + local_start.minute)
        end_minutes = int((local_end.hour - timeline_start_hour) * 60 + local_end.minute)
        clipped_start = max(0, start_minutes)
        clipped_end = min(timeline_total_minutes, end_minutes)
        if clipped_end <= 0 or clipped_start >= timeline_total_minutes:
            continue

        raw_timeline_events.append(
            {
                'id': timeline_event['id'],
                'title': timeline_event['title'],
                'location': timeline_event['location'],
                'is_personal': timeline_event['is_personal'],
                'start_label': local_start.strftime('%I:%M %p').lstrip('0').lower(),
                'end_label': local_end.strftime('%I:%M %p').lstrip('0').lower(),
                'start_minutes': clipped_start,
                'end_minutes': clipped_end,
            }
        )

    raw_timeline_events.sort(key=lambda item: (item['start_minutes'], item['end_minutes'], item['id']))

    overlap_clusters = []
    current_cluster = []
    current_cluster_end = None
    for event in raw_timeline_events:
        if not current_cluster or event['start_minutes'] < current_cluster_end:
            current_cluster.append(event)
            current_cluster_end = max(current_cluster_end or event['end_minutes'], event['end_minutes'])
        else:
            overlap_clusters.append(current_cluster)
            current_cluster = [event]
            current_cluster_end = event['end_minutes']
    if current_cluster:
        overlap_clusters.append(current_cluster)

    timeline_events = []
    for cluster in overlap_clusters:
        active_columns = []
        max_columns = 0
        for event in cluster:
            active_columns = [item for item in active_columns if item['end_minutes'] > event['start_minutes']]
            used_columns = {item['column'] for item in active_columns}
            column = 0
            while column in used_columns:
                column += 1
            event['column'] = column
            active_columns.append({'column': column, 'end_minutes': event['end_minutes']})
            max_columns = max(max_columns, len(active_columns), column + 1)

        width_pct = 100 / max_columns if max_columns else 100
        for event in cluster:
            event['top_px'] = int((event['start_minutes'] / 60) * timeline_pixels_per_hour)
            event['height_px'] = max(56, int(((event['end_minutes'] - event['start_minutes']) / 60) * timeline_pixels_per_hour))
            event['left_pct'] = event['column'] * width_pct
            event['width_pct'] = width_pct
            timeline_events.append(event)

    player_rsvp_by_session_id = {}
    if can_rsvp and profile is not None:
        month_session_ids = [event['id'] for event in raw_timeline_events if not event['is_personal']]
        if month_session_ids:
            player_rsvp_by_session_id = {
                rsvp.session_id: rsvp.status
                for rsvp in SessionRSVP.objects.filter(player=profile, session_id__in=month_session_ids)
            }

    for event in timeline_events:
        if event['is_personal']:
            continue
        event['viewer_rsvp_status'] = player_rsvp_by_session_id.get(event['id'])

    timeline_markers = []
    for hour in range(timeline_start_hour, timeline_end_hour + 1):
        display_hour = hour % 12 or 12
        suffix = 'am' if hour < 12 or hour == 24 else 'pm'
        timeline_markers.append(
            {
                'label': f'{display_hour}{suffix}',
                'top_px': hour * timeline_pixels_per_hour,
            }
        )

    current_time_top_px = None
    if selected_date == today:
        now_local = timezone.localtime(timezone.now(), local_tz)
        current_minutes = now_local.hour * 60 + now_local.minute
        current_time_top_px = int((current_minutes / 60) * timeline_pixels_per_hour)
        current_time_top_px = max(0, min(current_time_top_px, timeline_canvas_height))

    prev_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    next_month_nav = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    can_manage_availability_polls = request.user.is_staff or (
        profile is not None and profile.role == Player.Role.COACH
    )

    context = {
        'home_url': _post_login_route_for(request.user),
        'role_label': profile.get_role_display() if profile is not None else ('Admin' if request.user.is_staff else 'Member'),
        'can_manage_availability_polls': can_manage_availability_polls,
        'can_rsvp': can_rsvp,
        'calendar_title': month_start.strftime('%B %Y'),
        'selected_date': selected_date,
        'calendar_weeks': calendar_weeks,
        'timeline_markers': timeline_markers,
        'timeline_canvas_height': timeline_canvas_height,
        'timeline_events': timeline_events,
        'current_time_top_px': current_time_top_px,
        'featured_event': timeline_events[0] if timeline_events else None,
        'month_prev': prev_month,
        'month_next': next_month_nav,
        'quick_add': quick_add,
        'can_add_sessions': can_add_sessions,
        'can_add_events': can_add_events,
        'can_add_personal_events': can_add_personal_events,
        'active_nav': 'schedule',
    }
    return render(request, 'scheduling/sessions_calendar.html', context)


@login_required(login_url='scheduling:login')
def session_detail(request, session_id):
    session = get_object_or_404(
        TrainingSession.objects.annotate(
            going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.GOING)),
            not_going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.NOT_GOING)),
        ),
        pk=session_id,
    )

    user_profile = getattr(request.user, 'player_profile', None)
    is_player = user_profile is not None and user_profile.role == Player.Role.PLAYER
    is_coach = user_profile is not None and user_profile.role == Player.Role.COACH
    is_admin = request.user.is_staff
    can_manage_session = _can_manage_training_sessions(request.user)

    current_rsvp = session.rsvps.filter(player=user_profile).first() if is_player else None

    if request.method == 'POST':
        if not is_player:
            messages.error(request, 'Only player accounts can update an RSVP.')
            return redirect('scheduling:session_detail', session_id=session.id)

        form = SessionRSVPForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data['status']
            SessionRSVP.objects.update_or_create(
                session=session,
                player=user_profile,
                defaults={'status': status},
            )
            _notify_coaches_of_player_rsvp(user_profile, session, status)
            messages.success(request, 'RSVP saved.')
            return redirect('scheduling:session_detail', session_id=session.id)

        messages.error(request, 'Please choose whether you are going or not going.')
    else:
        initial = {'player': user_profile.id, 'status': current_rsvp.status} if current_rsvp else None
        form = SessionRSVPForm(initial=initial) if is_player else None

    rsvps = list(session.rsvps.select_related('player').order_by('player__name'))
    rsvp_by_player_id = {rsvp.player_id: rsvp for rsvp in rsvps}
    active_players = list(Player.objects.filter(role=Player.Role.PLAYER, is_active=True).order_by('name'))

    participant_rows = []
    for player in active_players:
        rsvp = rsvp_by_player_id.get(player.id)
        if rsvp is None:
            status_text = 'Pending'
            status_class = 'is-pending'
        elif rsvp.status == SessionRSVP.Status.GOING:
            status_text = 'Going'
            status_class = 'is-going'
        else:
            status_text = 'Not Going'
            status_class = 'is-not-going'
        participant_rows.append(
            {
                'player': player,
                'status_text': status_text,
                'status_class': status_class,
            }
        )

    available_rows = []
    for player in active_players:
        is_available = player.status == Player.Status.ELIGIBLE
        available_rows.append(
            {
                'player': player,
                'status_text': 'Available' if is_available else player.get_status_display(),
                'status_class': 'is-available' if is_available else 'is-on-break',
            }
        )

    personal_note_preview = None
    if user_profile is not None:
        personal_note_preview = session.personal_notes.filter(player=user_profile).first()

    local_starts = timezone.localtime(session.starts_at)
    local_ends = timezone.localtime(session.ends_at)
    calendar_back_url = (
        f"{reverse('scheduling:sessions_calendar')}"
        f"?year={local_starts.year}&month={local_starts.month}&day={local_starts.day}"
    )

    session_plan = getattr(session, 'plan', None)
    current_rsvp = session.rsvps.filter(player=user_profile).first() if is_player else None

    return render(
        request,
        'scheduling/session_detail.html',
        {
            'session': session,
            'form': form,
            'rsvps': rsvps,
            'participant_rows': participant_rows,
            'available_rows': available_rows,
            'personal_note_preview': personal_note_preview,
            'user_profile': user_profile,
            'can_manage_session': can_manage_session,
            'can_edit_personal_note': is_player,
            'calendar_back_url': calendar_back_url,
            'session_plan': session_plan,
            'is_player': is_player,
            'is_coach': is_coach,
            'is_admin': is_admin,
            'role_label': 'Admin' if is_admin else ('Coach' if is_coach else 'Player'),
            'current_rsvp': current_rsvp,
            'local_starts': local_starts,
            'local_ends': local_ends,
            'home_url': _post_login_route_for(request.user),
        },
    )


def coach_rsvp_overview(request):
    sessions = TrainingSession.objects.annotate(
        going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.GOING)),
        not_going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.NOT_GOING)),
    )
    return render(request, 'scheduling/coach_rsvp_overview.html', {'sessions': sessions})


def submit_availability(request):
    if request.method == 'POST':
        form = PlayerAvailabilityForm(request.POST)
        if form.is_valid():
            availability = form.save()
            messages.success(request, 'Availability saved.')
            return redirect('scheduling:availability_detail', availability_id=availability.id)
    else:
        form = PlayerAvailabilityForm()

    return render(request, 'scheduling/submit_availability.html', {'form': form})


def availability_detail(request, availability_id):
    availability = get_object_or_404(PlayerAvailability.objects.select_related('player'), pk=availability_id)
    return render(request, 'scheduling/availability_detail.html', {'availability': availability})


def coach_availability_overview(request):
    slots = PlayerAvailability.objects.select_related('player')
    grouped_slots = {}
    for slot in slots:
        grouped_slots.setdefault(slot.get_weekday_display(), []).append(slot)
    return render(request, 'scheduling/coach_availability_overview.html', {'grouped_slots': grouped_slots})


def create_vote_poll(request):
    if request.user.is_authenticated and request.user.is_staff:
        messages.info(request, 'Scheduling is not available for admin accounts.')
        return redirect('scheduling:admin_home')

    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    if not is_coach:
        return redirect('scheduling:polls_list')

    if request.method == 'POST':
        form = SessionVotePollForm(request.POST)
        if form.is_valid():
            poll = SessionVotePoll.objects.create(
                title=form.cleaned_data['title'],
                description=form.cleaned_data['description'],
                closes_at=form.cleaned_data['closes_at'],
            )
            SessionVoteOption.objects.bulk_create(
                [
                    SessionVoteOption(
                        poll=poll,
                        starts_at=form.cleaned_data['option_1_starts_at'],
                        location=form.cleaned_data['option_1_location'],
                    ),
                    SessionVoteOption(
                        poll=poll,
                        starts_at=form.cleaned_data['option_2_starts_at'],
                        location=form.cleaned_data['option_2_location'],
                    ),
                ]
            )
            messages.success(request, 'Candidate-time poll created.')
            return redirect('scheduling:vote_poll_detail', poll_id=poll.id)
    else:
        form = SessionVotePollForm()

    return render(request, 'scheduling/create_vote_poll.html', {'form': form})


def vote_poll_detail(request, poll_id):
    poll = get_object_or_404(
        SessionVotePoll.objects.annotate(vote_count=Count('votes')).prefetch_related('options__votes'),
        pk=poll_id,
    )
    profile = getattr(request.user, 'player_profile', None)
    can_vote = profile is not None and profile.role == Player.Role.PLAYER
    can_schedule_from_poll = request.user.is_staff or (
        profile is not None and profile.role == Player.Role.COACH
    )

    if request.method == 'POST':
        action = request.POST.get('poll_action', 'vote')

        if action == 'create_session':
            if not can_schedule_from_poll:
                messages.error(request, 'Only coach accounts can schedule from poll results.')
                return redirect('scheduling:vote_poll_detail', poll_id=poll.id)

            event_title = request.POST.get('event_title', '').strip()
            if not event_title:
                messages.error(request, 'Please provide an event name before creating the session.')
                return redirect('scheduling:vote_poll_detail', poll_id=poll.id)

            winning_option = (
                poll.options.annotate(vote_count=Count('votes'))
                .order_by('-vote_count', 'starts_at', 'id')
                .first()
            )

            if winning_option is None:
                messages.error(request, 'This poll has no options to schedule.')
                return redirect('scheduling:vote_poll_detail', poll_id=poll.id)

            existing_session = TrainingSession.objects.filter(
                title=event_title,
                starts_at=winning_option.starts_at,
                location=winning_option.location,
                cancelled=False,
            ).first()

            if existing_session is not None:
                messages.info(request, 'A training session has already been created from this winning option.')
                return redirect('scheduling:session_detail', session_id=existing_session.id)

            session = TrainingSession.objects.create(
                title=event_title,
                starts_at=winning_option.starts_at,
                ends_at=winning_option.starts_at + timedelta(hours=2),
                location=winning_option.location,
                session_type=TrainingSession.SessionType.PRACTICE,
                notes=f'Created automatically from poll "{poll.title}".',
            )

            notification_title, notification_message = _new_session_notification_payload(session)
            recipients = Player.objects.filter(is_active=True)
            if profile is not None:
                recipients = recipients.exclude(pk=profile.pk)
            Notification.objects.bulk_create(
                [
                    Notification(
                        recipient=recipient,
                        title=notification_title,
                        message=notification_message,
                        notification_type=Notification.Type.TRAINING_CREATED,
                    )
                    for recipient in recipients
                ]
            )

            poll.delete()

            messages.success(request, 'Training session created from the winning poll option.')
            return redirect('scheduling:session_detail', session_id=session.id)

        if not can_vote:
            messages.error(request, 'Only player accounts can vote in polls.')
            return redirect('scheduling:vote_poll_detail', poll_id=poll.id)

        form = SessionVoteForm(request.POST, poll=poll)
        if form.is_valid():
            SessionVote.objects.update_or_create(
                poll=poll,
                player=profile,
                defaults={'option': form.cleaned_data['option']},
            )
            messages.success(request, 'Vote saved.')
            return redirect('scheduling:vote_poll_detail', poll_id=poll.id)
    else:
        form = SessionVoteForm(poll=poll)

    options = poll.options.annotate(vote_count=Count('votes')).order_by('starts_at')
    votes = poll.votes.select_related('player', 'option')
    return render(
        request,
        'scheduling/vote_poll_detail.html',
        {
            'poll': poll,
            'form': form,
            'options': options,
            'votes': votes,
            'can_vote': can_vote,
            'can_schedule_from_poll': can_schedule_from_poll,
            'default_event_title': poll.title,
        },
    )


def polls_list(request):
    if request.user.is_authenticated and request.user.is_staff:
        messages.info(request, 'Scheduling is not available for admin accounts.')
        return redirect('scheduling:admin_home')

    polls = SessionVotePoll.objects.annotate(vote_count=Count('votes')).order_by('-created_at')
    profile = getattr(request.user, 'player_profile', None)
    can_create_poll = profile is not None and profile.role == Player.Role.COACH
    return render(request, 'scheduling/polls_list.html', {'polls': polls, 'can_create_poll': can_create_poll})


@login_required(login_url='scheduling:login')
def edit_session_plan(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)
    if not _can_manage_training_sessions(request.user):
        messages.error(request, 'Only coach or admin accounts can edit the session plan.')
        return redirect('scheduling:dashboard')

    try:
        plan = session.plan
    except SessionPlan.DoesNotExist:
        plan = None

    if request.method == 'POST':
        form = SessionPlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.session = session
            plan.save()
            messages.success(request, 'Session plan saved.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        initial = {'title': f'{session.title} Plan'} if plan is None else None
        form = SessionPlanForm(instance=plan, initial=initial)

    return render(request, 'scheduling/edit_session_plan.html', {'form': form, 'session': session})


@login_required(login_url='scheduling:login')
def personal_notes_overview(request):
    profile = getattr(request.user, 'player_profile', None)
    notes = PersonalSessionNote.objects.select_related('session', 'player').order_by('-updated_at')
    back_session_url = None

    source_session_id = request.GET.get('from_session')
    if source_session_id:
        try:
            back_session_url = reverse('scheduling:session_detail', args=[int(source_session_id)])
        except (TypeError, ValueError):
            back_session_url = None

    if profile is not None and profile.role == Player.Role.PLAYER:
        notes = notes.filter(player=profile)

    return render(
        request,
        'scheduling/personal_notes_overview.html',
        {
            'notes': notes,
            'home_url': _post_login_route_for(request.user),
            'back_session_url': back_session_url,
        },
    )


@login_required(login_url='scheduling:login')
def personal_note(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)
    note = None

    if request.method != 'POST':
        return redirect('scheduling:personal_notes_overview')

    profile = getattr(request.user, 'player_profile', None)
    if profile is None or profile.role != Player.Role.PLAYER:
        messages.error(request, 'Only player accounts can add personal notes.')
        return redirect('scheduling:session_detail', session_id=session.id)

    note = PersonalSessionNote.objects.filter(session=session, player=profile).first()
    form = PersonalSessionNoteForm(request.POST, instance=note)
    if form.is_valid():
        note = form.save(commit=False)
        note.session = session
        note.player = profile
        note.save()
        messages.success(request, 'Personal note saved.')
    else:
        messages.error(request, 'Could not save personal note. Please check the note content.')

    return redirect('scheduling:session_detail', session_id=session.id)


@login_required(login_url='scheduling:login')
def notification_inbox(request):
    notifications = Notification.objects.select_related('recipient').order_by('-created_at', '-id')
    profile = getattr(request.user, 'player_profile', None)

    if profile is not None:
        notifications = notifications.filter(recipient=profile)
        role_label = profile.get_role_display()
        home_url = _post_login_route_for(request.user)
    else:
        role_label = 'Admin' if request.user.is_staff else 'Member'
        home_url = 'scheduling:admin_home' if request.user.is_staff else 'scheduling:landing'

    notifications = list(notifications)
    unread_ids = [notification.id for notification in notifications if notification.read_at is None]

    if unread_ids:
        Notification.objects.filter(id__in=unread_ids).update(read_at=timezone.now())

    for notification in notifications:
        notification.was_unread = notification.id in unread_ids

    return render(
        request,
        'scheduling/notification_inbox.html',
        {
            'notifications': notifications,
            'role_label': role_label,
            'home_url': home_url,
            'notification_count': len(notifications),
            'unread_count': len(unread_ids),
        },
    )


@login_required(login_url='scheduling:login')
def delete_notification(request, notification_id):
    notification = get_object_or_404(Notification.objects.select_related('recipient'), pk=notification_id)
    profile = getattr(request.user, 'player_profile', None)

    if not request.user.is_staff and (profile is None or notification.recipient_id != profile.id):
        messages.error(request, 'You cannot delete this notification.')
        return redirect('scheduling:notification_inbox')

    if request.method == 'POST':
        notification.delete()
        messages.success(request, 'Notification deleted.')
        return redirect('scheduling:notification_inbox')

    return render(request, 'scheduling/delete_notification.html', {'notification': notification})


@login_required(login_url='scheduling:login')
def create_tryout_session(request):
    if request.user.is_staff:
        messages.info(request, 'Tryouts are not available for admin accounts.')
        return redirect('scheduling:admin_home')

    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        form = TryoutSessionForm(request.POST)
        if form.is_valid():
            tryout_session = form.save()
            recipients = list(Player.objects.filter(is_active=True).exclude(pk=coach.pk))
            Notification.objects.bulk_create([
                Notification(
                    recipient=p,
                    title='New Tryout Session',
                    message=(
                        f'A new tryout "{tryout_session.title}" has been scheduled'
                        f' for {tryout_session.starts_at.strftime("%b %d, %Y at %H:%M")}'
                        f' at {tryout_session.location}.'
                    ),
                    notification_type=Notification.Type.TRYOUT_CREATED,
                )
                for p in recipients
            ])
            messages.success(request, 'Tryout session created.')
            return redirect('scheduling:tryout_session_detail', tryout_session_id=tryout_session.id)
    else:
        form = TryoutSessionForm()

    return render(request, 'scheduling/create_tryout_session.html', {'form': form, 'coach': coach})


def register_tryout_candidate(request):
    open_tryouts = TryoutSession.objects.filter(registration_open=True).order_by('starts_at')

    if request.method == 'POST':
        form = TryoutCandidateForm(request.POST)
        if form.is_valid():
            candidate = form.save()
            messages.success(request, 'Tryout registration submitted.')
            profile = getattr(request.user, 'player_profile', None) if request.user.is_authenticated else None
            if profile is not None and profile.role == Player.Role.PLAYER:
                return redirect('scheduling:player_tryout_list')
            return redirect('scheduling:tryout_candidate_detail', candidate_id=candidate.id)
    else:
        form = TryoutCandidateForm()

    return render(
        request,
        'scheduling/register_tryout_candidate.html',
        {
            'form': form,
            'open_tryouts': open_tryouts,
        },
    )


@login_required(login_url='scheduling:login')
def tryout_session_detail(request, tryout_session_id):
    if request.user.is_staff:
        messages.info(request, 'Tryouts are not available for admin accounts.')
        return redirect('scheduling:admin_home')

    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    tryout_session = get_object_or_404(TryoutSession.objects.prefetch_related('candidates'), pk=tryout_session_id)
    return render(
        request,
        'scheduling/tryout_session_detail.html',
        {
            'coach': coach,
            'tryout_session': tryout_session,
            'candidate_count': tryout_session.candidates.count(),
        },
    )


def delete_tryout_session(request, tryout_session_id):
    if request.user.is_authenticated and request.user.is_staff:
        messages.info(request, 'Tryouts are not available for admin accounts.')
        return redirect('scheduling:admin_home')

    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    tryout_session = get_object_or_404(TryoutSession, pk=tryout_session_id)
    if request.method == 'POST':
        tryout_session.delete()
        messages.success(request, 'Tryout session deleted.')
        return redirect('scheduling:tryout_list')
    return render(request, 'scheduling/delete_tryout_session.html', {'tryout_session': tryout_session})


def tryout_candidate_detail(request, candidate_id):
    candidate = get_object_or_404(TryoutCandidate.objects.select_related('tryout_session'), pk=candidate_id)
    return render(request, 'scheduling/tryout_candidate_detail.html', {'candidate': candidate})


def convert_tryout_candidate(request, candidate_id):
    candidate = get_object_or_404(TryoutCandidate.objects.select_related('tryout_session'), pk=candidate_id)

    if request.method == 'POST':
        if candidate.status != TryoutCandidate.Status.CONVERTED:
            Player.objects.get_or_create(
                email=candidate.email,
                defaults={'name': candidate.name, 'role': Player.Role.PLAYER},
            )
            candidate.status = TryoutCandidate.Status.CONVERTED
            candidate.save(update_fields=['status'])
            messages.success(request, 'Candidate accepted as player.')
        else:
            candidate.status = TryoutCandidate.Status.SUBMITTED
            candidate.save(update_fields=['status'])
            messages.success(request, 'Candidate moved back to submitted status.')
        return redirect('scheduling:tryout_candidate_detail', candidate_id=candidate.id)

    return render(request, 'scheduling/convert_tryout_candidate.html', {'candidate': candidate})


@login_required(login_url='scheduling:login')
def player_status_list(request):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    admin_team = _get_admin_team(request.user)
    players = Player.objects.filter(role=Player.Role.PLAYER, is_approved=True)
    coaches = Player.objects.filter(role=Player.Role.COACH, is_approved=True)
    if admin_team is not None:
        pending_players = Player.objects.filter(role=Player.Role.PLAYER, team=admin_team, is_approved=False).order_by('name')
        pending_coaches = Player.objects.filter(role=Player.Role.COACH, team=admin_team, is_approved=False).order_by('name')
    else:
        pending_players = Player.objects.none()
        pending_coaches = Player.objects.none()
    return render(request, 'scheduling/player_status_list.html', {
        'players': players,
        'coaches': coaches,
        'pending_players': pending_players,
        'pending_coaches': pending_coaches,
    })


def eligible_players(request):
    players = Player.objects.filter(
        role=Player.Role.PLAYER,
        is_active=True,
        status=Player.Status.ELIGIBLE,
    )
    return render(request, 'scheduling/eligible_players.html', {'players': players})


@login_required(login_url='scheduling:login')
def update_player_status(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    player = get_object_or_404(Player, pk=player_id)

    if request.method == 'POST':
        form = PlayerUpdateForm(request.POST, instance=player)
        if form.is_valid():
            player = form.save()
            _sync_linked_user_access(player)
            messages.success(request, 'Player updated.')
            return redirect('scheduling:player_status_list')
    else:
        form = PlayerUpdateForm(instance=player)

    return render(request, 'scheduling/update_player_status.html', {'form': form, 'player': player})


@login_required(login_url='scheduling:login')
def activate_player(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)

    if request.method == 'POST':
        player.is_active = True
        player.save(update_fields=['is_active'])
        _sync_linked_user_access(player)
        messages.success(request, 'Player activated.')
        return redirect('scheduling:manage_player_detail', player_id=player.id)

    return redirect('scheduling:manage_player_detail', player_id=player.id)


@login_required(login_url='scheduling:login')
def deactivate_player(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)

    if request.method == 'POST':
        player.is_active = False
        player.save(update_fields=['is_active'])
        _sync_linked_user_access(player)
        messages.success(request, 'Player deactivated.')
        return redirect('scheduling:player_status_list')

    return render(request, 'scheduling/deactivate_player.html', {'player': player})


@login_required(login_url='scheduling:login')
def manage_player_detail(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)
    
    context = {
        'player': player,
    }
    return render(request, 'scheduling/manage_player_detail.html', context)


@login_required(login_url='scheduling:login')
def deactivate_coach(request, coach_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    coach = get_object_or_404(Player, pk=coach_id, role=Player.Role.COACH)

    if request.method == 'POST':
        coach.is_active = False
        coach.save(update_fields=['is_active'])
        _sync_linked_user_access(coach)
        messages.success(request, 'Coach deactivated.')
        return redirect('scheduling:player_status_list')

    return render(request, 'scheduling/deactivate_coach.html', {'coach': coach})


@login_required(login_url='scheduling:login')
def chat_with_player(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)
    
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.player = player
            message.sender_is_admin = True
            message.save()
            _create_chat_notification(
                recipient=player,
                sender_name=_chat_sender_name(request.user),
                content=message.content,
            )
            messages.success(request, 'Message sent successfully.')
            return redirect('scheduling:chat_with_player', player_id=player_id)
    else:
        form = MessageForm()
    
    # Get all messages for this player
    player_messages = Message.objects.filter(player=player).order_by('-created_at')
    
    context = {
        'player': player,
        'form': form,
        'messages': player_messages,
    }
    return render(request, 'scheduling/chat_with_player.html', context)


@login_required(login_url='scheduling:login')
def player_support(request, player_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)
    
    if request.method == 'POST':
        form = SupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.player = player
            ticket.save()
            messages.success(request, 'Support ticket created successfully.')
            return redirect('scheduling:player_support', player_id=player_id)
    else:
        form = SupportTicketForm()
    
    # Get all support tickets for this player
    support_tickets = SupportTicket.objects.filter(player=player).order_by('-created_at')
    
    context = {
        'player': player,
        'form': form,
        'support_tickets': support_tickets,
    }
    return render(request, 'scheduling/player_support.html', context)


@login_required(login_url='scheduling:login')
def coach_list(request):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    coaches = Player.objects.filter(role=Player.Role.COACH, is_active=True)
    context = {
        'coaches': coaches,
    }
    return render(request, 'scheduling/coach_list.html', context)


@login_required(login_url='scheduling:login')
def manage_coach_detail(request, coach_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    coach = get_object_or_404(Player, pk=coach_id, role=Player.Role.COACH)
    
    context = {
        'coach': coach,
    }
    return render(request, 'scheduling/manage_coach_detail.html', context)


@login_required(login_url='scheduling:login')
def chat_with_coach(request, coach_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    coach = get_object_or_404(Player, pk=coach_id, role=Player.Role.COACH)
    
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.player = coach
            message.sender_is_admin = True
            message.save()
            _create_chat_notification(
                recipient=coach,
                sender_name=_chat_sender_name(request.user),
                content=message.content,
            )
            messages.success(request, 'Message sent successfully.')
            return redirect('scheduling:chat_with_coach', coach_id=coach_id)
    else:
        form = MessageForm()
    
    # Get all messages for this coach
    coach_messages = Message.objects.filter(player=coach).order_by('-created_at')
    
    context = {
        'coach': coach,
        'form': form,
        'messages': coach_messages,
    }
    return render(request, 'scheduling/chat_with_coach.html', context)


@login_required(login_url='scheduling:login')
def coach_support(request, coach_id):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')
    
    coach = get_object_or_404(Player, pk=coach_id, role=Player.Role.COACH)
    
    if request.method == 'POST':
        form = SupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.player = coach
            ticket.save()
            messages.success(request, 'Support ticket created successfully.')
            return redirect('scheduling:coach_support', coach_id=coach_id)
    else:
        form = SupportTicketForm()
    
    # Get all support tickets for this coach
    support_tickets = SupportTicket.objects.filter(player=coach).order_by('-created_at')
    
    context = {
        'coach': coach,
        'form': form,
        'support_tickets': support_tickets,
    }
    return render(request, 'scheduling/coach_support.html', context)


@login_required(login_url='scheduling:login')
def team_stats_dashboard(request):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    is_league_handler = _can_manage_stats_entries(profile)
    is_admin = request.user.is_staff
    if not is_admin and not is_coach and not is_league_handler:
        return redirect(_post_login_route_for(request.user))

    coach_team = profile.team if is_coach else None
    matches = Match.objects.all()
    players = Player.objects.filter(role=Player.Role.PLAYER, is_active=True)
    player_stats_queryset = PlayerMatchStat.objects.all()

    if is_coach:
        if coach_team is None:
            matches = Match.objects.none()
            players = Player.objects.none()
            player_stats_queryset = PlayerMatchStat.objects.none()
        else:
            matches = matches.filter(team=coach_team)
            players = players.filter(team=coach_team)
            player_stats_queryset = player_stats_queryset.filter(
                match__team=coach_team,
                player__team=coach_team,
            )

    total_wins = sum(1 for m in matches if m.result == Match.Result.WIN)
    total_losses = sum(1 for m in matches if m.result == Match.Result.LOSS)
    total_draws = sum(1 for m in matches if m.result == Match.Result.DRAW)

    total_players = players.count()
    recovering_players = players.filter(status=Player.Status.RECOVERING).count()
    injured_players = players.filter(status=Player.Status.INJURED).count()
    non_eligible = recovering_players + injured_players
    recovery_pct = round(((total_players - non_eligible) / total_players) * 100) if total_players else 0

    top_scorers = (
        player_stats_queryset
        .values('player__id', 'player__name')
        .annotate(total_goals=Sum('goals'))
        .filter(total_goals__gt=0)
        .order_by('-total_goals')[:5]
    )
    top_defenders = (
        player_stats_queryset
        .values('player__id', 'player__name')
        .annotate(total_interceptions=Sum('interceptions'))
        .filter(total_interceptions__gt=0)
        .order_by('-total_interceptions')[:5]
    )

    goals_per_game = list(
        matches.order_by('date').values_list('opponent', 'goals_for')
    )

    metric_key = request.GET.get('metric', 'points')
    if metric_key not in TEAM_STAT_METRICS:
        metric_key = 'points'
    ranking_metric_label = TEAM_STAT_METRICS[metric_key]
    ranking_team = coach_team if is_coach else None
    top_players = _player_metric_rankings(metric_key, descending=True, team=ranking_team)
    weak_players = _player_metric_rankings(metric_key, descending=False, team=ranking_team)
    if is_coach and coach_team is None:
        top_players = []
        weak_players = []

    season_totals = _season_metric_totals(stats_queryset=player_stats_queryset)
    season_total_sum = sum(season_totals.values())
    season_percentages = [
        {
            'label': TEAM_STAT_METRICS[key],
            'value': season_totals[key],
            'percentage': round((season_totals[key] / season_total_sum) * 100, 1) if season_total_sum else 0,
        }
        for key in TEAM_STAT_METRICS
    ]

    team_goals = []
    for goal in TeamGoal.objects.all():
        current_value = season_totals.get(goal.metric, 0)
        progress_pct = round((current_value / goal.target_value) * 100) if goal.target_value else 0
        team_goals.append(
            {
                'goal': goal,
                'current_value': current_value,
                'progress_pct': progress_pct,
            }
        )

    soreness_overview = []
    for player in players:
        latest_report = player.soreness_reports.first()
        soreness_overview.append(
            {
                'player': player,
                'latest_report': latest_report,
            }
        )

    import json
    chart_labels = json.dumps([g[0] for g in goals_per_game])
    chart_data = json.dumps([g[1] for g in goals_per_game])
    season_percentage_labels = json.dumps([item['label'] for item in season_percentages])
    season_percentage_data = json.dumps([item['percentage'] for item in season_percentages])

    context = {
        'total_wins': total_wins,
        'total_losses': total_losses,
        'total_draws': total_draws,
        'recovery_pct': recovery_pct,
        'top_scorers': top_scorers,
        'top_defenders': top_defenders,
        'team_goals': team_goals,
        'top_players': top_players,
        'weak_players': weak_players,
        'ranking_metric': metric_key,
        'ranking_metric_label': ranking_metric_label,
        'metric_options': TEAM_STAT_METRICS.items(),
        'season_percentages': season_percentages,
        'season_percentage_labels': season_percentage_labels,
        'season_percentage_data': season_percentage_data,
        'soreness_overview': soreness_overview,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'match_count': matches.count(),
        'players': players,
        'can_manage_stats': is_league_handler,
        'home_url': _post_login_route_for(request.user),
    }
    return render(request, 'scheduling/team_stats.html', context)


@login_required(login_url='scheduling:login')
def player_stats_detail(request, player_id):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    is_league_handler = _can_manage_stats_entries(profile)
    is_player = profile is not None and profile.role == Player.Role.PLAYER

    if request.user.is_staff or is_league_handler:
        player = get_object_or_404(Player, pk=player_id)
        stats_queryset = PlayerMatchStat.objects.filter(player=player)
    elif is_coach:
        if profile.team is None:
            messages.error(request, 'Your coach account is not linked to a team.')
            return redirect('scheduling:team_stats')

        player = get_object_or_404(Player, pk=player_id)
        if player.team_id != profile.team_id:
            messages.error(request, 'You can only view stats for players on your team.')
            return redirect('scheduling:team_stats')
        stats_queryset = PlayerMatchStat.objects.filter(player=player, match__team=profile.team)
    elif is_player and profile.id == player_id:
        player = profile
        stats_queryset = PlayerMatchStat.objects.filter(player=player)
    else:
        messages.error(request, 'You can only view your own stats page.')
        return redirect('scheduling:player_home' if is_player else 'scheduling:dashboard')

    stats = stats_queryset.select_related('match').order_by('-match__date')

    totals = stats.aggregate(
        total_goals=Sum('goals'),
        total_interceptions=Sum('interceptions'),
        total_points=Sum('points'),
        total_blocks=Sum('blocks'),
        total_assists=Sum('assists'),
        total_aces=Sum('aces'),
        total_returns=Sum('returns'),
    )
    # Replace None with 0
    for k in totals:
        if totals[k] is None:
            totals[k] = 0

    averages = {
        'avg_goals': round(totals['total_goals'] / stats.count(), 2) if stats.count() else 0,
        'avg_interceptions': round(totals['total_interceptions'] / stats.count(), 2) if stats.count() else 0,
        'avg_points': round(totals['total_points'] / stats.count(), 2) if stats.count() else 0,
        'avg_blocks': round(totals['total_blocks'] / stats.count(), 2) if stats.count() else 0,
        'avg_assists': round(totals['total_assists'] / stats.count(), 2) if stats.count() else 0,
        'avg_aces': round(totals['total_aces'] / stats.count(), 2) if stats.count() else 0,
        'avg_returns': round(totals['total_returns'] / stats.count(), 2) if stats.count() else 0,
    }

    latest_injury = ''
    for s in stats:
        if s.most_recent_injury:
            latest_injury = s.most_recent_injury
            break

    stats_by_game = list(
        stats_queryset
        .select_related('match')
        .order_by('match__date', 'match__id')
    )

    import json
    game_labels = json.dumps([f'Game {idx}' for idx, _ in enumerate(stats_by_game, start=1)])
    aces_series = json.dumps([s.aces for s in stats_by_game])
    returns_series = json.dumps([s.returns for s in stats_by_game])
    blocks_series = json.dumps([s.blocks for s in stats_by_game])
    interceptions_series = json.dumps([s.interceptions for s in stats_by_game])
    points_series = json.dumps([s.points for s in stats_by_game])

    histogram_labels = json.dumps(['Aces', 'Returns', 'Blocks', 'Interceptions', 'Points'])
    histogram_data = json.dumps([
        totals['total_aces'],
        totals['total_returns'],
        totals['total_blocks'],
        totals['total_interceptions'],
        totals['total_points'],
    ])
    average_histogram_data = json.dumps([
        averages['avg_aces'],
        averages['avg_returns'],
        averages['avg_blocks'],
        averages['avg_interceptions'],
        averages['avg_points'],
    ])

    context = {
        'player': player,
        'stats': stats,
        'totals': totals,
        'averages': averages,
        'latest_injury': latest_injury,
        'matches_played': stats.count(),
        'can_view_team_dashboard': request.user.is_staff or is_coach or is_league_handler,
        'game_labels': game_labels,
        'aces_series': aces_series,
        'returns_series': returns_series,
        'blocks_series': blocks_series,
        'interceptions_series': interceptions_series,
        'points_series': points_series,
        'histogram_labels': histogram_labels,
        'histogram_data': histogram_data,
        'average_histogram_data': average_histogram_data,
    }
    return render(request, 'scheduling/player_stats_detail.html', context)


@login_required(login_url='scheduling:login')
def record_match(request):
    profile = getattr(request.user, 'player_profile', None)
    if not _can_manage_stats_entries(profile):
        return redirect(_post_login_route_for(request.user))

    if request.method == 'POST':
        form = LeagueMatchForm(request.POST)
        if form.is_valid():
            team_1 = form.cleaned_data['team_1']
            team_2 = form.cleaned_data['team_2']
            date = form.cleaned_data['date']
            score_1 = form.cleaned_data['team_1_score']
            score_2 = form.cleaned_data['team_2_score']
            notes = form.cleaned_data.get('notes', '')

            # Create a Match record from team_1's perspective
            match_1 = Match.objects.create(
                team=team_1,
                opponent=team_2.name,
                opponent_team=team_2,
                date=date,
                goals_for=score_1,
                goals_against=score_2,
                notes=notes,
            )
            # Create the mirror record from team_2's perspective
            match_2 = Match.objects.create(
                team=team_2,
                opponent=team_1.name,
                opponent_team=team_1,
                date=date,
                goals_for=score_2,
                goals_against=score_1,
                notes=notes,
            )

            # Notify all active players in both teams
            both_team_players = Player.objects.filter(
                is_active=True,
                team__in=[team_1, team_2],
            )
            if profile:
                both_team_players = both_team_players.exclude(pk=profile.pk)
            Notification.objects.bulk_create([
                Notification(
                    recipient=p,
                    title='New Match Result Recorded',
                    message=(
                        f'Match result recorded: {team_1.name} {score_1}–{score_2} {team_2.name}'
                        f' on {date.strftime("%b %d, %Y")}.'
                    ),
                    notification_type=Notification.Type.STATS_ADDED,
                )
                for p in both_team_players
            ])
            messages.success(request, f'Match recorded for both {team_1.name} and {team_2.name}.')
            return redirect('scheduling:record_player_stats', match_id=match_1.id)
    else:
        form = LeagueMatchForm()
    return render(request, 'scheduling/record_match.html', {'form': form})


@login_required(login_url='scheduling:login')
def record_player_stats(request, match_id):
    profile = getattr(request.user, 'player_profile', None)
    if not _can_manage_stats_entries(profile):
        return redirect(_post_login_route_for(request.user))

    # match_id always belongs to team_1's record; find the mirror via opponent_team
    match = get_object_or_404(Match, pk=match_id)
    mirror_match = None
    if match.opponent_team is not None:
        mirror_match = (
            Match.objects
            .filter(team=match.opponent_team, opponent_team=match.team, date=match.date)
            .exclude(pk=match.id)
            .first()
        )

    # Determine which team's form to render: first team_1, then team_2
    current_phase = request.GET.get('phase', '1')
    if current_phase == '2' and mirror_match is not None:
        active_match = mirror_match
    else:
        active_match = match
        current_phase = '1'

    existing_stats = list(active_match.player_stats.select_related('player'))

    # Also collect stats already entered for the other match so we can show a combined summary
    other_match = mirror_match if current_phase == '1' else match
    other_stats = list(other_match.player_stats.select_related('player')) if other_match else []

    if request.method == 'POST':
        form = PlayerMatchStatForm(request.POST, team=active_match.team)
        if form.is_valid():
            stat = form.save(commit=False)
            stat.match = active_match
            stat.save()
            messages.success(request, f'Stats for {stat.player.name} saved.')
            return redirect(
                f"{reverse('scheduling:record_player_stats', args=[match_id])}?phase={current_phase}"
            )
    else:
        form = PlayerMatchStatForm(team=active_match.team)

    return render(request, 'scheduling/record_player_stats.html', {
        'form': form,
        'match': match,
        'active_match': active_match,
        'mirror_match': mirror_match,
        'current_phase': current_phase,
        'existing_stats': existing_stats,
        'other_stats': other_stats,
    })


@login_required(login_url='scheduling:login')
def add_team_goal(request):
    profile = getattr(request.user, 'player_profile', None)
    if not _can_manage_stats_entries(profile):
        return redirect(_post_login_route_for(request.user))

    if request.method == 'POST':
        form = TeamGoalForm(request.POST)
        if form.is_valid():
            goal = form.save()
            qs = Player.objects.filter(is_active=True).exclude(role=Player.Role.LEAGUE_SYSTEM_HANDLER)
            if profile:
                qs = qs.exclude(pk=profile.pk)
            Notification.objects.bulk_create([
                Notification(
                    recipient=p,
                    title='New Team Goal Added',
                    message=f'A new team goal has been set: "{goal.description}".',
                    notification_type=Notification.Type.STATS_ADDED,
                )
                for p in qs
            ])
            messages.success(request, 'Team goal added.')
            return redirect('scheduling:team_stats')
    else:
        form = TeamGoalForm()
    return render(request, 'scheduling/add_team_goal.html', {'form': form})


# ── Upcoming Games ──────────────────────────────────────────────────────────

def _get_player_or_admin_team(request):
    """Return (team, player_profile) for players/coaches and admin users."""
    profile = getattr(request.user, 'player_profile', None)
    if profile is not None:
        return profile.team, profile
    if request.user.is_staff:
        assignment = (
            StaffTeamAssignment.objects
            .filter(user=request.user)
            .select_related('team')
            .first()
        )
        if assignment is not None:
            return assignment.team, None
    return None, None


@login_required(login_url='scheduling:login')
def upcoming_games(request):
    profile = getattr(request.user, 'player_profile', None)

    # League system handlers have their own dedicated page.
    if profile is not None and profile.role == Player.Role.LEAGUE_SYSTEM_HANDLER:
        return redirect('scheduling:league_handler_upcoming_games')

    team, player_profile = _get_player_or_admin_team(request)
    if team is None:
        messages.info(request, 'You are not assigned to a team.')
        return redirect('scheduling:dashboard')

    # Show games scheduled from 12 hours ago onwards (so just-passed games still appear briefly).
    cutoff = timezone.now() - timedelta(hours=12)
    games = (
        UpcomingGame.objects
        .filter(Q(home_team=team) | Q(away_team=team), scheduled_at__gte=cutoff)
        .select_related('home_team', 'away_team')
        .order_by('scheduled_at')
    )
    game_ids = [g.pk for g in games]

    # Pre-fetch all attendances for these games.
    all_attendances = (
        GameAttendance.objects
        .filter(game_id__in=game_ids)
        .select_related('player')
    )

    from collections import defaultdict
    att_by_game: dict = defaultdict(list)
    for att in all_attendances:
        att_by_game[att.game_id].append(att)

    # Current player's own attendance records (players only).
    is_player = player_profile is not None and player_profile.role == Player.Role.PLAYER
    my_attendance: dict = {}
    if is_player:
        my_attendance = {
            a.game_id: a
            for a in GameAttendance.objects.filter(game_id__in=game_ids, player=player_profile)
        }

    enriched_games = []
    for game in games:
        atts = att_by_game[game.pk]
        enriched_games.append({
            'game': game,
            'going': [a for a in atts if a.status == GameAttendance.Status.GOING],
            'not_going': [a for a in atts if a.status == GameAttendance.Status.NOT_GOING],
            'injured': [a for a in atts if a.status == GameAttendance.Status.INJURED],
            'maybe': [a for a in atts if a.status == GameAttendance.Status.MAYBE],
            'my_status': my_attendance.get(game.pk),
            'is_home': game.home_team_id == team.pk,
            'opponent': game.away_team if game.home_team_id == team.pk else game.home_team,
        })

    context = {
        'team': team,
        'enriched_games': enriched_games,
        'is_player': is_player,
        'attendance_choices': GameAttendance.Status.choices,
    }
    return render(request, 'scheduling/upcoming_games.html', context)


@login_required(login_url='scheduling:login')
def set_game_attendance(request, game_id):
    if request.method != 'POST':
        return redirect('scheduling:upcoming_games')

    profile = getattr(request.user, 'player_profile', None)
    if profile is None or profile.role != Player.Role.PLAYER:
        messages.error(request, 'Only players can set their game attendance.')
        return redirect('scheduling:upcoming_games')

    game = get_object_or_404(UpcomingGame, pk=game_id)
    # Ensure the game actually involves the player's team.
    if profile.team_id not in (game.home_team_id, game.away_team_id):
        messages.error(request, 'This game is not for your team.')
        return redirect('scheduling:upcoming_games')

    valid_statuses = {c[0] for c in GameAttendance.Status.choices}
    status = request.POST.get('status', '')
    if status not in valid_statuses:
        messages.error(request, 'Invalid attendance status.')
        return redirect('scheduling:upcoming_games')

    GameAttendance.objects.update_or_create(
        game=game,
        player=profile,
        defaults={'status': status},
    )
    messages.success(request, 'Your attendance status has been updated.')
    return redirect('scheduling:upcoming_games')


@login_required(login_url='scheduling:login')
def league_handler_upcoming_games(request):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.info(request, 'This page is only available to the league system handler.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            game = get_object_or_404(UpcomingGame, pk=request.POST.get('game_id'))
            game.delete()
            messages.success(request, 'Game removed.')
            return redirect('scheduling:league_handler_upcoming_games')
        form = UpcomingGameForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Upcoming game scheduled.')
            return redirect('scheduling:league_handler_upcoming_games')
    else:
        form = UpcomingGameForm()

    all_games = (
        UpcomingGame.objects
        .select_related('home_team', 'away_team')
        .order_by('scheduled_at')
    )
    context = {
        'handler': handler,
        'form': form,
        'games': all_games,
    }
    return render(request, 'scheduling/league_handler_upcoming_games.html', context)


@login_required(login_url='scheduling:login')
def pending_admins(request):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.info(request, 'This page is only available to the league system handler.')
        return redirect('scheduling:dashboard')
    pending = (
        StaffTeamAssignment.objects
        .filter(is_approved=False)
        .select_related('user', 'team')
        .order_by('created_at')
    )
    return render(request, 'scheduling/pending_admins.html', {'handler': handler, 'pending': pending})


@login_required(login_url='scheduling:login')
def approve_admin(request, assignment_id):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        return redirect('scheduling:dashboard')
    if request.method == 'POST':
        assignment = get_object_or_404(StaffTeamAssignment, pk=assignment_id, is_approved=False)
        assignment.is_approved = True
        assignment.save()
        messages.success(request, f'Admin account for {assignment.user.get_full_name() or assignment.user.username} has been approved.')
    return redirect('scheduling:pending_admins')


@login_required(login_url='scheduling:login')
def reject_admin(request, assignment_id):
    handler = getattr(request.user, 'player_profile', None)
    if handler is None or handler.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        return redirect('scheduling:dashboard')
    if request.method == 'POST':
        assignment = get_object_or_404(StaffTeamAssignment, pk=assignment_id, is_approved=False)
        admin_name = assignment.user.get_full_name() or assignment.user.username
        assignment.user.delete()  # cascades to assignment
        messages.success(request, f'Admin registration for {admin_name} has been rejected and removed.')
    return redirect('scheduling:pending_admins')


@login_required(login_url='scheduling:login')
def notifications_popup_data(request):
    """Return unread notifications as JSON for the real-time popup system."""
    profile = getattr(request.user, 'player_profile', None)
    if profile is None:
        return JsonResponse({'notifications': []})
    notifs = (
        Notification.objects
        .filter(recipient=profile, read_at__isnull=True)
        .order_by('-created_at')[:20]
    )
    data = [{'id': n.pk, 'title': n.title, 'message': n.message} for n in notifs]
    return JsonResponse({'notifications': data})


@login_required
def player_scouting_report(request, player_id):
    """Download a PDF scouting report for a player (coach own-team or admin)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        )
    except ImportError:
        messages.error(request, 'PDF generation requires reportlab. Run: pip install reportlab')
        return redirect('scheduling:manage_player_detail', player_id=player_id)

    viewer = request.user
    viewer_profile = getattr(viewer, 'player_profile', None)

    is_admin = viewer.is_staff
    is_coach = (
        viewer_profile is not None
        and viewer_profile.role == Player.Role.COACH
    )

    if not is_admin and not is_coach:
        messages.error(request, 'You do not have permission to download scouting reports.')
        return redirect('scheduling:dashboard')

    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)

    # Coaches can only scout players from their own team
    if is_coach and not is_admin:
        if viewer_profile.team is None or player.team != viewer_profile.team:
            messages.error(request, 'You can only download scouting reports for players on your team.')
            return redirect('scheduling:coach_home')

    stats_qs = (
        PlayerMatchStat.objects
        .filter(player=player)
        .select_related('match')
        .order_by('-match__date', '-match__id')
    )
    totals = {
        key: (stats_qs.aggregate(**{f't_{key}': Coalesce(Sum(key), Value(0))})[f't_{key}'])
        for key in ('goals', 'points', 'assists', 'blocks', 'aces', 'interceptions', 'returns')
    }
    last5 = list(stats_qs[:5])
    latest_soreness = player.soreness_reports.first()
    latest_injury = next((s.most_recent_injury for s in stats_qs if s.most_recent_injury), '')
    narrative = generate_scouting_narrative(player)

    # ---- Build PDF ----
    response = HttpResponse(content_type='application/pdf')
    safe_name = player.name.replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="scouting_{safe_name}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    forest = colors.HexColor('#3f5e4a')
    ink = colors.HexColor('#111111')
    accent = colors.HexColor('#0df2dc')

    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        textColor=forest,
        fontSize=20,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        'SectionHead',
        parent=styles['Heading2'],
        textColor=forest,
        fontSize=13,
        spaceBefore=14,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        textColor=ink,
        fontSize=10,
        leading=14,
    )

    story = []

    # Title
    story.append(Paragraph(f'Scouting Report: {player.name}', title_style))
    story.append(Paragraph(
        f'Generated {date.today():%B %d, %Y}',
        ParagraphStyle('sub', parent=styles['Normal'], fontSize=9, textColor=colors.grey),
    ))
    story.append(HRFlowable(width='100%', thickness=1, color=forest, spaceAfter=10))

    # Player profile table
    story.append(Paragraph('Player Profile', section_style))
    profile_data = [
        ['Name', player.name],
        ['Team', player.team.name if player.team else 'Unassigned'],
        ['Status', player.get_status_display() if hasattr(player, 'get_status_display') else player.status],
        ['Contract Expiry', str(player.contract_expiry) if player.contract_expiry else 'N/A'],
    ]
    profile_table = Table(profile_data, colWidths=[4 * cm, None])
    profile_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), forest),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(profile_table)

    # Career stats totals
    story.append(Paragraph('Career Stats (All Recorded Matches)', section_style))
    metric_labels = ['Goals', 'Points', 'Assists', 'Blocks', 'Aces', 'Interceptions', 'Returns']
    metric_keys = ['goals', 'points', 'assists', 'blocks', 'aces', 'interceptions', 'returns']
    stats_header = ['Metric', 'Total', '', 'Metric', 'Total']
    paired_rows = []
    for i in range(0, len(metric_keys), 2):
        left_label = metric_labels[i]
        left_val = str(totals[metric_keys[i]])
        if i + 1 < len(metric_keys):
            right_label = metric_labels[i + 1]
            right_val = str(totals[metric_keys[i + 1]])
        else:
            right_label = ''
            right_val = ''
        paired_rows.append([left_label, left_val, '', right_label, right_val])
    stats_table = Table(
        [stats_header] + paired_rows,
        colWidths=[4.5 * cm, 2.5 * cm, 0.8 * cm, 4.5 * cm, 2.5 * cm],
    )
    stats_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), forest),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('SPAN', (2, 0), (2, -1)),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (4, 0), (4, -1), 'CENTER'),
    ]))
    story.append(stats_table)

    # Last 5 matches form
    story.append(Paragraph('Last 5 Matches', section_style))
    if last5:
        match_header = ['Date', 'Opponent', 'Result', 'Pts', 'Aces', 'Blocks', 'Assists']
        match_rows = []
        for s in last5:
            m = s.match
            match_rows.append([
                m.date.strftime('%b %d, %Y'),
                m.opponent,
                m.result.upper(),
                str(s.points),
                str(s.aces),
                str(s.blocks),
                str(s.assists),
            ])
        form_table = Table(
            [match_header] + match_rows,
            colWidths=[2.8 * cm, None, 1.8 * cm, 1.4 * cm, 1.4 * cm, 1.8 * cm, 1.8 * cm],
        )
        form_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 0), (-1, 0), forest),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(form_table)
    else:
        story.append(Paragraph('No match stats recorded for this player yet.', body_style))

    # Recovery & injury notes
    story.append(Paragraph('Recovery & Injury Notes', section_style))
    soreness_text = (
        f'Latest soreness: {latest_soreness.soreness_level}/10 '
        f'(reported {latest_soreness.reported_at:%b %d, %Y})'
        if latest_soreness
        else 'No soreness report on file.'
    )
    story.append(Paragraph(soreness_text, body_style))
    if latest_injury:
        story.append(Paragraph(f'Latest injury note: {latest_injury}', body_style))
    else:
        story.append(Paragraph('No injury note on file.', body_style))

    # AI narrative
    story.append(Paragraph('AI Scout Analysis', section_style))
    story.append(HRFlowable(width='100%', thickness=0.5, color=accent, spaceAfter=6))
    story.append(Paragraph(narrative, body_style))

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(
        f'Report generated by Volleyball Club Management System on {date.today():%B %d, %Y}.',
        ParagraphStyle('footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey),
    ))

    doc.build(story)
    return response


@login_required
def opponent_analysis(request):
    """Opponent analysis page for league system handler."""
    profile = getattr(request.user, 'player_profile', None)
    if profile is None or profile.role != Player.Role.LEAGUE_SYSTEM_HANDLER:
        messages.error(request, 'Only the league system handler can access opponent analysis.')
        return redirect('scheduling:dashboard')

    teams = Team.objects.all().order_by('name')

    if request.method == 'POST':
        team1_id = request.POST.get('team1')
        team2_id = request.POST.get('team2')

        if not team1_id or not team2_id:
            messages.error(request, 'Please select two teams.')
            return render(request, 'scheduling/opponent_analysis.html', {'teams': teams})

        if team1_id == team2_id:
            messages.error(request, 'Please select two different teams.')
            return render(request, 'scheduling/opponent_analysis.html', {'teams': teams})

        team1 = get_object_or_404(Team, pk=team1_id)
        team2 = get_object_or_404(Team, pk=team2_id)

        def _team_record(team):
            matches = Match.objects.filter(team=team)
            wins = sum(1 for m in matches if m.result == Match.Result.WIN)
            losses = sum(1 for m in matches if m.result == Match.Result.LOSS)
            draws = sum(1 for m in matches if m.result == Match.Result.DRAW)
            goals_for = sum(m.goals_for for m in matches)
            goals_against = sum(m.goals_against for m in matches)
            return {
                'wins': wins, 'losses': losses, 'draws': draws,
                'played': wins + losses + draws,
                'goals_for': goals_for, 'goals_against': goals_against,
                'points': wins * 3 + draws,
                'gd': goals_for - goals_against,
            }

        t1_record = _team_record(team1)
        t2_record = _team_record(team2)

        # Head-to-head: team1 matches where opponent field matches team2 name
        h2h_t1 = list(
            Match.objects.filter(team=team1, opponent_team=team2).order_by('-date', '-id')[:5]
        )
        h2h_t2 = list(
            Match.objects.filter(team=team2, opponent_team=team1).order_by('-date', '-id')[:5]
        )
        # Recent form (last 5)
        t1_form = list(Match.objects.filter(team=team1).order_by('-date', '-id')[:5])
        t2_form = list(Match.objects.filter(team=team2).order_by('-date', '-id')[:5])

        ai_result = generate_opponent_analysis(
            team1_name=team1.name,
            t1_record=t1_record,
            team2_name=team2.name,
            t2_record=t2_record,
        )

        context = {
            'teams': teams,
            'team1': team1,
            'team2': team2,
            't1_record': t1_record,
            't2_record': t2_record,
            'h2h': h2h_t1,
            't1_form': t1_form,
            't2_form': t2_form,
            'ai_summary': ai_result['text'],
            'ai_source': ai_result['source'],
            'is_ai_enabled': ai_result['is_ai_enabled'],
        }
        return render(request, 'scheduling/opponent_analysis.html', context)

    return render(request, 'scheduling/opponent_analysis.html', {'teams': teams})

