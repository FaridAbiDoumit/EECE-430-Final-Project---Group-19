from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from scheduling.models import (
    Announcement,
    AnnouncementReply,
    ChatGroup,
    GameAttendance,
    Match,
    Message,
    Notification,
    PersonalCalendarEvent,
    PersonalSessionNote,
    Player,
    PlayerAvailability,
    PlayerMatchStat,
    PlayerSorenessReport,
    SessionPlan,
    SessionRSVP,
    SessionVote,
    SessionVoteOption,
    SessionVotePoll,
    StaffTeamAssignment,
    SupportTicket,
    Team,
    TeamGoal,
    TrainingSession,
    TryoutCandidate,
    TryoutSession,
    UpcomingGame,
)


User = get_user_model()
DEMO_PASSWORD = "test12345"


class Command(BaseCommand):
    help = "Seed a simple demo dataset for manual testing."

    def handle(self, *args, **options):
        now = timezone.now()

        team_alpha = Team.objects.create(name="Team Alpha")
        team_beta = Team.objects.create(name="Team Beta")
        Team.objects.create(name="Team Gamma")

        admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        StaffTeamAssignment.objects.create(user=admin_user, team=team_alpha, is_approved=True)

        handler_user = User.objects.create_user(
            username="handler@example.com",
            email="handler@example.com",
            password=DEMO_PASSWORD,
            first_name="League",
            last_name="Handler",
        )
        handler = Player.objects.create(
            user=handler_user,
            name="League Handler",
            email="handler@example.com",
            role=Player.Role.LEAGUE_SYSTEM_HANDLER,
            team=team_alpha,
            is_approved=True,
        )

        coach_user = User.objects.create_user(
            username="coach@example.com",
            email="coach@example.com",
            password=DEMO_PASSWORD,
            first_name="Coach",
            last_name="One",
        )
        coach = Player.objects.create(
            user=coach_user,
            name="Coach One",
            email="coach@example.com",
            role=Player.Role.COACH,
            team=team_alpha,
            is_approved=True,
        )

        player1_user = User.objects.create_user(
            username="player1@example.com",
            email="player1@example.com",
            password=DEMO_PASSWORD,
            first_name="Player",
            last_name="One",
        )
        player1 = Player.objects.create(
            user=player1_user,
            name="Player One",
            email="player1@example.com",
            role=Player.Role.PLAYER,
            team=team_alpha,
            is_approved=True,
        )

        player2_user = User.objects.create_user(
            username="player2@example.com",
            email="player2@example.com",
            password=DEMO_PASSWORD,
            first_name="Player",
            last_name="Two",
        )
        player2 = Player.objects.create(
            user=player2_user,
            name="Player Two",
            email="player2@example.com",
            role=Player.Role.PLAYER,
            team=team_alpha,
            status=Player.Status.RECOVERING,
            is_approved=True,
        )

        player3_user = User.objects.create_user(
            username="player3@example.com",
            email="player3@example.com",
            password=DEMO_PASSWORD,
            first_name="Player",
            last_name="Three",
        )
        player3 = Player.objects.create(
            user=player3_user,
            name="Player Three",
            email="player3@example.com",
            role=Player.Role.PLAYER,
            team=team_alpha,
            status=Player.Status.INJURED,
            is_approved=True,
        )

        player4_user = User.objects.create_user(
            username="player4@example.com",
            email="player4@example.com",
            password=DEMO_PASSWORD,
            first_name="Player",
            last_name="Four",
        )
        player4 = Player.objects.create(
            user=player4_user,
            name="Player Four",
            email="player4@example.com",
            role=Player.Role.PLAYER,
            team=team_beta,
            is_approved=True,
        )

        practice = TrainingSession.objects.create(
            title="Evening Practice",
            starts_at=now + timedelta(days=1, hours=2),
            ends_at=now + timedelta(days=1, hours=4),
            location="Main Gym",
            session_type=TrainingSession.SessionType.PRACTICE,
            notes="Serve receive and transition work.",
        )
        TrainingSession.objects.create(
            title="Match Review",
            starts_at=now + timedelta(days=3, hours=1),
            ends_at=now + timedelta(days=3, hours=2, minutes=30),
            location="Video Room",
            session_type=TrainingSession.SessionType.FRIENDLY,
            notes="Quick review before the next game.",
        )
        SessionPlan.objects.create(
            session=practice,
            title="Practice Plan",
            drills="Warm-up\nServe receive\nBlocking drill\nScrimmage",
        )

        SessionRSVP.objects.create(session=practice, player=player1, status=SessionRSVP.Status.GOING)
        SessionRSVP.objects.create(session=practice, player=player2, status=SessionRSVP.Status.GOING)
        SessionRSVP.objects.create(session=practice, player=player3, status=SessionRSVP.Status.NOT_GOING)

        PlayerAvailability.objects.create(
            player=player1,
            weekday=PlayerAvailability.Weekday.MONDAY,
            start_time=timezone.datetime(2026, 1, 1, 18, 0).time(),
            end_time=timezone.datetime(2026, 1, 1, 20, 0).time(),
            notes="Best after classes.",
        )
        PlayerAvailability.objects.create(
            player=player2,
            weekday=PlayerAvailability.Weekday.WEDNESDAY,
            start_time=timezone.datetime(2026, 1, 1, 17, 0).time(),
            end_time=timezone.datetime(2026, 1, 1, 19, 0).time(),
        )

        PersonalCalendarEvent.objects.create(
            player=player1,
            title="Physio Visit",
            starts_at=now + timedelta(days=2, hours=1),
            ends_at=now + timedelta(days=2, hours=2),
            location="Clinic",
            notes="Routine check.",
        )
        PersonalSessionNote.objects.create(
            session=practice,
            player=player1,
            content="Focus on quicker first step in defense.",
        )

        poll = SessionVotePoll.objects.create(
            title="Next Training Time",
            description="Pick the better slot for next week.",
            closes_at=now + timedelta(days=2),
        )
        option1 = SessionVoteOption.objects.create(
            poll=poll,
            starts_at=now + timedelta(days=6, hours=18),
            location="Main Gym",
        )
        option2 = SessionVoteOption.objects.create(
            poll=poll,
            starts_at=now + timedelta(days=7, hours=19),
            location="Main Gym",
        )
        SessionVote.objects.create(poll=poll, option=option1, player=player1)
        SessionVote.objects.create(poll=poll, option=option2, player=player2)

        match_one = Match.objects.create(
            opponent="Team Beta",
            team=team_alpha,
            date=(now - timedelta(days=10)).date(),
            goals_for=3,
            goals_against=1,
            notes="Strong passing night.",
        )
        match_two = Match.objects.create(
            opponent="Team Beta",
            team=team_alpha,
            date=(now - timedelta(days=4)).date(),
            goals_for=2,
            goals_against=3,
            notes="Close loss late in the set.",
        )
        match_three = Match.objects.create(
            opponent="Team Gamma",
            team=team_alpha,
            date=(now - timedelta(days=1)).date(),
            goals_for=3,
            goals_against=0,
            notes="Clean win.",
        )

        for match, points1, points2, points3 in [
            (match_one, 15, 9, 2),
            (match_two, 11, 7, 1),
            (match_three, 18, 10, 0),
        ]:
            PlayerMatchStat.objects.create(
                match=match,
                player=player1,
                goals=2,
                interceptions=3,
                points=points1,
                blocks=2,
                assists=4,
                aces=3,
                returns=5,
            )
            PlayerMatchStat.objects.create(
                match=match,
                player=player2,
                goals=1,
                interceptions=2,
                points=points2,
                blocks=1,
                assists=2,
                aces=1,
                returns=3,
            )
            PlayerMatchStat.objects.create(
                match=match,
                player=player3,
                goals=0,
                interceptions=1,
                points=points3,
                blocks=0,
                assists=1,
                aces=0,
                returns=1,
                most_recent_injury="Left ankle soreness",
            )

        TeamGoal.objects.create(description="Reach 40 points", metric=TeamGoal.Metric.POINTS, target_value=40)
        TeamGoal.objects.create(description="Record 10 blocks", metric=TeamGoal.Metric.BLOCKS, target_value=10)

        PlayerSorenessReport.objects.create(player=player1, soreness_level=3, notes="Feeling good.")
        PlayerSorenessReport.objects.create(player=player2, soreness_level=6, notes="Mild shoulder tightness.")
        PlayerSorenessReport.objects.create(player=player3, soreness_level=8, notes="Recovering from ankle pain.")

        upcoming_game = UpcomingGame.objects.create(
            home_team=team_alpha,
            away_team=team_beta,
            scheduled_at=now + timedelta(days=5),
            venue="Main Gym",
            notes="Arrive 30 minutes early.",
        )
        GameAttendance.objects.create(game=upcoming_game, player=player1, status=GameAttendance.Status.GOING)
        GameAttendance.objects.create(game=upcoming_game, player=player2, status=GameAttendance.Status.MAYBE)
        GameAttendance.objects.create(game=upcoming_game, player=player3, status=GameAttendance.Status.INJURED)

        tryout = TryoutSession.objects.create(
            title="Spring Tryout",
            starts_at=now + timedelta(days=8),
            location="Court B",
            description="Bring water and sportswear.",
        )
        TryoutCandidate.objects.create(
            tryout_session=tryout,
            name="Jamie Candidate",
            email="candidate@example.com",
            notes="Outside hitter",
        )

        group = ChatGroup.objects.create(name="Team Alpha Chat", created_by_player=coach)
        group.members.set([coach, player1, player2, player3])

        Message.objects.create(
            player=player1,
            sender=coach,
            sender_is_admin=False,
            subject="Good work",
            content="Keep leading the back row.",
        )
        Announcement.objects.create(
            title="Practice Reminder",
            content="Practice starts at 6 PM tomorrow.",
            created_by_player=coach,
        )
        announcement = Announcement.objects.get(title="Practice Reminder")
        AnnouncementReply.objects.create(
            announcement=announcement,
            sender=player1,
            content="I will be there.",
        )

        Notification.objects.create(
            recipient=player1,
            title="Stats updated",
            message="Your latest match stats have been recorded.",
            notification_type=Notification.Type.STATS_ADDED,
        )
        Notification.objects.create(
            recipient=player2,
            title="Upcoming game",
            message="Please update your attendance for the next game.",
            notification_type=Notification.Type.GENERAL,
        )

        SupportTicket.objects.create(
            player=player2,
            subject="Need recovery guidance",
            message="Can we reduce jumping volume this week?",
            priority="medium",
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("Login password for all demo accounts: test12345")
        self.stdout.write("Admin: admin@example.com")
        self.stdout.write("Coach: coach@example.com")
        self.stdout.write("Handler: handler@example.com")
        self.stdout.write("Players: player1@example.com, player2@example.com, player3@example.com, player4@example.com")
