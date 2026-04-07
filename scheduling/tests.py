from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Notification,
    Player,
    PlayerAvailability,
    PersonalSessionNote,
    SessionRSVP,
    SessionPlan,
    SessionVote,
    SessionVotePoll,
    TrainingSession,
)


class SchedulingViewsTests(TestCase):
    def test_edit_session_creates_notifications_for_players(self):
        Player.objects.create(name='Player One', email='player1@example.com')
        Player.objects.create(name='Player Two', email='player2@example.com')
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
        self.assertEqual(Notification.objects.count(), 2)

    def test_delete_notification_removes_notification(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')
        notification = Notification.objects.create(
            recipient=player,
            title='Session Updated',
            message='Practice moved to Court B',
        )

        response = self.client.post(reverse('scheduling:delete_notification', args=[notification.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())

    def test_edit_session_plan_creates_plan(self):
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=timezone.now() + timedelta(days=1),
            location='Main Gym',
        )

        response = self.client.post(
            reverse('scheduling:edit_session_plan', args=[session.id]),
            data={'title': 'Warmup Plan', 'drills': 'Stretching\nServing\nScrimmage'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(SessionPlan.objects.filter(session=session, title='Warmup Plan').exists())

    def test_personal_note_updates_existing_note(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=timezone.now() + timedelta(days=1),
            location='Main Gym',
        )
        PersonalSessionNote.objects.create(session=session, player=player, content='Bring water')

        response = self.client.post(
            reverse('scheduling:personal_note', args=[session.id]),
            data={'player': player.id, 'content': 'Bring water and knee pads'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(session.personal_notes.count(), 1)
        self.assertEqual(session.personal_notes.get().content, 'Bring water and knee pads')

    def test_create_vote_poll_creates_two_options(self):
        response = self.client.post(
            reverse('scheduling:create_vote_poll'),
            data={
                'title': 'Wednesday Practice Vote',
                'description': 'Pick the better slot',
                'closes_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'option_1_starts_at': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'option_1_location': 'Court A',
                'option_2_starts_at': (timezone.now() + timedelta(days=4)).strftime('%Y-%m-%dT%H:%M'),
                'option_2_location': 'Court B',
            },
        )

        self.assertEqual(response.status_code, 302)
        poll = SessionVotePoll.objects.get()
        self.assertEqual(poll.options.count(), 2)

    def test_vote_poll_updates_existing_player_vote(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')
        poll = SessionVotePoll.objects.create(
            title='Wednesday Practice Vote',
            closes_at=timezone.now() + timedelta(days=2),
        )
        option_1 = poll.options.create(starts_at=timezone.now() + timedelta(days=3), location='Court A')
        option_2 = poll.options.create(starts_at=timezone.now() + timedelta(days=4), location='Court B')
        SessionVote.objects.create(poll=poll, option=option_1, player=player)

        response = self.client.post(
            reverse('scheduling:vote_poll_detail', args=[poll.id]),
            data={'player': player.id, 'option': option_2.id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SessionVote.objects.count(), 1)
        self.assertEqual(SessionVote.objects.get().option, option_2)

    def test_submit_availability_creates_slot(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')

        response = self.client.post(
            reverse('scheduling:submit_availability'),
            data={
                'player': player.id,
                'weekday': PlayerAvailability.Weekday.MONDAY,
                'start_time': '18:00',
                'end_time': '20:00',
                'notes': 'After work',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlayerAvailability.objects.count(), 1)
        slot = PlayerAvailability.objects.get()
        self.assertEqual(slot.player, player)
        self.assertEqual(slot.weekday, PlayerAvailability.Weekday.MONDAY)

    def test_submit_availability_rejects_invalid_time_range(self):
        player = Player.objects.create(name='Player One', email='player1@example.com')

        response = self.client.post(
            reverse('scheduling:submit_availability'),
            data={
                'player': player.id,
                'weekday': PlayerAvailability.Weekday.MONDAY,
                'start_time': '20:00',
                'end_time': '18:00',
                'notes': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlayerAvailability.objects.count(), 0)

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
