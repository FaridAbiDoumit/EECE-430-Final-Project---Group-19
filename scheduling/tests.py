from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Player, SessionRSVP, TrainingSession


class SchedulingViewsTests(TestCase):
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
