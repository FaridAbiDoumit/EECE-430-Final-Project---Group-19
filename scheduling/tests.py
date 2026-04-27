from datetime import timedelta
import types
from unittest.mock import patch

from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .ai_analytics import _generate_ai_summary
from .models import (
    Announcement,
    ChatGroup,
    GameAttendance,
    GameRoster,
    GroupMessage,
    Match,
    Message,
    Notification,
    Player,
    StaffTeamAssignment,
    Team,
    PlayerAvailability,
    PlayerMatchStat,
    PlayerSorenessReport,
    PersonalSessionNote,
    SessionRSVP,
    SessionPlan,
    SessionVote,
    SessionVotePoll,
    TeamGoal,
    TryoutCandidate,
    TryoutSession,
    TrainingSession,
    UpcomingGame,
)


User = get_user_model()


class SchedulingViewsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_player_create = Player.objects.create

        def create_player_with_approval(*args, **kwargs):
            kwargs.setdefault('is_approved', True)
            return cls._original_player_create(*args, **kwargs)

        Player.objects.create = create_player_with_approval

    @classmethod
    def tearDownClass(cls):
        Player.objects.create = cls._original_player_create
        super().tearDownClass()

    def make_session(self, **overrides):
        starts_at = overrides.pop('starts_at', timezone.now() + timedelta(days=1))
        defaults = {
            'title': 'Practice',
            'starts_at': starts_at,
            'ends_at': starts_at + timedelta(hours=2),
            'location': 'Main Gym',
        }
        defaults.update(overrides)
        return TrainingSession.objects.create(**defaults)

    def make_team(self, name='Team Alpha'):
        return Team.objects.create(name=name)

    def test_signup_creates_player_profile_and_logs_user_in(self):
        team = self.make_team('Signups Team')
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'New Player',
                'email': 'newplayer@example.com',
                'password': 'strong-pass-123',
                'role': 'player',
                'team': team.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newplayer@example.com')
        player = Player.objects.get(email='newplayer@example.com')
        self.assertEqual(player.user, user)
        self.assertEqual(player.role, Player.Role.PLAYER)
        self.assertEqual(player.team, team)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.id))

    def test_signup_creates_staff_user_for_admin_role(self):
        team = self.make_team('Admin Team')
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Admin User',
                'email': 'admin@example.com',
                'password': 'strong-pass-123',
                'role': 'club_admin',
                'team': team.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='admin@example.com')
        self.assertTrue(user.is_staff)
        self.assertFalse(Player.objects.filter(email='admin@example.com').exists())
        self.assertEqual(StaffTeamAssignment.objects.get(user=user).team, team)

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
        team = self.make_team('Duplicates Team')
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
                'team': team.id,
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
        team = self.make_team('Player Home Team')
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Player Home',
                'email': 'playerhome@example.com',
                'password': 'strong-pass-123',
                'role': 'player',
                'team': team.id,
            },
        )

        self.assertRedirects(response, reverse('scheduling:pending_approval'))

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
        team = self.make_team('Coach Home Team')
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Coach Home',
                'email': 'coachhome@example.com',
                'password': 'strong-pass-123',
                'role': 'coach',
                'team': team.id,
            },
        )

        self.assertRedirects(response, reverse('scheduling:pending_approval'))

    def test_league_system_handler_signup_redirects_to_handler_home(self):
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'League Handler',
                'email': 'leaguehandler@example.com',
                'password': 'strong-pass-123',
                'role': 'league_system_handler',
            },
        )

        self.assertRedirects(response, reverse('scheduling:league_system_handler_home'))
        handler = Player.objects.get(email='leaguehandler@example.com')
        self.assertEqual(handler.role, Player.Role.LEAGUE_SYSTEM_HANDLER)
        self.assertIsNone(handler.team)

    def test_signup_ignores_team_for_league_system_handler(self):
        team = self.make_team('Handler Must Not Join')

        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'League Handler Team Field',
                'email': 'leaguehandlerteam@example.com',
                'password': 'strong-pass-123',
                'role': 'league_system_handler',
                'team': team.id,
            },
        )

        self.assertRedirects(response, reverse('scheduling:league_system_handler_home'))
        handler = Player.objects.get(email='leaguehandlerteam@example.com')
        self.assertEqual(handler.role, Player.Role.LEAGUE_SYSTEM_HANDLER)
        self.assertIsNone(handler.team)

    def test_league_system_handler_home_requires_logged_in_handler_and_shows_name(self):
        user = User.objects.create_user(
            username='handlerdashboard@example.com',
            email='handlerdashboard@example.com',
            password='strong-pass-123',
            first_name='Handler View',
        )
        Player.objects.create(
            user=user,
            name='Handler View',
            email='handlerdashboard@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:league_system_handler_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Handler View!')
        self.assertContains(response, 'Record Player and Match Stats')
        self.assertContains(response, 'Add Teams to League')
        self.assertContains(response, reverse('scheduling:league_handler_manage_teams'))
        self.assertContains(response, 'Log out')
        self.assertContains(response, reverse('scheduling:record_match'))
        self.assertNotContains(response, 'Add Team Goal')
        self.assertNotContains(response, 'Opponent Analysis')

    def test_league_system_handler_can_add_team_from_manage_teams_page(self):
        user = User.objects.create_user(
            username='handlerteams@example.com',
            email='handlerteams@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Team Handler',
            email='handlerteams@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        self.client.force_login(user)
        open_page = self.client.get(reverse('scheduling:league_handler_manage_teams'))
        self.assertEqual(open_page.status_code, 200)

        response = self.client.post(
            reverse('scheduling:league_handler_manage_teams'),
            data={
                'name': 'Falcons',
            },
        )

        self.assertRedirects(response, reverse('scheduling:league_handler_manage_teams'))
        self.assertTrue(Team.objects.filter(name='Falcons').exists())

    def test_non_handler_is_redirected_away_from_league_system_handler_home(self):
        user = User.objects.create_user(
            username='notahandler@example.com',
            email='notahandler@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Regular Coach',
            email='notahandler@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:league_system_handler_home'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

    def test_non_handler_is_redirected_away_from_league_handler_manage_teams(self):
        user = User.objects.create_user(
            username='notahandlerteams@example.com',
            email='notahandlerteams@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Regular Player',
            email='notahandlerteams@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:league_handler_manage_teams'))

        self.assertRedirects(response, reverse('scheduling:dashboard'))

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
        self.assertContains(response, 'Team Stats Dashboard')
        self.assertNotContains(response, '<h2>Dashboard</h2>', html=False)

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
        team = self.make_team('Admin Home Team')
        response = self.client.post(
            reverse('scheduling:signup'),
            data={
                'name': 'Admin Home',
                'email': 'adminhome@example.com',
                'password': 'strong-pass-123',
                'role': 'club_admin',
                'team': team.id,
            },
        )

        self.assertRedirects(
            response,
            reverse('scheduling:admin_home'),
            target_status_code=302,
        )

    def test_signup_requires_team_for_player_coach_and_admin(self):
        for role in ['player', 'coach', 'club_admin']:
            response = self.client.post(
                reverse('scheduling:signup'),
                data={
                    'name': f'No Team {role}',
                    'email': f'noteam-{role}@example.com',
                    'password': 'strong-pass-123',
                    'role': role,
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Please select the team you are registering to.')

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
        self.assertContains(response, 'Team Stats Dashboard')
        self.assertNotContains(response, 'System dashboard')

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

    def test_unassigned_admin_cannot_access_schedule_ai_or_tryout_pages(self):
        user = User.objects.create_user(
            username='hubadmin@example.com',
            email='hubadmin@example.com',
            password='strong-pass-123',
            is_staff=True,
        )

        self.client.force_login(user)
        for route_name in [
            'scheduling:create_session',
            'scheduling:ai_analytics_hub',
            'scheduling:create_tryout_session',
            'scheduling:tryout_list',
        ]:
            response = self.client.get(reverse(route_name))
            self.assertRedirects(response, reverse('scheduling:admin_home'))

        calendar_response = self.client.get(reverse('scheduling:sessions_calendar'))
        self.assertRedirects(calendar_response, reverse('scheduling:admin_home'))

    def test_team_assigned_admin_calendar_shows_team_game(self):
        team = self.make_team('Admin Calendar Team')
        opponent = self.make_team('Admin Calendar Opponent')
        scheduled_at = timezone.now() + timedelta(days=3)
        UpcomingGame.objects.create(
            home_team=team,
            away_team=opponent,
            scheduled_at=scheduled_at,
            venue='Center Court',
        )
        admin_user = User.objects.create_user(
            username='teamadmincalendar@example.com',
            email='teamadmincalendar@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        StaffTeamAssignment.objects.create(user=admin_user, team=team, is_approved=True)

        self.client.force_login(admin_user)
        response = self.client.get(
            reverse('scheduling:sessions_calendar'),
            {'year': scheduled_at.year, 'month': scheduled_at.month, 'day': scheduled_at.day},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Game vs Admin Calendar Opponent')

    def test_calendar_shows_games_for_coach_and_rostered_players_only(self):
        team = self.make_team('Calendar Team')
        opponent = self.make_team('Calendar Opponent')
        scheduled_at = timezone.now() + timedelta(days=4)
        game = UpcomingGame.objects.create(
            home_team=team,
            away_team=opponent,
            scheduled_at=scheduled_at,
            venue='Match Arena',
        )
        coach_user = User.objects.create_user(
            username='calendarcoach@example.com',
            email='calendarcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Calendar Coach',
            email='calendarcoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        player_user = User.objects.create_user(
            username='calendarplayer@example.com',
            email='calendarplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=player_user,
            name='Calendar Player',
            email='calendarplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )

        self.client.force_login(coach_user)
        coach_response = self.client.get(
            reverse('scheduling:sessions_calendar'),
            {'year': scheduled_at.year, 'month': scheduled_at.month, 'day': scheduled_at.day},
        )

        self.assertEqual(coach_response.status_code, 200)
        self.assertContains(coach_response, 'Game vs Calendar Opponent')

        self.client.force_login(player_user)
        player_response = self.client.get(
            reverse('scheduling:sessions_calendar'),
            {'year': scheduled_at.year, 'month': scheduled_at.month, 'day': scheduled_at.day},
        )

        self.assertEqual(player_response.status_code, 200)
        self.assertNotContains(player_response, 'Game vs Calendar Opponent')

        GameRoster.objects.create(game=game, player=player)
        rostered_player_response = self.client.get(
            reverse('scheduling:sessions_calendar'),
            {'year': scheduled_at.year, 'month': scheduled_at.month, 'day': scheduled_at.day},
        )

        self.assertEqual(rostered_player_response.status_code, 200)
        self.assertContains(rostered_player_response, 'Game vs Calendar Opponent')
        self.assertContains(rostered_player_response, 'Selected in roster')

    @patch.dict('os.environ', {}, clear=True)
    def test_player_ai_hub_shows_stat_based_fallback_insights(self):
        user = User.objects.create_user(
            username='aiplayer@example.com',
            email='aiplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='AI Player',
            email='aiplayer@example.com',
            role=Player.Role.PLAYER,
        )
        match = Match.objects.create(
            opponent='Spikers',
            date=timezone.now().date(),
            goals_for=3,
            goals_against=1,
        )
        PlayerMatchStat.objects.create(
            match=match,
            player=player,
            points=14,
            assists=2,
            blocks=1,
            returns=3,
        )
        PlayerSorenessReport.objects.create(player=player, soreness_level=8, notes='Tight shoulder')

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:ai_analytics_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI Summary')
        self.assertContains(response, 'Based on recorded stats')
        self.assertContains(response, 'Best contribution')
        self.assertContains(response, 'Next focus')
        self.assertContains(response, 'Recovery status')
        self.assertContains(response, 'Readiness Focus')
        self.assertNotContains(response, 'GROQ_API_KEY')

    @patch.dict('os.environ', {}, clear=True)
    def test_player_ai_hub_includes_next_match_prep(self):
        team = Team.objects.create(name='Prep Team')
        opponent_team = Team.objects.create(name='Prep Rivals')
        user = User.objects.create_user(
            username='prepplayer@example.com',
            email='prepplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Prep Player',
            email='prepplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )
        PlayerSorenessReport.objects.create(player=player, soreness_level=8, notes='Heavy legs')
        upcoming_game = UpcomingGame.objects.create(
            home_team=team,
            away_team=opponent_team,
            scheduled_at=timezone.now() + timedelta(days=1),
            venue='Court A',
        )
        GameAttendance.objects.create(
            game=upcoming_game,
            player=player,
            status=GameAttendance.Status.GOING,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:ai_analytics_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Next Match Prep')
        self.assertContains(response, 'Next match: Prep Rivals')
        self.assertContains(response, 'Going')

    @patch.dict('os.environ', {}, clear=True)
    def test_coach_ai_hub_shows_team_level_fallback_insights(self):
        team = Team.objects.create(name='AI Team')
        user = User.objects.create_user(
            username='aicoach@example.com',
            email='aicoach@example.com',
            password='strong-pass-123',
        )
        coach = Player.objects.create(
            user=user,
            name='AI Coach',
            email='aicoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        player = Player.objects.create(
            name='Team Player',
            email='teamplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )
        match = Match.objects.create(
            opponent='Blockers',
            team=team,
            date=timezone.now().date(),
            goals_for=2,
            goals_against=3,
        )
        PlayerMatchStat.objects.create(
            match=match,
            player=player,
            points=9,
            assists=1,
            blocks=2,
        )
        PlayerSorenessReport.objects.create(player=player, soreness_level=7, notes='Heavy legs')

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:ai_analytics_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Team-level match intelligence')
        self.assertContains(response, 'Latest Result')
        self.assertContains(response, 'AI-Recommended Focus Areas')
        self.assertContains(response, 'Next Opponent Brief')
        self.assertContains(response, coach.team.name)
        self.assertContains(response, 'Opponent Analysis')
        self.assertContains(response, reverse('scheduling:opponent_analysis'))

    @patch.dict('os.environ', {}, clear=True)
    def test_coach_ai_hub_includes_upcoming_opponent_brief(self):
        team = Team.objects.create(name='Preview Team')
        opponent_team = Team.objects.create(name='Rivals')
        user = User.objects.create_user(
            username='previewcoach@example.com',
            email='previewcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Preview Coach',
            email='previewcoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        player = Player.objects.create(
            name='Ready Player',
            email='readyplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )
        match = Match.objects.create(
            opponent='Rivals',
            team=team,
            date=timezone.now().date() - timedelta(days=7),
            goals_for=1,
            goals_against=3,
        )
        PlayerMatchStat.objects.create(
            match=match,
            player=player,
            points=6,
            assists=1,
        )
        upcoming_game = UpcomingGame.objects.create(
            home_team=team,
            away_team=opponent_team,
            scheduled_at=timezone.now() + timedelta(days=2),
            venue='Main Arena',
        )
        GameAttendance.objects.create(
            game=upcoming_game,
            player=player,
            status=GameAttendance.Status.GOING,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:ai_analytics_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upcoming Opponent Brief')
        self.assertContains(response, 'Next opponent: Rivals')
        self.assertContains(response, 'Past record vs Rivals')
        self.assertContains(response, 'Confirmed availability is 1 player')

    def test_opponent_analysis_is_coach_only(self):
        team = Team.objects.create(name='Coach Analysis Team')
        coach_user = User.objects.create_user(
            username='opponentcoach@example.com',
            email='opponentcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Opponent Coach',
            email='opponentcoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        handler_user = User.objects.create_user(
            username='opponenthandler@example.com',
            email='opponenthandler@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=handler_user,
            name='Opponent Handler',
            email='opponenthandler@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        self.client.force_login(coach_user)
        coach_response = self.client.get(reverse('scheduling:opponent_analysis'))

        self.assertEqual(coach_response.status_code, 200)
        self.assertContains(coach_response, 'AI Opponent Analysis')
        self.assertContains(coach_response, 'Coach')
        self.assertContains(coach_response, reverse('scheduling:coach_home'))

        self.client.force_login(handler_user)
        handler_response = self.client.get(reverse('scheduling:opponent_analysis'))

        self.assertRedirects(handler_response, reverse('scheduling:league_system_handler_home'))

    @patch.dict('os.environ', {}, clear=True)
    def test_league_handler_ai_hub_does_not_suggest_opponent_analysis(self):
        user = User.objects.create_user(
            username='handleranalytics@example.com',
            email='handleranalytics@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Handler Analytics',
            email='handleranalytics@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:ai_analytics_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Use Opponent Analysis to compare any two teams head-to-head.')

    @patch.dict('os.environ', {'GROQ_API_KEY': 'test-key', 'GROQ_MODEL': 'demo-model'}, clear=True)
    def test_ai_summary_is_cached_between_identical_requests(self):
        cache.clear()
        call_counter = {'count': 0}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            @property
            def responses(self):
                class ResponsesApi:
                    @staticmethod
                    def create(**kwargs):
                        call_counter['count'] += 1
                        return types.SimpleNamespace(output_text='Cached AI summary')

                return ResponsesApi()

        fake_module = types.SimpleNamespace(OpenAI=FakeClient)

        with patch.dict('sys.modules', {'openai': fake_module}):
            first = _generate_ai_summary(
                role_label='player',
                stat_payload={'player_name': 'Cache Test', 'points': 10},
                fallback_summary='fallback',
            )
            second = _generate_ai_summary(
                role_label='player',
                stat_payload={'player_name': 'Cache Test', 'points': 10},
                fallback_summary='fallback',
            )

        self.assertEqual(first['text'], 'Cached AI summary')
        self.assertEqual(second['text'], 'Cached AI summary')
        self.assertEqual(call_counter['count'], 1)

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

    def test_player_tryout_list_shows_clean_registered_state(self):
        user = User.objects.create_user(
            username='registeredplayer@example.com',
            email='registeredplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Registered Player',
            email='registeredplayer@example.com',
            role=Player.Role.PLAYER,
        )
        tryout = TryoutSession.objects.create(
            title='Open Tryout',
            starts_at=timezone.now() + timedelta(days=5),
            location='Court C',
        )
        TryoutCandidate.objects.create(
            tryout_session=tryout,
            name=player.name,
            email=player.email,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('scheduling:player_tryout_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You already have an active tryout registration.')
        self.assertContains(response, 'Cancel Registration')

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
        session = self.make_session()
        updated_starts_at = timezone.now() + timedelta(days=2)

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session', args=[session.id]),
            data={
                'title': 'Updated Practice',
                'starts_at': updated_starts_at.strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (updated_starts_at + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
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

    def test_chatting_hub_header_shows_contact_name_and_role_only(self):
        sender_user = User.objects.create_user(
            username='chat-sender@example.com',
            email='chat-sender@example.com',
            password='strong-pass-123',
        )
        sender = Player.objects.create(
            user=sender_user,
            name='Chat Sender',
            email='chat-sender@example.com',
            role=Player.Role.PLAYER,
        )
        contact = Player.objects.create(
            name='Chat Coach',
            email='chat-coach@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(sender_user)
        response = self.client.get(reverse('scheduling:chatting_hub'), {'selected': contact.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<h1>{contact.name}</h1>', html=False)
        self.assertContains(response, '<p>Coach</p>', html=False)
        self.assertContains(response, '<span class="chat-list__meta">Coach</span>', html=False)
        self.assertNotContains(response, contact.email)
        self.assertNotContains(response, 'Chatting')
        self.assertNotContains(response, 'Conversation with')

    def test_chatting_hub_post_creates_notification_for_message_recipient(self):
        sender_user = User.objects.create_user(
            username='notif-sender@example.com',
            email='notif-sender@example.com',
            password='strong-pass-123',
        )
        sender = Player.objects.create(
            user=sender_user,
            name='Notify Sender',
            email='notif-sender@example.com',
            role=Player.Role.PLAYER,
        )
        recipient = Player.objects.create(
            name='Notify Recipient',
            email='notif-recipient@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(sender_user)
        response = self.client.post(
            reverse('scheduling:chatting_hub'),
            data={
                'selected_id': recipient.id,
                'content': 'Hello from sender',
            },
        )

        self.assertRedirects(response, f"{reverse('scheduling:chatting_hub')}?selected={recipient.id}")
        self.assertTrue(
            Message.objects.filter(
                player=recipient,
                sender=sender,
                content='Hello from sender',
            ).exists()
        )

        notification = Notification.objects.get(recipient=recipient)
        self.assertEqual(notification.title, 'New message from Notify Sender')
        self.assertIn('Hello from sender', notification.message)

    def test_chatting_hub_can_create_group_with_selected_members(self):
        creator_user = User.objects.create_user(
            username='group-creator@example.com',
            email='group-creator@example.com',
            password='strong-pass-123',
        )
        creator = Player.objects.create(
            user=creator_user,
            name='Group Creator',
            email='group-creator@example.com',
            role=Player.Role.PLAYER,
        )
        member_one = Player.objects.create(name='Member One', email='member1@example.com', role=Player.Role.PLAYER)
        member_two = Player.objects.create(name='Member Two', email='member2@example.com', role=Player.Role.COACH)

        self.client.force_login(creator_user)
        response = self.client.post(
            reverse('scheduling:chatting_hub'),
            data={
                'chat_action': 'create_group',
                'name': 'Team Sparks',
                'members': [member_one.id, member_two.id],
            },
        )

        group = ChatGroup.objects.get(name='Team Sparks')
        self.assertRedirects(response, f"{reverse('scheduling:chatting_hub')}?group={group.id}")
        self.assertTrue(group.members.filter(pk=creator.pk).exists())
        self.assertTrue(group.members.filter(pk=member_one.pk).exists())
        self.assertTrue(group.members.filter(pk=member_two.pk).exists())

        hub_response = self.client.get(reverse('scheduling:chatting_hub'), {'group': group.id})
        self.assertEqual(hub_response.status_code, 200)
        self.assertContains(hub_response, '3 members')

    def test_chatting_hub_group_message_creates_message_and_recipient_notification(self):
        sender_user = User.objects.create_user(
            username='group-sender@example.com',
            email='group-sender@example.com',
            password='strong-pass-123',
        )
        sender = Player.objects.create(
            user=sender_user,
            name='Group Sender',
            email='group-sender@example.com',
            role=Player.Role.PLAYER,
        )
        receiver = Player.objects.create(name='Group Receiver', email='group-receiver@example.com', role=Player.Role.COACH)
        group = ChatGroup.objects.create(
            name='Demo Group',
            created_by_player=sender,
            created_by_user=sender_user,
        )
        group.members.add(sender, receiver)

        self.client.force_login(sender_user)
        response = self.client.post(
            reverse('scheduling:chatting_hub'),
            data={
                'chat_action': 'send_group',
                'group_id': group.id,
                'content': 'Hello group',
            },
        )

        self.assertRedirects(response, f"{reverse('scheduling:chatting_hub')}?group={group.id}")
        self.assertTrue(
            GroupMessage.objects.filter(
                group=group,
                sender_player=sender,
                content='Hello group',
            ).exists()
        )

        self.assertFalse(Notification.objects.filter(recipient=sender, title=f'New group message: {group.name}').exists())
        receiver_notification = Notification.objects.get(recipient=receiver, title=f'New group message: {group.name}')
        self.assertIn('Hello group', receiver_notification.message)

    def test_chatting_hub_sections_are_independently_scrollable(self):
        viewer_user = User.objects.create_user(
            username='scroll-viewer@example.com',
            email='scroll-viewer@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=viewer_user,
            name='Scroll Viewer',
            email='scroll-viewer@example.com',
            role=Player.Role.PLAYER,
        )
        Player.objects.create(name='Scroll Contact', email='scroll-contact@example.com', role=Player.Role.COACH)

        self.client.force_login(viewer_user)
        response = self.client.get(reverse('scheduling:chatting_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="chat-section__body"', html=False)
        self.assertContains(response, 'overflow-y: auto;', html=False)
        self.assertContains(response, 'id="toggleGroupForm"', html=False)

    def test_player_chatting_hub_shows_announcements_but_hides_create_controls(self):
        player_user = User.objects.create_user(
            username='player-announcements@example.com',
            email='player-announcements@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=player_user,
            name='Player Announcements',
            email='player-announcements@example.com',
            role=Player.Role.PLAYER,
        )
        coach_user = User.objects.create_user(
            username='coach-feed@example.com',
            email='coach-feed@example.com',
            password='strong-pass-123',
        )
        coach = Player.objects.create(
            user=coach_user,
            name='Coach Feed',
            email='coach-feed@example.com',
            role=Player.Role.COACH,
        )
        Announcement.objects.create(
            title='Team Notice',
            content='Game review starts at 6 PM.',
            created_by_player=coach,
            created_by_user=coach_user,
        )
        Player.objects.create(name='Other Contact', email='other-contact@example.com', role=Player.Role.COACH)

        self.client.force_login(player_user)
        response = self.client.get(reverse('scheduling:chatting_hub'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Announcements')
        self.assertContains(response, 'Team Notice')
        self.assertContains(response, 'Game review starts at 6 PM.')
        self.assertNotContains(response, 'id="toggleAnnouncementForm"', html=False)
        self.assertNotContains(response, 'chat_action" value="create_announcement"', html=False)

    def test_coach_and_admin_chatting_hub_show_announcements_section(self):
        coach_user = User.objects.create_user(
            username='coach-announcements@example.com',
            email='coach-announcements@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Coach Announcements',
            email='coach-announcements@example.com',
            role=Player.Role.COACH,
        )
        admin_user = User.objects.create_user(
            username='admin-announcements@example.com',
            email='admin-announcements@example.com',
            password='strong-pass-123',
            is_staff=True,
        )

        self.client.force_login(coach_user)
        coach_response = self.client.get(reverse('scheduling:chatting_hub'))
        self.assertEqual(coach_response.status_code, 200)
        self.assertContains(coach_response, 'id="toggleAnnouncementForm"', html=False)

        self.client.force_login(admin_user)
        admin_response = self.client.get(reverse('scheduling:chatting_hub'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, 'id="toggleAnnouncementForm"', html=False)

    def test_announcement_post_creates_notifications_for_all_active_players(self):
        coach_user = User.objects.create_user(
            username='coach-broadcast@example.com',
            email='coach-broadcast@example.com',
            password='strong-pass-123',
        )
        coach = Player.objects.create(
            user=coach_user,
            name='Coach Broadcaster',
            email='coach-broadcast@example.com',
            role=Player.Role.COACH,
            is_approved=True,
        )
        first = Player.objects.create(
            name='First Active',
            email='first-active@example.com',
            role=Player.Role.PLAYER,
            is_approved=True,
        )
        second = Player.objects.create(
            name='Second Active',
            email='second-active@example.com',
            role=Player.Role.COACH,
            is_approved=True,
        )

        self.client.force_login(coach_user)
        response = self.client.post(
            reverse('scheduling:chatting_hub'),
            data={
                'chat_action': 'create_announcement',
                'title': 'Practice Update',
                'content': 'Practice starts at 7 PM today.',
            },
        )

        self.assertEqual(response.status_code, 302)
        announcement = Announcement.objects.get(title='Practice Update')
        self.assertEqual(announcement.created_by_player, coach)
        self.assertEqual(Notification.objects.filter(title='Announcement: Practice Update').count(), 2)
        self.assertFalse(Notification.objects.filter(recipient=coach, title='Announcement: Practice Update').exists())
        self.assertTrue(Notification.objects.filter(recipient=first, title='Announcement: Practice Update').exists())
        self.assertTrue(Notification.objects.filter(recipient=second, title='Announcement: Practice Update').exists())

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
        session = self.make_session()

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session_plan', args=[session.id]),
            data={'title': 'Warmup Plan', 'drills': 'Stretching\nServing\nScrimmage'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(SessionPlan.objects.filter(session=session, title='Warmup Plan').exists())

    def test_personal_note_updates_existing_note(self):
        user = User.objects.create_user(
            username='player1@example.com',
            email='player1@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Player One',
            email='player1@example.com',
            role=Player.Role.PLAYER,
        )
        session = self.make_session()
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
        user = User.objects.create_user(
            username='coach@example.com',
            email='coach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Coach User',
            email='coach@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(user)
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
            username='player1@example.com',
            email='player1@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=user,
            name='Player One',
            email='player1@example.com',
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
            data={'option': option_2.id},
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
        session = self.make_session()
        updated_starts_at = timezone.now() + timedelta(days=2)

        self.client.force_login(admin)
        response = self.client.post(
            reverse('scheduling:edit_session', args=[session.id]),
            data={
                'title': 'Updated Practice',
                'starts_at': updated_starts_at.strftime('%Y-%m-%dT%H:%M'),
                'ends_at': (updated_starts_at + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
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

    def test_cancel_session_deletes_session(self):
        user = User.objects.create_user(
            username='coach@example.com',
            email='coach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=user,
            name='Coach User',
            email='coach@example.com',
            role=Player.Role.COACH,
        )
        session = self.make_session()

        self.client.force_login(user)
        response = self.client.post(reverse('scheduling:cancel_session', args=[session.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TrainingSession.objects.filter(id=session.id).exists())

    def test_next_session_shows_earliest_upcoming_session(self):
        user = User.objects.create_user(
            username='viewer@example.com',
            email='viewer@example.com',
            password='strong-pass-123',
        )
        self.client.force_login(user)
        self.make_session(title='Later Session', starts_at=timezone.now() + timedelta(days=2), location='Court B')
        earliest = self.make_session(title='Earlier Session', starts_at=timezone.now() + timedelta(hours=3), location='Court A')

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
        session = self.make_session()
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

    def test_player_can_log_daily_soreness(self):
        player_user = User.objects.create_user(
            username='sorenessplayer@example.com',
            email='sorenessplayer@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=player_user,
            name='Soreness Player',
            email='sorenessplayer@example.com',
            role=Player.Role.PLAYER,
        )

        self.client.force_login(player_user)
        response = self.client.post(
            reverse('scheduling:log_player_soreness'),
            data={'soreness_level': 7, 'notes': 'Shoulder feels tight'},
        )

        self.assertEqual(response.status_code, 302)
        report = PlayerSorenessReport.objects.get(player=player)
        self.assertEqual(report.soreness_level, 7)
        self.assertEqual(report.notes, 'Shoulder feels tight')

    def test_player_home_shows_latest_soreness_card(self):
        player_user = User.objects.create_user(
            username='homesoreness@example.com',
            email='homesoreness@example.com',
            password='strong-pass-123',
        )
        player = Player.objects.create(
            user=player_user,
            name='Home Soreness',
            email='homesoreness@example.com',
            role=Player.Role.PLAYER,
        )
        PlayerSorenessReport.objects.create(player=player, soreness_level=4, notes='Light fatigue')

        self.client.force_login(player_user)
        response = self.client.get(reverse('scheduling:player_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Daily soreness')
        self.assertContains(response, 'Latest level: 4/10')

    def test_team_goal_form_persists_metric_and_target_value(self):
        handler_user = User.objects.create_user(
            username='goalhandler@example.com',
            email='goalhandler@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=handler_user,
            name='Goal Handler',
            email='goalhandler@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        self.client.force_login(handler_user)
        response = self.client.post(
            reverse('scheduling:add_team_goal'),
            data={
                'description': 'Improve our serving output',
                'metric': TeamGoal.Metric.ACES,
                'target_value': 12,
            },
        )

        self.assertEqual(response.status_code, 302)
        goal = TeamGoal.objects.get()
        self.assertEqual(goal.metric, TeamGoal.Metric.ACES)
        self.assertEqual(goal.target_value, 12)

    def test_coach_cannot_record_match_or_team_goal(self):
        coach_user = User.objects.create_user(
            username='blockedcoach@example.com',
            email='blockedcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Blocked Coach',
            email='blockedcoach@example.com',
            role=Player.Role.COACH,
        )
        player = Player.objects.create(
            name='Blocked Stats Target',
            email='blocked-stats-target@example.com',
            role=Player.Role.PLAYER,
        )
        existing_match = Match.objects.create(
            opponent='Existing Match',
            date=timezone.now().date(),
            goals_for=1,
            goals_against=1,
        )

        self.client.force_login(coach_user)
        match_response = self.client.post(
            reverse('scheduling:record_match'),
            data={
                'opponent': 'Denied Team',
                'date': timezone.now().date().isoformat(),
                'goals_for': 2,
                'goals_against': 1,
                'result': Match.Result.WIN,
            },
        )
        player_stats_response = self.client.post(
            reverse('scheduling:record_player_stats', args=[existing_match.id]),
            data={
                'player': player.id,
                'goals': 1,
                'interceptions': 1,
                'points': 2,
                'blocks': 1,
                'assists': 0,
                'aces': 0,
                'returns': 1,
                'most_recent_injury': '',
            },
        )
        goal_response = self.client.post(
            reverse('scheduling:add_team_goal'),
            data={
                'description': 'Coach should not be allowed',
                'metric': TeamGoal.Metric.POINTS,
                'target_value': 40,
            },
        )

        self.assertRedirects(match_response, reverse('scheduling:coach_home'))
        self.assertRedirects(player_stats_response, reverse('scheduling:coach_home'))
        self.assertRedirects(goal_response, reverse('scheduling:coach_home'))
        self.assertEqual(Match.objects.count(), 1)
        self.assertFalse(PlayerMatchStat.objects.filter(match=existing_match, player=player).exists())
        self.assertEqual(TeamGoal.objects.count(), 0)

    def test_admin_cannot_record_match_or_player_stats_or_team_goal(self):
        admin_user = User.objects.create_user(
            username='blockedadminstats@example.com',
            email='blockedadminstats@example.com',
            password='strong-pass-123',
            is_staff=True,
        )
        player = Player.objects.create(
            name='Admin Block Target',
            email='admin-block-target@example.com',
            role=Player.Role.PLAYER,
        )
        existing_match = Match.objects.create(
            opponent='Admin Existing Match',
            date=timezone.now().date(),
            goals_for=0,
            goals_against=0,
        )

        self.client.force_login(admin_user)
        match_response = self.client.post(
            reverse('scheduling:record_match'),
            data={
                'opponent': 'Admin Denied Team',
                'date': timezone.now().date().isoformat(),
                'goals_for': 5,
                'goals_against': 1,
            },
        )
        player_stats_response = self.client.post(
            reverse('scheduling:record_player_stats', args=[existing_match.id]),
            data={
                'player': player.id,
                'goals': 1,
                'interceptions': 1,
                'points': 2,
                'blocks': 1,
                'assists': 0,
                'aces': 0,
                'returns': 1,
                'most_recent_injury': '',
            },
        )
        goal_response = self.client.post(
            reverse('scheduling:add_team_goal'),
            data={
                'description': 'Admin should not be allowed',
                'metric': TeamGoal.Metric.POINTS,
                'target_value': 60,
            },
        )

        self.assertRedirects(match_response, reverse('scheduling:admin_home'))
        self.assertRedirects(player_stats_response, reverse('scheduling:admin_home'))
        self.assertRedirects(goal_response, reverse('scheduling:admin_home'))
        self.assertEqual(Match.objects.count(), 1)
        self.assertFalse(PlayerMatchStat.objects.filter(match=existing_match, player=player).exists())
        self.assertEqual(TeamGoal.objects.count(), 0)

    def test_league_handler_can_record_match_and_player_stats(self):
        team = self.make_team('Handler Stats Team')
        handler_user = User.objects.create_user(
            username='matchhandler@example.com',
            email='matchhandler@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=handler_user,
            name='Match Handler',
            email='matchhandler@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )
        player = Player.objects.create(
            name='Stats Target',
            email='statstarget@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )

        self.client.force_login(handler_user)
        match_response = self.client.post(
            reverse('scheduling:record_match'),
            data={
                'team': team.id,
                'opponent': 'Data Team',
                'date': timezone.now().date().isoformat(),
                'goals_for': 3,
                'goals_against': 0,
                'result': Match.Result.WIN,
            },
        )

        self.assertEqual(match_response.status_code, 302)
        match = Match.objects.get(opponent='Data Team')

        stats_response = self.client.post(
            reverse('scheduling:record_player_stats', args=[match.id]),
            data={
                'player': player.id,
                'goals': 1,
                'interceptions': 2,
                'points': 8,
                'blocks': 3,
                'assists': 4,
                'aces': 2,
                'returns': 5,
                'most_recent_injury': '',
            },
        )

        self.assertEqual(stats_response.status_code, 302)
        self.assertTrue(PlayerMatchStat.objects.filter(match=match, player=player).exists())

    def test_handler_recorded_stats_show_on_coach_and_player_dashboards(self):
        team = self.make_team('Visibility Team')
        handler_user = User.objects.create_user(
            username='dashboardhandler@example.com',
            email='dashboardhandler@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=handler_user,
            name='Dashboard Handler',
            email='dashboardhandler@example.com',
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
        )

        coach_user = User.objects.create_user(
            username='visibilitycoach@example.com',
            email='visibilitycoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Visibility Coach',
            email='visibilitycoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )

        player_user = User.objects.create_user(
            username='visibilityplayer@example.com',
            email='visibilityplayer@example.com',
            password='strong-pass-123',
        )
        player_profile = Player.objects.create(
            user=player_user,
            name='Visibility Player',
            email='visibilityplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )

        self.client.force_login(handler_user)
        match_response = self.client.post(
            reverse('scheduling:record_match'),
            data={
                'team': team.id,
                'opponent': 'Visibility Rivals',
                'date': timezone.now().date().isoformat(),
                'goals_for': 3,
                'goals_against': 1,
            },
        )
        self.assertEqual(match_response.status_code, 302)
        match = Match.objects.get(opponent='Visibility Rivals')

        stats_response = self.client.post(
            reverse('scheduling:record_player_stats', args=[match.id]),
            data={
                'player': player_profile.id,
                'goals': 2,
                'interceptions': 1,
                'points': 11,
                'blocks': 3,
                'assists': 2,
                'aces': 1,
                'returns': 4,
                'most_recent_injury': '',
            },
        )
        self.assertEqual(stats_response.status_code, 302)

        self.client.force_login(coach_user)
        coach_dashboard_response = self.client.get(reverse('scheduling:team_stats'))
        self.assertEqual(coach_dashboard_response.status_code, 200)
        self.assertTrue(
            any(
                item['player__name'] == player_profile.name and item['total_goals'] == 2
                for item in coach_dashboard_response.context['top_scorers']
            )
        )

        self.client.force_login(player_user)
        player_dashboard_response = self.client.get(
            reverse('scheduling:player_stats_detail', args=[player_profile.id])
        )
        self.assertEqual(player_dashboard_response.status_code, 200)
        self.assertEqual(player_dashboard_response.context['totals']['total_goals'], 2)
        self.assertEqual(player_dashboard_response.context['totals']['total_points'], 11)
        self.assertContains(player_dashboard_response, 'Per-Match Averages')

    def test_team_stats_hides_record_actions_for_coach(self):
        coach_user = User.objects.create_user(
            username='viewcoach@example.com',
            email='viewcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='View Coach',
            email='viewcoach@example.com',
            role=Player.Role.COACH,
        )

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:team_stats'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('scheduling:record_match'))
        self.assertNotContains(response, reverse('scheduling:add_team_goal'))

    def test_team_stats_computes_goal_progress_and_shows_latest_soreness(self):
        team = self.make_team('Coach Scope Team')
        coach_user = User.objects.create_user(
            username='statscoach@example.com',
            email='statscoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Stats Coach',
            email='statscoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        player = Player.objects.create(
            name='Tracked Player',
            email='tracked@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )
        match = Match.objects.create(opponent='Rivals', team=team, date=timezone.now().date(), goals_for=3, goals_against=1)
        PlayerMatchStat.objects.create(match=match, player=player, points=10, aces=2, assists=1)
        TeamGoal.objects.create(description='Reach point target', metric=TeamGoal.Metric.POINTS, target_value=20)
        PlayerSorenessReport.objects.create(player=player, soreness_level=6, notes='Normal soreness')

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:team_stats'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['team_goals'][0]['progress_pct'], 50)
        self.assertEqual(response.context['soreness_overview'][0]['latest_report'].soreness_level, 6)
        self.assertContains(response, 'Latest Soreness Levels')

    def test_team_stats_rankings_respect_selected_metric(self):
        team = self.make_team('Ranking Team')
        coach_user = User.objects.create_user(
            username='rankingcoach@example.com',
            email='rankingcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Ranking Coach',
            email='rankingcoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        first = Player.objects.create(name='First Player', email='firstmetric@example.com', role=Player.Role.PLAYER, team=team)
        second = Player.objects.create(name='Second Player', email='secondmetric@example.com', role=Player.Role.PLAYER, team=team)
        match = Match.objects.create(opponent='Ranking Match', team=team, date=timezone.now().date(), goals_for=2, goals_against=2)
        PlayerMatchStat.objects.create(match=match, player=first, assists=1, points=20)
        PlayerMatchStat.objects.create(match=match, player=second, assists=5, points=3)

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:team_stats'), {'metric': 'assists'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ranking_metric'], 'assists')
        self.assertEqual(response.context['top_players'][0].name, 'Second Player')
        self.assertEqual(response.context['weak_players'][0].name, 'First Player')

    def test_coach_team_stats_are_limited_to_own_team_games_and_players(self):
        team_a = self.make_team('Team A Scope')
        team_b = self.make_team('Team B Scope')

        coach_user = User.objects.create_user(
            username='scopedcoach@example.com',
            email='scopedcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Scoped Coach',
            email='scopedcoach@example.com',
            role=Player.Role.COACH,
            team=team_a,
        )

        player_a = Player.objects.create(
            name='Scoped Player A',
            email='scoped-player-a@example.com',
            role=Player.Role.PLAYER,
            team=team_a,
        )
        player_b = Player.objects.create(
            name='Scoped Player B',
            email='scoped-player-b@example.com',
            role=Player.Role.PLAYER,
            team=team_b,
        )

        match_a = Match.objects.create(opponent='Rivals A', team=team_a, date=timezone.now().date(), goals_for=3, goals_against=1)
        match_b = Match.objects.create(opponent='Rivals B', team=team_b, date=timezone.now().date(), goals_for=2, goals_against=2)
        PlayerMatchStat.objects.create(match=match_a, player=player_a, goals=2, points=9)
        PlayerMatchStat.objects.create(match=match_b, player=player_b, goals=4, points=11)

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:team_stats'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['match_count'], 1)
        self.assertEqual(response.context['players'].count(), 1)
        self.assertEqual(response.context['players'][0].id, player_a.id)
        self.assertTrue(any(item['player__name'] == player_a.name for item in response.context['top_scorers']))
        self.assertFalse(any(item['player__name'] == player_b.name for item in response.context['top_scorers']))

    def test_coach_cannot_open_player_stats_of_other_team(self):
        team_a = self.make_team('Detail Team A')
        team_b = self.make_team('Detail Team B')

        coach_user = User.objects.create_user(
            username='detailcoach@example.com',
            email='detailcoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Detail Coach',
            email='detailcoach@example.com',
            role=Player.Role.COACH,
            team=team_a,
        )
        other_team_player = Player.objects.create(
            name='Other Team Player',
            email='other-team-player@example.com',
            role=Player.Role.PLAYER,
            team=team_b,
        )

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:player_stats_detail', args=[other_team_player.id]))

        self.assertRedirects(response, reverse('scheduling:team_stats'))

    def test_player_stats_detail_includes_average_summary(self):
        team = self.make_team('Average Team')
        coach_user = User.objects.create_user(
            username='averagecoach@example.com',
            email='averagecoach@example.com',
            password='strong-pass-123',
        )
        Player.objects.create(
            user=coach_user,
            name='Average Coach',
            email='averagecoach@example.com',
            role=Player.Role.COACH,
            team=team,
        )
        player = Player.objects.create(
            name='Average Player',
            email='averageplayer@example.com',
            role=Player.Role.PLAYER,
            team=team,
        )
        first_match = Match.objects.create(opponent='One', team=team, date=timezone.now().date(), goals_for=1, goals_against=0)
        second_match = Match.objects.create(opponent='Two', team=team, date=timezone.now().date() + timedelta(days=1), goals_for=2, goals_against=1)
        PlayerMatchStat.objects.create(match=first_match, player=player, points=6, blocks=2, aces=1)
        PlayerMatchStat.objects.create(match=second_match, player=player, points=4, blocks=4, aces=3)

        self.client.force_login(coach_user)
        response = self.client.get(reverse('scheduling:player_stats_detail', args=[player.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['averages']['avg_points'], 5.0)
        self.assertEqual(response.context['averages']['avg_blocks'], 3.0)
        self.assertContains(response, 'Per-Match Averages')
        self.assertContains(response, 'Average Output Per Match')
