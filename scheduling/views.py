import calendar
from datetime import date, datetime, time, timedelta

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    EmailAuthenticationForm,
    PlayerAvailabilityForm,
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
    SupportTicketForm,
    MatchForm,
    PlayerMatchStatForm,
    TeamGoalForm,
)
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
    Message,
    SupportTicket,
    Match,
    PlayerMatchStat,
    TeamGoal,
)


def _post_login_route_for(user):
    player = getattr(user, 'player_profile', None)
    if player is not None:
        if player.role == Player.Role.PLAYER:
            return 'scheduling:player_home'
        if player.role == Player.Role.COACH:
            return 'scheduling:coach_home'
    if user.is_staff:
        return 'scheduling:admin_home'
    return 'scheduling:dashboard'


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
            auth_login(request, user)
            messages.success(request, 'Account created successfully.')
            return redirect(_post_login_route_for(user))
    else:
        form = SignUpForm(initial={'role': 'player'})

    return render(request, 'scheduling/signup.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_route_for(request.user))

    if request.method == 'POST':
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
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
    context = {
        'player': player,
        'welcome_name': player.name,
        'next_session': next_session,
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
def tryout_list(request):
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
def admin_home(request):
    if not request.user.is_staff:
        messages.info(request, 'This page is currently available only for admin accounts.')
        return redirect('scheduling:dashboard')

    welcome_name = request.user.first_name or request.user.username
    context = {
        'welcome_name': welcome_name,
        'active_players': Player.objects.filter(role=Player.Role.PLAYER, is_active=True).count(),
        'coach_count': Player.objects.filter(role=Player.Role.COACH, is_active=True).count(),
        'open_tryouts': TryoutSession.objects.filter(registration_open=True).count(),
        'session_count': TrainingSession.objects.count(),
        'notification_count': Notification.objects.count(),
        'poll_count': SessionVotePoll.objects.count(),
    }
    return render(request, 'scheduling/admin_home.html', context)


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


def create_session(request):
    if request.method == 'POST':
        form = TrainingSessionForm(request.POST)
        if form.is_valid():
            session = form.save()
            messages.success(request, 'Training session created.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        form = TrainingSessionForm()

    return render(request, 'scheduling/create_session.html', {'form': form})


def edit_session(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)

    if request.method == 'POST':
        form = TrainingSessionForm(request.POST, instance=session)
        if form.is_valid():
            session = form.save()
            player_recipients = list(Player.objects.filter(role=Player.Role.PLAYER))
            Notification.objects.bulk_create(
                [
                    Notification(
                        recipient=player,
                        title='Session Updated',
                        message=f'{session.title} was updated for {session.starts_at} at {session.location}.',
                        notification_type=Notification.Type.SESSION_UPDATED,
                    )
                    for player in player_recipients
                ]
            )
            messages.success(request, 'Training session updated.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        form = TrainingSessionForm(instance=session)

    return render(request, 'scheduling/edit_session.html', {'form': form, 'session': session})


def cancel_session(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)

    if request.method == 'POST':
        session.cancelled = True
        session.save(update_fields=['cancelled'])
        messages.success(request, 'Training session cancelled.')
        return redirect('scheduling:session_detail', session_id=session.id)

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
    profile = getattr(request.user, 'player_profile', None)
    can_add_sessions = request.user.is_staff or (
        profile is not None and profile.role == Player.Role.COACH
    )

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
    }

    if request.method == 'POST':
        if action == 'rsvp':
            session_id = request.POST.get('session_id')
            rsvp_status = request.POST.get('rsvp_status')
            if profile is None:
                messages.error(request, 'This account cannot RSVP because it is not linked to a player profile.')
            elif rsvp_status not in {SessionRSVP.Status.GOING, SessionRSVP.Status.NOT_GOING}:
                messages.error(request, 'Invalid RSVP action.')
            else:
                target_session = TrainingSession.objects.filter(pk=session_id, cancelled=False).first()
                if target_session is None:
                    messages.error(request, 'Session is no longer available for RSVP.')
                else:
                    SessionRSVP.objects.update_or_create(
                        session=target_session,
                        player=profile,
                        defaults={'status': rsvp_status},
                    )
                    messages.success(request, 'RSVP updated.')
            return redirect(selected_query)

        if action == 'quick_add':
            if not can_add_sessions:
                messages.error(request, 'Only coach and admin accounts can add sessions.')
            else:
                title = quick_add['title']
                location = quick_add['location']
                start_time_raw = quick_add['start_time']
                end_time_raw = quick_add['end_time']

                if not title or not location or not start_time_raw or not end_time_raw:
                    messages.error(request, 'Please fill in session name, start time, end time, and location.')
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
                            TrainingSession.objects.create(
                                title=title,
                                starts_at=starts_at_local,
                                ends_at=ends_at_local,
                                location=location,
                                session_type=TrainingSession.SessionType.PRACTICE,
                                notes='Calendar quick-add.',
                            )
                            messages.success(request, 'Session added to the schedule.')
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

    sessions_by_day = {}
    for training_session in month_sessions:
        local_starts = timezone.localtime(training_session.starts_at, local_tz)
        day_key = local_starts.date()
        sessions_by_day.setdefault(day_key, []).append(training_session)

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
    for training_session in selected_day_sessions:
        local_start = timezone.localtime(training_session.starts_at, local_tz)
        local_end = timezone.localtime(training_session.ends_at, local_tz)
        start_minutes = int((local_start.hour - timeline_start_hour) * 60 + local_start.minute)
        end_minutes = int((local_end.hour - timeline_start_hour) * 60 + local_end.minute)
        clipped_start = max(0, start_minutes)
        clipped_end = min(timeline_total_minutes, end_minutes)
        if clipped_end <= 0 or clipped_start >= timeline_total_minutes:
            continue

        raw_timeline_events.append(
            {
                'id': training_session.id,
                'title': training_session.title,
                'location': training_session.location,
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
        'active_nav': 'schedule',
    }
    return render(request, 'scheduling/sessions_calendar.html', context)


def session_detail(request, session_id):
    session = get_object_or_404(
        TrainingSession.objects.annotate(
            going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.GOING)),
            not_going_count=Count('rsvps', filter=Q(rsvps__status=SessionRSVP.Status.NOT_GOING)),
        ),
        pk=session_id,
    )

    if request.method == 'POST':
        form = SessionRSVPForm(request.POST)
        if form.is_valid():
            SessionRSVP.objects.update_or_create(
                session=session,
                player=form.cleaned_data['player'],
                defaults={'status': form.cleaned_data['status']},
            )
            messages.success(request, 'RSVP saved.')
            return redirect('scheduling:session_detail', session_id=session.id)
    else:
        form = SessionRSVPForm()

    rsvps = list(session.rsvps.select_related('player'))
    rsvp_by_player_id = {rsvp.player_id: rsvp for rsvp in rsvps}
    active_players = list(
        Player.objects.filter(role=Player.Role.PLAYER, is_active=True).order_by('name')
    )

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
                'status_text': 'Available' if is_available else 'On Break',
                'status_class': 'is-available' if is_available else 'is-on-break',
            }
        )

    user_profile = getattr(request.user, 'player_profile', None)
    personal_note_preview = None
    if user_profile is not None:
        personal_note_preview = session.personal_notes.filter(player=user_profile).first()

    local_starts = timezone.localtime(session.starts_at)
    calendar_back_url = (
        f"{reverse('scheduling:sessions_calendar')}"
        f"?year={local_starts.year}&month={local_starts.month}&day={local_starts.day}"
    )

    session_plan = getattr(session, 'plan', None)
    return render(
        request,
        'scheduling/session_detail.html',
        {
            'session': session,
            'form': form,
            'rsvps': rsvps,
            'participant_rows': participant_rows[:5],
            'available_rows': available_rows[:5],
            'personal_note_preview': personal_note_preview,
            'user_profile': user_profile,
            'can_edit_personal_note': user_profile is not None and user_profile.role == Player.Role.PLAYER,
            'calendar_back_url': calendar_back_url,
            'session_plan': session_plan,
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
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    if not request.user.is_staff and not is_coach:
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

    if request.method == 'POST':
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
        },
    )


