from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    PlayerAvailabilityForm,
    SessionRSVPForm,
    SessionVoteForm,
    SessionVotePollForm,
    TrainingSessionForm,
)
from .models import (
    PlayerAvailability,
    SessionRSVP,
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
            form.save()
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
    return render(
        request,
        'scheduling/session_detail.html',
        {
            'session': session,
            'form': form,
            'rsvps': rsvps,
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
