from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Player, SessionRSVP, TrainingSession


class SchedulingViewsTests(TestCase):
    def test_edit_session_updates_existing_session(self):
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=timezone.now() + timedelta(days=1),
            location='Main Gym',
        )

        response = self.client.post(
            reverse('scheduling:edit_session', args=[session.id]),
            data={
                'title': 'Updated Practice',
                'starts_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'location': 'Court B',
                'session_type': TrainingSession.SessionType.MATCH,
                'notes': 'Bring match jerseys',
            },
        )

        self.assertEqual(response.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.title, 'Updated Practice')
        self.assertEqual(session.location, 'Court B')
        self.assertEqual(session.session_type, TrainingSession.SessionType.MATCH)
        self.assertEqual(session.notes, 'Bring match jerseys')

    def test_cancel_session_marks_session_as_cancelled(self):
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=timezone.now() + timedelta(days=1),
            location='Main Gym',
        )

        response = self.client.post(reverse('scheduling:cancel_session', args=[session.id]))

        self.assertEqual(response.status_code, 302)
        session.refresh_from_db()
        self.assertTrue(session.cancelled)

    def test_next_session_shows_earliest_upcoming_session(self):
        TrainingSession.objects.create(
            title='Later Session',
            starts_at=timezone.now() + timedelta(days=2),
            location='Court B',
        )
        earliest = TrainingSession.objects.create(
            title='Earlier Session',
            starts_at=timezone.now() + timedelta(hours=3),
            location='Court A',
        )

        response = self.client.get(reverse('scheduling:next_session'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['session'], earliest)

    def test_session_detail_updates_existing_rsvp(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=timezone.now() + timedelta(days=1),
            location='Main Gym',
        )
        SessionRSVP.objects.create(session=session, player=player, status=SessionRSVP.Status.GOING)

        response = self.client.post(
            reverse('scheduling:session_detail', args=[session.id]),
            data={'player': player.id, 'status': SessionRSVP.Status.NOT_GOING},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(session.rsvps.count(), 1)
        self.assertEqual(session.rsvps.get().status, SessionRSVP.Status.NOT_GOING)
