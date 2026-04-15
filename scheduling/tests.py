from datetime import timedelta

from django.contrib.auth import get_user_model
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
    TryoutCandidate,
    TryoutSession,
    TrainingSession,
)


User = get_user_model()


class SchedulingViewsTests(TestCase):
    def test_signup_creates_player_profile_and_logs_user_in(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'New Player',
                'email': 'newplayer@example.com',
                'password': 'strong-pass-123',
                'role': 'player',
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newplayer@example.com')
        player = Player.objects.get(email='newplayer@example.com')
        self.assertEqual(player.user, user)
        self.assertEqual(player.role, Player.Role.PLAYER)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.id))

    def test_signup_creates_staff_user_for_admin_role(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Admin User',
                'email': 'admin@example.com',
                'password': 'strong-pass-123',
                'role': 'admin',
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='admin@example.com')
        self.assertTrue(user.is_staff)
        self.assertFalse(Player.objects.filter(email='admin@example.com').exists())

    def test_login_view_authenticates_with_email(self):
        user = User.objects.create_user(
            username='member@example.com',
            email='member@example.com',
            password='strong-pass-123',
        )

        response = self.client.post(
            reverse('scheduling:login'),
            data={'username': 'member@example.com', 'password': 'strong-pass-123'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.id))

    def test_inactive_player_cannot_log_in(self):
        user = User.objects.create_user(
            username='inactive-login@example.com',
            email='inactive-login@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Inactive Login',
            email='inactive-login@example.com',
            role=Player.Role.PLAYER,
            is_active=False,
        )

        response = self.client.post(
            reverse('scheduling:login'),
            data={'username': 'inactive-login@example.com', 'password': 'strong-pass-123'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertContains(response, 'deactivated')

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user(
            username='duplicate@example.com',
            email='duplicate@example.com',
            password='strong-pass-123',
        )

        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Duplicate User',
                'email': 'duplicate@example.com',
                'password': 'strong-pass-123',
                'role': 'coach',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'An account with this email already exists.')

    def test_root_landing_page_shows_login_and_register_options(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Login')
        self.assertContains(response, 'Register')
        self.assertNotContains(response, 'Upcoming Session')

    def test_root_redirects_authenticated_user_to_role_home(self):
        user = User.objects.create_user(
            username='landingplayer@example.com',
            email='landingplayer@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Landing Player',
            email='landingplayer@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(user)
        response = self.client.get('/')

        self.assertRedirects(response, reverse('scheduling:player_home'))

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('scheduling:dashboard'))

        self.assertRedirects(response, f"{reverse('scheduling:login')}?next={reverse('scheduling:dashboard')}")

    def test_player_signup_redirects_to_player_home(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Player Home',
                'email': 'playerhome@example.com',
                'password': 'strong-pass-123',
                'role': 'player',
            },
        )

        self.assertRedirects(response, reverse('scheduling:player_home'))

    def test_player_home_requires_logged_in_player_and_shows_name(self):
        user = User.objects.create_user(
            username='playerview@example.com',
            email='playerview@example.com',
            password='strong-pass-123',
            first_name='Player View',
        )
        Player.objects.create(
            user=user,
            name='Player View',
            email='playerview@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:player_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Player View!')
        self.assertContains(response, 'My personal stats')
        self.assertContains(response, 'My calendar and schedules')

    def test_non_player_is_redirected_away_from_player_home(self):
        user = User.objects.create_user(
            username='coachview@example.com',
            email='coachview@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Coach View',
            email='coachview@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:player_home'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_coach_signup_redirects_to_coach_home(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Coach Home',
                'email': 'coachhome@example.com',
                'password': 'strong-pass-123',
                'role': 'coach',
            },
        )

        self.assertRedirects(response, reverse('scheduling:coach_home'))

    def test_coach_home_requires_logged_in_coach_and_shows_name(self):
        user = User.objects.create_user(
            username='coachdashboard@example.com',
            email='coachdashboard@example.com',
            password='strong-pass-123',
            first_name='Coach View',
        )
        Player.objects.create(
            user=user,
            name='Coach View',
            email='coachdashboard@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:coach_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Coach View!')
        self.assertContains(response, 'Tryouts')
        self.assertContains(response, 'Dashboard')

    def test_non_coach_is_redirected_away_from_coach_home(self):
        user = User.objects.create_user(
            username='playerview@example.com',
            email='playerview@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Player Redirect',
            email='playerview@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:coach_home'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_admin_signup_redirects_to_admin_home(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Admin Home',
                'email': 'adminhome@example.com',
                'password': 'strong-pass-123',
                'role': 'admin',
            },
        )

        self.assertRedirects(response, reverse('scheduling:admin_home'))

    def test_admin_home_requires_staff_user_and_shows_name(self):
        user = User.objects.create_user(
            username='adminview@example.com',
            email='adminview@example.com',
            password='strong-pass-123',
            first_name='Admin View',
            is_staff=True,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:admin_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Admin View!')
        self.assertContains(response, 'User management')
        self.assertContains(response, 'System dashboard')

    def test_team_stats_home_link_targets_admin_home_for_staff_user(self):
        user = User.objects.create_user(
            username='adminstats@example.com',
            email='adminstats@example.com',
            password='strong-pass-123',
            is_staff=True,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:team_stats'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("scheduling:admin_home")}"')

    def test_admin_home_hides_scheduling_ai_and_tryout_buttons(self):
        user = User.objects.create_user(
            username='restrictedadmin@example.com',
            email='restrictedadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:admin_home'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Scheduling')
        self.assertNotContains(response, 'AI Analytics')
        self.assertNotContains(response, 'Tryouts')

    def test_admin_cannot_access_schedule_ai_or_tryout_pages(self):
        user = User.objects.create_user(
            username='hubadmin@example.com',
            email='hubadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )

        self.client.force_login(user)
        for route_name in [
            'scheduling:create_session',
            'scheduling:sessions_calendar',
            'scheduling:ai_analytics_hub',
            'scheduling:create_tryout_session',
            'scheduling:tryout_list',
        ]:
            response = self.client.get(reverse(route_name))
            self.assertRedirects(response, reverse('scheduling:admin_home'))

    def test_manage_coach_detail_shows_only_primary_actions(self):
        admin = User.objects.create_user(
            username='coachadmin@example.com',
            email='coachadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        coach = Player.objects.create(
            name='Coach Clean',
            email='coachclean@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(admin)
        response = self.client.get(reverse('scheduling:manage_coach_detail', args=[coach.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Details')
        self.assertNotContains(response, 'Chat With Coach')
        self.assertNotContains(response, 'Support')

    def test_non_admin_is_redirected_away_from_admin_home(self):
        user = User.objects.create_user(
            username='regular@example.com',
            email='regular@example.com',
            password='strong-pass-123',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:admin_home'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_deactivate_player_sets_player_inactive(self):
        admin = User.objects.create_user(
            username='deactivateadmin@example.com',
            email='deactivateadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        linked_user = User.objects.create_user(
            username='player1@example.com',
            email='player1@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=linked_user,
            name='Player One',
            email='player1@example.com',
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('scheduling:deactivate_player', args=[player.id]))

        self.assertEqual(response.status_code, 302)
        player.refresh_from_db()
        linked_user.refresh_from_db()
        self.assertFalse(player.is_active)
        self.assertFalse(linked_user.is_active)

    def test_admin_can_reactivate_deactivated_player(self):
        admin = User.objects.create_user(
            username='reactivateadmin@example.com',
            email='reactivateadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        linked_user = User.objects.create_user(
            username='inactiveplayer@example.com',
            email='inactiveplayer@example.com',
            password='strong-pass-123',
            is_active=False,
        )
        player = Player.objects.create(
            user=linked_user,
            name='Inactive Player',
            email='inactiveplayer@example.com',
            is_active=False,
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('scheduling:activate_player', args=[player.id]))

        self.assertEqual(response.status_code, 302)
        player.refresh_from_db()
        linked_user.refresh_from_db()
        self.assertTrue(player.is_active)
        self.assertTrue(linked_user.is_active)

    def test_edit_player_screen_removes_active_checkbox(self):
        admin = User.objects.create_user(
            username='editplayeradmin@example.com',
            email='editplayeradmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        player = Player.objects.create(name='Edit Player', email='editplayer@example.com')

        self.client.force_login(admin)
        response = self.client.get(reverse('scheduling:update_player_status', args=[player.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Active account')
        self.assertContains(response, 'Deactivate Player Profile')

    def test_inactive_player_is_logged_out_on_next_request(self):
        user = User.objects.create_user(
            username='inactive-session@example.com',
            email='inactive-session@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Inactive Session',
            email='inactive-session@example.com',
            role=Player.Role.PLAYER,
            is_active=False,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:player_home'))

        self.assertRedirects(response, reverse('scheduling:login'))
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertFalse(player.is_active)

    def test_deactivate_coach_sets_coach_inactive(self):
        admin = User.objects.create_user(
            username='deactivatecoachadmin@example.com',
            email='deactivatecoachadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        coach_user = User.objects.create_user(
            username='coach1@example.com',
            email='coach1@example.com',
            password='strong-pass-123',
        )
        coach = Player.objects.create(
            user=coach_user,
            name='Coach One',
            email='coach1@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('scheduling:deactivate_coach', args=[coach.id]))

        self.assertEqual(response.status_code, 302)
        coach.refresh_from_db()
        coach_user.refresh_from_db()
        self.assertFalse(coach.is_active)
        self.assertFalse(coach_user.is_active)

    def test_eligible_players_only_shows_active_eligible_players(self):
        eligible = Player.objects.create(name='Eligible Player', email='eligible@example.com')
        Player.objects.create(
            name='Injured Player',
            email='injured@example.com',
            status=Player.Status.INJURED,
        )
        Player.objects.create(
            name='Inactive Player',
            email='inactive@example.com',
            is_active=False,
        )

        response = self.client.get(reverse('scheduling:eligible_players'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, eligible.name)
        self.assertNotContains(response, 'Injured Player')
        self.assertNotContains(response, 'Inactive Player')

    def test_tryouts_index_requires_logged_in_coach(self):
        response = self.client.get(reverse('scheduling:tryout_list'))

        self.assertRedirects(response, f"{reverse('scheduling:login')}?next={reverse('scheduling:tryout_list')}")

    def test_tryouts_index_shows_tryouts_for_coach(self):
        user = User.objects.create_user(
            username='tryoutcoach@example.com',
            email='tryoutcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Tryout Coach',
            email='tryoutcoach@example.com',
            role=Player.Role.COACH,
        )
        first_tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
        )
        second_tryout = TryoutSession.objects.create(
            title='Junior Tryout',
            starts_at=timezone.now() + timedelta(days=8),
            location='Court A',
            registration_open=False,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:tryout_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Current Tryouts')
        self.assertContains(response, first_tryout.title)
        self.assertContains(response, second_tryout.title)
        self.assertContains(response, 'Create Tryout')
        self.assertContains(response, reverse('scheduling:tryout_session_detail', args=[first_tryout.id]))

    def test_non_coach_is_redirected_away_from_tryouts_index(self):
        user = User.objects.create_user(
            username='notcoach@example.com',
            email='notcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Not Coach',
            email='notcoach@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:tryout_list'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_create_tryout_session_requires_logged_in_coach(self):
        response = self.client.get(reverse('scheduling:create_tryout_session'))

        self.assertRedirects(response, f"{reverse('scheduling:login')}?next={reverse('scheduling:create_tryout_session')}")

    def test_create_tryout_session_creates_record_with_saved_details(self):
        user = User.objects.create_user(
            username='createtryoutcoach@example.com',
            email='createtryoutcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Create Tryout Coach',
            email='createtryoutcoach@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(user)
        response = self.client.post(
            reverse('scheduling:create_tryout_session'),
            data={
                'title': 'Open Tryout',
                'starts_at': (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
                'location': 'Court C',
                'description': 'Bring sportswear and arrive 15 minutes early.',
                'registration_open': True,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(TryoutSession.objects.count(), 1)
        self.assertEqual(
            TryoutSession.objects.get().description,
            'Bring sportswear and arrive 15 minutes early.',
        )

    def test_tryout_detail_requires_logged_in_coach(self):
        tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
        )

        response = self.client.get(reverse('scheduling:tryout_session_detail', args=[tryout.id]))

        self.assertRedirects(
            response,
            f"{reverse('scheduling:login')}?next={reverse('scheduling:tryout_session_detail', args=[tryout.id])}",
        )

    def test_tryout_detail_shows_tryout_info_and_candidates_for_coach(self):
        user = User.objects.create_user(
            username='detailcoach@example.com',
            email='detailcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Detail Coach',
            email='detailcoach@example.com',
            role=Player.Role.COACH,
        )
        tryout = TryoutSession.objects.create(
            title='Elite Tryout',
            starts_at=timezone.now() + timedelta(days=7),
            location='Court B',
        )
        candidate = TryoutCandidate.objects.create(
            tryout_session=tryout,
            name='Candidate One',
            email='candidate1@example.com',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:tryout_session_detail', args=[tryout.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tryout Details')
        self.assertContains(response, tryout.title)
        self.assertContains(response, candidate.name)
        self.assertContains(response, 'More Details')

    def test_non_coach_is_redirected_away_from_tryout_detail(self):
        user = User.objects.create_user(
            username='detailplayer@example.com',
            email='detailplayer@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Detail Player',
            email='detailplayer@example.com',
            role=Player.Role.PLAYER,
        )
        tryout = TryoutSession.objects.create(
            title='Elite Tryout',
            starts_at=timezone.now() + timedelta(days=7),
            location='Court B',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:tryout_session_detail', args=[tryout.id]))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_register_tryout_candidate_page_shows_tryout_details(self):
        tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
            description='Bring sportswear and arrive 15 minutes early.',
        )

        response = self.client.get(reverse('scheduling:register_tryout_candidate'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, tryout.title)
        self.assertContains(response, 'Bring sportswear and arrive 15 minutes early.')

    def test_register_tryout_candidate_creates_candidate(self):
        tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
            description='Bring sportswear and arrive 15 minutes early.',
        )

        response = self.client.post(
            reverse('scheduling:register_tryout_candidate'),
            data={
                'tryout_session': tryout.id,
                'name': 'Candidate One',
                'email': 'candidate1@example.com',
                'notes': 'Outside hitter',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(TryoutCandidate.objects.count(), 1)

    def test_convert_tryout_candidate_creates_player(self):
        tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
        )
        candidate = TryoutCandidate.objects.create(
            tryout_session=tryout,
            name='Candidate One',
            email='candidate1@example.com',
        )

        response = self.client.post(reverse('scheduling:convert_tryout_candidate', args=[candidate.id]))

        self.assertEqual(response.status_code, 302)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, TryoutCandidate.Status.CONVERTED)
        self.assertTrue(Player.objects.filter(email='candidate1@example.com').exists())

    def test_edit_session_creates_notifications_for_players(self):
        admin = User.objects.create_user(
            username='editadmin@example.com',
            email='editadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        Player.objects.create(name='Player One', email='player1@example.com')
        Player.objects.create(name='Player Two', email='player2@example.com')
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session', args=[session.id]),
            data={
                'title': 'Updated Practice',
                'starts_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (timezone.now() + timedelta(days=2, hours=2)).strftime('%Y-%m-%dT%H:%M'),
                'location': 'Court B',
                'session_type': TrainingSession.SessionType.MATCH,
                'notes': 'Bring match jerseys',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Notification.objects.count(), 2)

    def test_notification_inbox_requires_login(self):
        response = self.client.get(reverse('scheduling:notification_inbox'))

        self.assertRedirects(response, f"{reverse('scheduling:login')}?next={reverse('scheduling:notification_inbox')}")

    def test_player_notification_inbox_only_shows_their_notifications(self):
        user = User.objects.create_user(
            username='notifyplayer@example.com',
            email='notifyplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Notify Player',
            email='notifyplayer@example.com',
            role=Player.Role.PLAYER,
        )
        other = Player.objects.create(name='Other Player', email='othernotify@example.com')
        Notification.objects.create(recipient=player, title='Mine', message='Visible to me')
        Notification.objects.create(recipient=other, title='Other', message='Should be hidden')

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:notification_inbox'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mine')
        self.assertNotContains(response, 'Other')
        self.assertIsNotNone(Notification.objects.get(recipient=player, title='Mine').read_at)

    def test_admin_notification_inbox_can_see_all_notifications(self):
        admin = User.objects.create_user(
            username='notifyadmin@example.com',
            email='notifyadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        first = Player.objects.create(name='Player One', email='player1@example.com')
        second = Player.objects.create(name='Player Two', email='player2@example.com')
        Notification.objects.create(recipient=first, title='First Notice', message='One')
        Notification.objects.create(recipient=second, title='Second Notice', message='Two')

        self.client.force_login(admin)
        response = self.client.get(reverse('scheduling:notification_inbox'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'First Notice')
        self.assertContains(response, 'Second Notice')

    def test_delete_notification_removes_notification(self):
        user = User.objects.create_user(
            username='player1@example.com',
            email='player1@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(user=user, name='Player One', email='player1@example.com')
        notification = Notification.objects.create(
            recipient=player,
            title='Session Updated',
            message='Practice moved to Court B',
        )

        self.client.force_login(user)
        response = self.client.post(reverse('scheduling:delete_notification', args=[notification.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())

    def test_edit_session_plan_creates_plan(self):
        admin = User.objects.create_user(
            username='planadmin@example.com',
            email='planadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session_plan', args=[session.id]),
            data={'title': 'Warmup Plan', 'drills': 'Stretching\nServing\nScrimmage'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(SessionPlan.objects.filter(session=session, title='Warmup Plan').exists())

    def test_personal_note_updates_existing_note(self):
        user = User.objects.create_user(
            username='noteplayer@example.com',
            email='noteplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Player One',
            email='noteplayer@example.com',
            role=Player.Role.PLAYER,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )
        PersonalSessionNote.objects.create(session=session, player=player, content='Bring water')

        self.client.force_login(user)
        response = self.client.post(
            reverse('scheduling:personal_note', args=[session.id]),
            data={'player': player.id, 'content': 'Bring water and knee pads'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(session.personal_notes.count(), 1)
        self.assertEqual(session.personal_notes.get().content, 'Bring water and knee pads')

    def test_create_vote_poll_creates_two_options(self):
        coach_user = User.objects.create_user(
            username='pollcoach@example.com',
            email='pollcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Poll Coach',
            email='pollcoach@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(coach_user)
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
        user = User.objects.create_user(
            username='pollplayer@example.com',
            email='pollplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Player One',
            email='pollplayer@example.com',
            role=Player.Role.PLAYER,
        )
        poll = SessionVotePoll.objects.create(
            title='Wednesday Practice Vote',
            closes_at=timezone.now() + timedelta(days=2),
        )
        option_1 = poll.options.create(starts_at=timezone.now() + timedelta(days=3), location='Court A')
        option_2 = poll.options.create(starts_at=timezone.now() + timedelta(days=4), location='Court B')
        SessionVote.objects.create(poll=poll, option=option_1, player=player)

        self.client.force_login(user)
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
        admin = User.objects.create_user(
            username='updateadmin@example.com',
            email='updateadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session', args=[session.id]),
            data={
                'title': 'Updated Practice',
                'starts_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (timezone.now() + timedelta(days=2, hours=2)).strftime('%Y-%m-%dT%H:%M'),
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
        admin = User.objects.create_user(
            username='canceladmin@example.com',
            email='canceladmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('scheduling:cancel_session', args=[session.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TrainingSession.objects.filter(id=session.id).exists())

    def test_next_session_shows_earliest_upcoming_session(self):
        user = User.objects.create_user(
            username='nextsession@example.com',
            email='nextsession@example.com',
            password='strong-pass-123',
        )
        later_start = timezone.now() + timedelta(days=2)
        early_start = timezone.now() + timedelta(hours=3)
        TrainingSession.objects.create(
            title='Later Session',
            starts_at=later_start,
            ends_at=later_start + timedelta(hours=2),
            location='Court B',
        )
        earliest = TrainingSession.objects.create(
            title='Earlier Session',
            starts_at=early_start,
            ends_at=early_start + timedelta(hours=2),
            location='Court A',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:next_session'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['session'], earliest)

    def test_session_detail_updates_existing_rsvp(self):
        user = User.objects.create_user(
            username='detailplayer@example.com',
            email='detailplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Player One',
            email='detailplayer@example.com',
            role=Player.Role.PLAYER,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )
        SessionRSVP.objects.create(session=session, player=player, status=SessionRSVP.Status.GOING)

        self.client.force_login(user)
        response = self.client.post(
            reverse('scheduling:session_detail', args=[session.id]),
            data={'player': player.id, 'status': SessionRSVP.Status.NOT_GOING},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(session.rsvps.count(), 1)
        self.assertEqual(session.rsvps.get().status, SessionRSVP.Status.NOT_GOING)

    def test_player_session_detail_shows_only_player_actions(self):
        player_user = User.objects.create_user(
            username='sessionplayer@example.com',
            email='sessionplayer@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=player_user,
            name='Session Player',
            email='sessionplayer@example.com',
            role=Player.Role.PLAYER,
        )
        Player.objects.create(
            name='Session Coach',
            email='sessioncoach@example.com',
            role=Player.Role.COACH,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Player Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
            notes='Bring water and be on time.',
        )

        self.client.force_login(player_user)
        response = self.client.get(reverse('scheduling:session_detail', args=[session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My RSVP')
        self.assertContains(response, 'Personal Notes')
        self.assertNotContains(response, 'Edit Session')
        self.assertNotContains(response, 'Available Players')

    def test_player_cannot_edit_session_but_coach_can(self):
        player_user = User.objects.create_user(
            username='cannotedit@example.com',
            email='cannotedit@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=player_user,
            name='Cannot Edit',
            email='cannotedit@example.com',
            role=Player.Role.PLAYER,
        )
        coach_user = User.objects.create_user(
            username='caneditcoach@example.com',
            email='caneditcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Can Edit Coach',
            email='caneditcoach@example.com',
            role=Player.Role.COACH,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Coach Editable Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Court A',
        )

        self.client.force_login(player_user)
        player_response = self.client.get(reverse('scheduling:edit_session', args=[session.id]))
        self.assertRedirects(player_response, reverse('scheduling:dashboard'))

        self.client.force_login(coach_user)
        coach_response = self.client.get(reverse('scheduling:edit_session', args=[session.id]))
        self.assertEqual(coach_response.status_code, 200)
        self.assertContains(coach_response, 'Edit Training Session')

    def test_admin_can_manage_training_session_from_detail_page(self):
        admin = User.objects.create_user(
            username='sessionadmin@example.com',
            email='sessionadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Admin Session Control',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Court B',
        )

        self.client.force_login(admin)
        response = self.client.get(reverse('scheduling:session_detail', args=[session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Session')
        self.assertContains(response, 'Session Plan')

    def test_player_rsvp_creates_notification_for_coach(self):
        player_user = User.objects.create_user(
            username='player-rsvp@example.com',
            email='player-rsvp@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=player_user,
            name='RSVP Player',
            email='player-rsvp@example.com',
            role=Player.Role.PLAYER,
        )
        coach = Player.objects.create(
            name='RSVP Coach',
            email='coach-rsvp@example.com',
            role=Player.Role.COACH,
        )
        start_time = timezone.now() + timedelta(days=1)
        session = TrainingSession.objects.create(
            title='Team Practice',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Court A',
        )

        self.client.force_login(player_user)
        response = self.client.post(
            reverse('scheduling:sessions_calendar'),
            data={
                'calendar_action': 'rsvp',
                'session_id': session.id,
                'rsvp_status': SessionRSVP.Status.GOING,
                'year': start_time.year,
                'month': start_time.month,
                'day': start_time.day,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SessionRSVP.objects.filter(
                session=session,
                player=player,
                status=SessionRSVP.Status.GOING,
            ).exists()
        )
        coach_notification = Notification.objects.filter(recipient=coach).first()
        self.assertIsNotNone(coach_notification)
        self.assertIn('RSVP Player accepted', coach_notification.message)

    def test_player_home_shows_next_session_rsvp_status(self):
        player_user = User.objects.create_user(
            username='home-rsvp@example.com',
            email='home-rsvp@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=player_user,
            name='Home RSVP Player',
            email='home-rsvp@example.com',
            role=Player.Role.PLAYER,
        )
        start_time = timezone.now() + timedelta(days=2)
        session = TrainingSession.objects.create(
            title='Morning Session',
            starts_at=start_time,
            ends_at=start_time + timedelta(hours=2),
            location='Main Gym',
        )
        SessionRSVP.objects.create(session=session, player=player, status=SessionRSVP.Status.GOING)

        self.client.force_login(player_user)
        response = self.client.get(reverse('scheduling:player_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You accepted')