def polls_list(request):
    polls = SessionVotePoll.objects.annotate(vote_count=Count('votes')).order_by('-created_at')
    profile = getattr(request.user, 'player_profile', None)
    can_create_poll = request.user.is_staff or (
        profile is not None and profile.role == Player.Role.COACH
    )
    return render(request, 'scheduling/polls_list.html', {'polls': polls, 'can_create_poll': can_create_poll})


def edit_session_plan(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)
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
        home_url = 'scheduling:player_home' if profile.role == Player.Role.PLAYER else 'scheduling:coach_home'
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
    coach = getattr(request.user, 'player_profile', None)
    if coach is None or coach.role != Player.Role.COACH:
        messages.info(request, 'This page is currently available only for coach accounts.')
        return redirect('scheduling:dashboard')

    if request.method == 'POST':
        form = TryoutSessionForm(request.POST)
        if form.is_valid():
            tryout_session = form.save()
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


def tryout_candidate_detail(request, candidate_id):
    candidate = get_object_or_404(TryoutCandidate.objects.select_related('tryout_session'), pk=candidate_id)
    return render(request, 'scheduling/tryout_candidate_detail.html', {'candidate': candidate})


def convert_tryout_candidate(request, candidate_id):
    candidate = get_object_or_404(TryoutCandidate.objects.select_related('tryout_session'), pk=candidate_id)

    if request.method == 'POST' and candidate.status != TryoutCandidate.Status.CONVERTED:
        Player.objects.get_or_create(
            email=candidate.email,
            defaults={'name': candidate.name, 'role': Player.Role.PLAYER},
        )
        candidate.status = TryoutCandidate.Status.CONVERTED
        candidate.save(update_fields=['status'])
        messages.success(request, 'Candidate converted to player.')
        return redirect('scheduling:tryout_candidate_detail', candidate_id=candidate.id)

    return render(request, 'scheduling/convert_tryout_candidate.html', {'candidate': candidate})


