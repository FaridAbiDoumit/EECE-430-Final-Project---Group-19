from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import PlayerAvailabilityForm, SessionRSVPForm, TrainingSessionForm
from .models import PlayerAvailability, SessionRSVP, TrainingSession


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
