from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    PlayerAvailabilityForm,
    PersonalSessionNoteForm,
    SessionRSVPForm,
    SessionPlanForm,
    SessionVoteForm,
    SessionVotePollForm,
    TrainingSessionForm,
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
    TrainingSession,
)


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


def next_session(request):
    session = (
        TrainingSession.objects.filter(starts_at__gte=timezone.now(), cancelled=False)
        .order_by('starts_at')
        .first()
    )
    return render(request, 'scheduling/next_session.html', {'session': session})


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

    rsvps = session.rsvps.select_related('player')
    session_plan = getattr(session, 'plan', None)
    return render(
        request,
        'scheduling/session_detail.html',
        {
            'session': session,
            'form': form,
            'rsvps': rsvps,
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

    if request.method == 'POST':
        form = SessionVoteForm(request.POST, poll=poll)
        if form.is_valid():
            SessionVote.objects.update_or_create(
                poll=poll,
                player=form.cleaned_data['player'],
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
        },
    )


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


def personal_note(request, session_id):
    session = get_object_or_404(TrainingSession, pk=session_id)
    note = None

    if request.method == 'POST':
        player_id = request.POST.get('player')
        if player_id:
            note = PersonalSessionNote.objects.filter(session=session, player_id=player_id).first()
        form = PersonalSessionNoteForm(request.POST, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            note.session = session
            note.save()
            messages.success(request, 'Personal note saved.')
            return redirect('scheduling:personal_note', session_id=session.id)
    else:
        form = PersonalSessionNoteForm()

    existing_notes = session.personal_notes.select_related('player')
    return render(
        request,
        'scheduling/personal_note.html',
        {
            'session': session,
            'form': form,
            'existing_notes': existing_notes,
        },
    )


def notification_inbox(request):
    notifications = Notification.objects.select_related('recipient')
    unread_ids = []
    for notification in notifications:
        if notification.read_at is None:
            unread_ids.append(notification.id)

    if unread_ids:
        Notification.objects.filter(id__in=unread_ids).update(read_at=timezone.now())
        notifications = Notification.objects.select_related('recipient')

    return render(request, 'scheduling/notification_inbox.html', {'notifications': notifications})


def delete_notification(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id)

    if request.method == 'POST':
        notification.delete()
        messages.success(request, 'Notification deleted.')
        return redirect('scheduling:notification_inbox')

    return render(request, 'scheduling/delete_notification.html', {'notification': notification})