def player_status_list(request):
    players = Player.objects.filter(role=Player.Role.PLAYER)
    coaches = Player.objects.filter(role=Player.Role.COACH)
    return render(request, 'scheduling/player_status_list.html', {'players': players, 'coaches': coaches})


def eligible_players(request):
    players = Player.objects.filter(
        role=Player.Role.PLAYER,
        is_active=True,
        status=Player.Status.ELIGIBLE,
    )
    return render(request, 'scheduling/eligible_players.html', {'players': players})


def update_player_status(request, player_id):
    player = get_object_or_404(Player, pk=player_id)

    if request.method == 'POST':
        form = PlayerUpdateForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            messages.success(request, 'Player updated.')
            return redirect('scheduling:player_status_list')
    else:
        form = PlayerUpdateForm(instance=player)

    return render(request, 'scheduling/update_player_status.html', {'form': form, 'player': player})


def deactivate_player(request, player_id):
    player = get_object_or_404(Player, pk=player_id, role=Player.Role.PLAYER)

    if request.method == 'POST':
        player.is_active = False
        player.save(update_fields=['is_active'])
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


def deactivate_coach(request, coach_id):
    coach = get_object_or_404(Player, pk=coach_id, role=Player.Role.COACH)

    if request.method == 'POST':
        coach.is_active = False
        coach.save(update_fields=['is_active'])
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
    if not request.user.is_staff and not is_coach:
        return redirect('scheduling:player_home')

    matches = Match.objects.all()
    total_wins = sum(1 for m in matches if m.result == Match.Result.WIN)
    total_losses = sum(1 for m in matches if m.result == Match.Result.LOSS)
    total_draws = sum(1 for m in matches if m.result == Match.Result.DRAW)

    total_players = Player.objects.filter(role=Player.Role.PLAYER).count()
    recovering_players = Player.objects.filter(role=Player.Role.PLAYER, status=Player.Status.RECOVERING).count()
    injured_players = Player.objects.filter(role=Player.Role.PLAYER, status=Player.Status.INJURED).count()
    non_eligible = recovering_players + injured_players
    recovery_pct = round(((total_players - non_eligible) / total_players) * 100) if total_players else 0

    top_scorers = (
        PlayerMatchStat.objects
        .values('player__id', 'player__name')
        .annotate(total_goals=Sum('goals'))
        .filter(total_goals__gt=0)
        .order_by('-total_goals')[:5]
    )
    top_defenders = (
        PlayerMatchStat.objects
        .values('player__id', 'player__name')
        .annotate(total_interceptions=Sum('interceptions'))
        .filter(total_interceptions__gt=0)
        .order_by('-total_interceptions')[:5]
    )

    goals_per_game = list(
        Match.objects.order_by('date').values_list('opponent', 'goals_for')
    )

    team_goals = TeamGoal.objects.all()

    players = Player.objects.filter(role=Player.Role.PLAYER, is_active=True)

    import json
    chart_labels = json.dumps([g[0] for g in goals_per_game])
    chart_data = json.dumps([g[1] for g in goals_per_game])

    context = {
        'total_wins': total_wins,
        'total_losses': total_losses,
        'total_draws': total_draws,
        'recovery_pct': recovery_pct,
        'top_scorers': top_scorers,
        'top_defenders': top_defenders,
        'team_goals': team_goals,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'match_count': matches.count(),
        'players': players,
    }
    return render(request, 'scheduling/team_stats.html', context)


@login_required(login_url='scheduling:login')
def player_stats_detail(request, player_id):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    is_player = profile is not None and profile.role == Player.Role.PLAYER

    if request.user.is_staff or is_coach:
        player = get_object_or_404(Player, pk=player_id)
    elif is_player and profile.id == player_id:
        player = profile
    else:
        messages.error(request, 'You can only view your own stats page.')
        return redirect('scheduling:player_home' if is_player else 'scheduling:dashboard')

    stats = PlayerMatchStat.objects.filter(player=player).select_related('match').order_by('-match__date')

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

    latest_injury = ''
    for s in stats:
        if s.most_recent_injury:
            latest_injury = s.most_recent_injury
            break

    stats_by_game = list(
        PlayerMatchStat.objects
        .filter(player=player)
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

    context = {
        'player': player,
        'stats': stats,
        'totals': totals,
        'latest_injury': latest_injury,
        'matches_played': stats.count(),
        'can_view_team_dashboard': request.user.is_staff or is_coach,
        'game_labels': game_labels,
        'aces_series': aces_series,
        'returns_series': returns_series,
        'blocks_series': blocks_series,
        'interceptions_series': interceptions_series,
        'points_series': points_series,
        'histogram_labels': histogram_labels,
        'histogram_data': histogram_data,
    }
    return render(request, 'scheduling/player_stats_detail.html', context)


@login_required(login_url='scheduling:login')
def record_match(request):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    if not request.user.is_staff and not is_coach:
        return redirect('scheduling:player_home')

    if request.method == 'POST':
        form = MatchForm(request.POST)
        if form.is_valid():
            match = form.save()
            messages.success(request, 'Match recorded.')
            return redirect('scheduling:record_player_stats', match_id=match.id)
    else:
        form = MatchForm()
    return render(request, 'scheduling/record_match.html', {'form': form})


@login_required(login_url='scheduling:login')
def record_player_stats(request, match_id):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    if not request.user.is_staff and not is_coach:
        return redirect('scheduling:player_home')

    match = get_object_or_404(Match, pk=match_id)
    existing_stats = list(match.player_stats.select_related('player'))

    if request.method == 'POST':
        form = PlayerMatchStatForm(request.POST)
        if form.is_valid():
            stat = form.save(commit=False)
            stat.match = match
            stat.save()
            messages.success(request, f'Stats for {stat.player.name} saved.')
            return redirect('scheduling:record_player_stats', match_id=match.id)
    else:
        form = PlayerMatchStatForm()

    return render(request, 'scheduling/record_player_stats.html', {
        'form': form,
        'match': match,
        'existing_stats': existing_stats,
    })


@login_required(login_url='scheduling:login')
def add_team_goal(request):
    profile = getattr(request.user, 'player_profile', None)
    is_coach = profile is not None and profile.role == Player.Role.COACH
    if not request.user.is_staff and not is_coach:
        return redirect('scheduling:player_home')

    if request.method == 'POST':
        form = TeamGoalForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Team goal added.')
            return redirect('scheduling:team_stats')
    else:
        form = TeamGoalForm()
    return render(request, 'scheduling/add_team_goal.html', {'form': form})
