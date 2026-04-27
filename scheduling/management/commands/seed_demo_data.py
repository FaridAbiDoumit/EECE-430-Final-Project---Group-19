from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from scheduling.models import (
    Announcement,
    AnnouncementReply,
    ChatGroup,
    GameAttendance,
    GameRoster,
    GroupMessage,
    Match,
    MembershipPayment,
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
    TeamSubscriptionFee,
    TrainingSession,
    TryoutCandidate,
    TryoutSession,
    UpcomingGame,
)


User = get_user_model()
DEMO_PASSWORD = "test12345"
DEMO_DOMAIN = "example.com"

TEAM_BLUEPRINTS = [
    {
        "name": "Barcelona",
        "slug": "barcelona",
        "gender_category": Team.GenderCategory.MENS,
        "court_name": "Palau Blaugrana",
        "court_lat": Decimal("41.380898"),
        "court_lng": Decimal("2.122820"),
        "currency": "EUR",
        "monthly_fee": Decimal("95.00"),
        "practice_hour": 18,
    },
    {
        "name": "Real Madrid",
        "slug": "realmadrid",
        "gender_category": Team.GenderCategory.MENS,
        "court_name": "WiZink Center",
        "court_lat": Decimal("40.424021"),
        "court_lng": Decimal("-3.671175"),
        "currency": "EUR",
        "monthly_fee": Decimal("98.00"),
        "practice_hour": 19,
    },
    {
        "name": "VakifBank",
        "slug": "vakifbank",
        "gender_category": Team.GenderCategory.WOMENS,
        "court_name": "VakifBank Sports Palace",
        "court_lat": Decimal("41.047614"),
        "court_lng": Decimal("28.987846"),
        "currency": "TRY",
        "monthly_fee": Decimal("3400.00"),
        "practice_hour": 17,
    },
    {
        "name": "Fenerbahce",
        "slug": "fenerbahce",
        "gender_category": Team.GenderCategory.WOMENS,
        "court_name": "Burhan Felek Hall",
        "court_lat": Decimal("41.021027"),
        "court_lng": Decimal("29.043209"),
        "currency": "TRY",
        "monthly_fee": Decimal("3550.00"),
        "practice_hour": 18,
    },
    {
        "name": "Cedars",
        "slug": "cedars",
        "gender_category": Team.GenderCategory.MIXED,
        "court_name": "AUB Sports Center",
        "court_lat": Decimal("33.900165"),
        "court_lng": Decimal("35.479768"),
        "currency": "USD",
        "monthly_fee": Decimal("75.00"),
        "practice_hour": 20,
    },
    {
        "name": "Byblos Waves",
        "slug": "bybloswaves",
        "gender_category": Team.GenderCategory.MIXED,
        "court_name": "Byblos Arena",
        "court_lat": Decimal("34.122467"),
        "court_lng": Decimal("35.648632"),
        "currency": "USD",
        "monthly_fee": Decimal("72.00"),
        "practice_hour": 21,
    },
]

PLAYER_STATUS_CYCLE = [
    Player.Status.ELIGIBLE,
    Player.Status.ELIGIBLE,
    Player.Status.RECOVERING,
    Player.Status.ELIGIBLE,
    Player.Status.INJURED,
    Player.Status.ELIGIBLE,
]

RSVP_STATUS_CYCLE = [
    SessionRSVP.Status.GOING,
    SessionRSVP.Status.GOING,
    SessionRSVP.Status.GOING,
    SessionRSVP.Status.NOT_GOING,
    SessionRSVP.Status.GOING,
    SessionRSVP.Status.GOING,
]

ATTENDANCE_STATUS_CYCLE = [
    GameAttendance.Status.GOING,
    GameAttendance.Status.GOING,
    GameAttendance.Status.MAYBE,
    GameAttendance.Status.GOING,
    GameAttendance.Status.INJURED,
    GameAttendance.Status.NOT_GOING,
]

WEEKDAY_CYCLE = [
    PlayerAvailability.Weekday.MONDAY,
    PlayerAvailability.Weekday.TUESDAY,
    PlayerAvailability.Weekday.WEDNESDAY,
    PlayerAvailability.Weekday.THURSDAY,
    PlayerAvailability.Weekday.FRIDAY,
    PlayerAvailability.Weekday.SATURDAY,
]


class Command(BaseCommand):
    help = "Seed a rich multi-team demo dataset for manual testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Flush the database before seeding demo data.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Applying latest migrations before seeding demo data...")
        call_command("migrate", interactive=False, verbosity=0)

        if options["reset"]:
            self.stdout.write("Flushing existing database rows before seeding demo data...")
            call_command("flush", interactive=False, verbosity=0)

        now = timezone.now()
        account_rows = []
        team_contexts = []

        handlers = self._create_league_handlers(account_rows)

        for team_index, blueprint in enumerate(TEAM_BLUEPRINTS, start=1):
            team_context = self._create_team_dataset(
                blueprint=blueprint,
                team_index=team_index,
                now=now,
                handlers=handlers,
                account_rows=account_rows,
            )
            team_contexts.append(team_context)

        self._create_inter_team_competition(team_contexts, now)
        self._create_global_team_goals()

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write(f"Shared password for all seeded accounts: {DEMO_PASSWORD}")
        self.stdout.write(
            f"Created {Team.objects.count()} teams, {User.objects.count()} users, "
            f"{Player.objects.count()} player profiles, and {StaffTeamAssignment.objects.count()} team admins."
        )
        self.stdout.write("Seeded accounts:")
        for row in account_rows:
            self.stdout.write(
                f"- {row['team']}: {row['role']} | {row['name']} | {row['email']} | "
                f"approved={row['approved']} | status={row['status']} | gender={row['gender']}"
            )

    def _create_league_handlers(self, account_rows):
        handlers = []
        for index, gender in enumerate([Player.Gender.MALE, Player.Gender.FEMALE], start=1):
            handle = f"leaguehandler{index}"
            email = self._email_for(handle)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=DEMO_PASSWORD,
                first_name=handle,
            )
            handler = Player.objects.create(
                user=user,
                name=handle,
                email=email,
                role=Player.Role.LEAGUE_SYSTEM_HANDLER,
                team=None,
                gender=gender,
                is_approved=True,
            )
            handlers.append(handler)
            self._append_account_row(
                account_rows,
                team="League",
                role="league_handler",
                name=handle,
                email=email,
                approved=True,
                status=Player.Status.ELIGIBLE,
                gender=gender,
            )
        return handlers

    def _create_team_dataset(self, blueprint, team_index, now, handlers, account_rows):
        team = Team.objects.create(
            name=blueprint["name"],
            court_name=blueprint["court_name"],
            court_lat=blueprint["court_lat"],
            court_lng=blueprint["court_lng"],
            gender_category=blueprint["gender_category"],
        )

        TeamSubscriptionFee.objects.create(
            team=team,
            monthly_amount=blueprint["monthly_fee"],
            currency=blueprint["currency"],
        )

        for handler in handlers:
            Notification.objects.create(
                recipient=handler,
                title=f"{team.name} added to the league",
                message=f"{team.name} is ready for demo use with coaches, admins, and a full roster.",
                notification_type=Notification.Type.GENERAL,
            )

        admins = self._create_team_admins(team, blueprint["slug"], account_rows)
        coaches = self._create_team_coaches(team, blueprint, account_rows)
        players = self._create_team_players(team, blueprint, team_index, account_rows, now)

        practice = TrainingSession.objects.create(
            title=f"{team.name} Training Session",
            starts_at=now + timedelta(days=team_index, hours=blueprint["practice_hour"]),
            ends_at=now + timedelta(days=team_index, hours=blueprint["practice_hour"] + 2),
            location=team.court_name,
            session_type=TrainingSession.SessionType.PRACTICE,
            notes=f"{team.name} focus: serve receive, rotation discipline, and transition speed.",
        )
        review_session = TrainingSession.objects.create(
            title=f"{team.name} Match Review",
            starts_at=now + timedelta(days=team_index + 2, hours=blueprint["practice_hour"]),
            ends_at=now + timedelta(days=team_index + 2, hours=blueprint["practice_hour"] + 1),
            location=f"{team.name} Video Room",
            session_type=TrainingSession.SessionType.FRIENDLY,
            notes=f"{team.name} tactical review and opponent scouting.",
        )
        SessionPlan.objects.create(
            session=practice,
            title=f"{team.name} Practice Plan",
            drills="Warm-up\nServe receive patterns\nTempo offense\nSix-on-six finish",
        )

        for player_index, player in enumerate(players, start=1):
            SessionRSVP.objects.create(
                session=practice,
                player=player,
                status=RSVP_STATUS_CYCLE[player_index - 1],
            )
            PlayerAvailability.objects.create(
                player=player,
                weekday=WEEKDAY_CYCLE[player_index - 1],
                start_time=time(hour=16 + (player_index % 3)),
                end_time=time(hour=18 + (player_index % 3)),
                notes=f"{player.name} is most available after classes or work.",
            )
            PersonalSessionNote.objects.create(
                session=practice,
                player=player,
                content=f"{player.name} should focus on first contact quality and transition footwork.",
            )
            PlayerSorenessReport.objects.create(
                player=player,
                soreness_level=min(10, 2 + player_index),
                notes=f"{player.name} current recovery checkpoint for {team.name}.",
            )
            MembershipPayment.objects.create(
                player=player,
                amount=blueprint["monthly_fee"],
                period_month=now.month,
                period_year=now.year,
                method=MembershipPayment.Method.CARD if player_index % 2 else MembershipPayment.Method.CASH,
                status=MembershipPayment.Status.PAID if player_index <= 4 else MembershipPayment.Status.PENDING,
                card_last4=f"42{player_index:02d}" if player_index % 2 else "",
                paid_at=now - timedelta(days=player_index) if player_index <= 4 else None,
            )

        PersonalCalendarEvent.objects.create(
            player=players[0],
            title=f"{team.name} physio check",
            starts_at=now + timedelta(days=team_index + 1, hours=9),
            ends_at=now + timedelta(days=team_index + 1, hours=10),
            location="Medical Center",
            notes=f"Routine recovery follow-up for {players[0].name}.",
        )

        poll = SessionVotePoll.objects.create(
            title=f"{team.name} next training slot",
            description=f"Choose the better window for the next {team.name} session.",
            closes_at=now + timedelta(days=team_index + 2),
        )
        option_one = SessionVoteOption.objects.create(
            poll=poll,
            starts_at=now + timedelta(days=team_index + 7, hours=blueprint["practice_hour"]),
            location=team.court_name,
        )
        option_two = SessionVoteOption.objects.create(
            poll=poll,
            starts_at=now + timedelta(days=team_index + 8, hours=blueprint["practice_hour"] + 1),
            location=team.court_name,
        )
        for vote_index, player in enumerate(players[:4], start=1):
            SessionVote.objects.create(
                poll=poll,
                option=option_one if vote_index % 2 else option_two,
                player=player,
            )

        tryout = TryoutSession.objects.create(
            title=f"{team.name} tryout session",
            starts_at=now + timedelta(days=team_index + 10, hours=17),
            location=team.court_name,
            description=f"Open evaluation for prospective {team.name} players.",
        )
        TryoutCandidate.objects.create(
            tryout_session=tryout,
            name=f"{blueprint['slug']}candidate1",
            email=self._email_for(f"{blueprint['slug']}candidate1"),
            notes=f"Interested in joining {team.name} as a setter.",
        )
        TryoutCandidate.objects.create(
            tryout_session=tryout,
            name=f"{blueprint['slug']}candidate2",
            email=self._email_for(f"{blueprint['slug']}candidate2"),
            notes=f"Interested in joining {team.name} as an outside hitter.",
        )

        group = ChatGroup.objects.create(
            name=f"{team.name} Team Chat",
            created_by_player=coaches[0],
        )
        group.members.set([*coaches, *players])
        GroupMessage.objects.create(
            group=group,
            sender_player=coaches[0],
            sender_name=coaches[0].name,
            content=f"Welcome to the {team.name} team chat. Training details will be posted here.",
        )
        GroupMessage.objects.create(
            group=group,
            sender_player=players[0],
            sender_name=players[0].name,
            content=f"{players[0].name} checked in and is ready for the next session.",
        )

        Message.objects.create(
            player=players[0],
            sender=coaches[0],
            sender_is_admin=False,
            subject=f"{team.name} training target",
            content=f"{players[0].name}, focus on serve receive discipline in the next block.",
        )
        Message.objects.create(
            player=players[1],
            sender_user=admins[0],
            recipient_user=players[1].user,
            sender_is_admin=True,
            subject=f"{team.name} membership reminder",
            content=f"Please review the latest {team.name} payment and availability details.",
        )

        announcement = Announcement.objects.create(
            title=f"{team.name} weekly update",
            content=f"{team.name} has a full week of training, match prep, and admin follow-up queued.",
            created_by_player=coaches[0],
            notify_league_handler=True,
        )
        AnnouncementReply.objects.create(
            announcement=announcement,
            sender=players[0],
            content=f"{players[0].name} confirmed availability.",
        )
        AnnouncementReply.objects.create(
            announcement=announcement,
            sender=players[1],
            content=f"{players[1].name} asked for extra blocking reps.",
        )

        Notification.objects.create(
            recipient=players[0],
            title=f"{team.name} stats will be updated",
            message=f"New match stats are queued for {players[0].name} after the next fixture.",
            notification_type=Notification.Type.STATS_ADDED,
        )
        Notification.objects.create(
            recipient=players[1],
            title=f"{team.name} upcoming session",
            message=f"Please update your RSVP for {practice.title}.",
            notification_type=Notification.Type.TRAINING_CREATED,
        )
        Notification.objects.create(
            recipient=players[2],
            title=f"{team.name} review session",
            message=f"Video review for {review_session.title} is on the schedule.",
            notification_type=Notification.Type.GENERAL,
        )

        SupportTicket.objects.create(
            player=players[2],
            subject=f"{team.name} recovery planning",
            message=f"{players[2].name} requested adjusted workload for this week.",
            priority="medium",
        )

        return {
            "team": team,
            "slug": blueprint["slug"],
            "admins": admins,
            "coaches": coaches,
            "players": players,
            "currency": blueprint["currency"],
            "monthly_fee": blueprint["monthly_fee"],
            "gender_category": blueprint["gender_category"],
        }

    def _create_team_admins(self, team, team_slug, account_rows):
        admins = []
        for index in range(1, 3):
            handle = f"{team_slug}admin{index}"
            email = self._email_for(handle)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=DEMO_PASSWORD,
                first_name=handle,
                is_staff=True,
            )
            StaffTeamAssignment.objects.create(user=user, team=team, is_approved=True)
            admins.append(user)
            self._append_account_row(
                account_rows,
                team=team.name,
                role="club_admin",
                name=handle,
                email=email,
                approved=True,
                status="-",
                gender="-",
            )
        return admins

    def _create_team_coaches(self, team, blueprint, account_rows):
        coaches = []
        for index in range(1, 3):
            handle = f"{blueprint['slug']}coach{index}"
            email = self._email_for(handle)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=DEMO_PASSWORD,
                first_name=handle,
            )
            coach = Player.objects.create(
                user=user,
                name=handle,
                email=email,
                role=Player.Role.COACH,
                team=team,
                gender=self._gender_for_team(team.gender_category, index),
                is_approved=True,
            )
            coaches.append(coach)
            self._append_account_row(
                account_rows,
                team=team.name,
                role="coach",
                name=handle,
                email=email,
                approved=True,
                status=Player.Status.ELIGIBLE,
                gender=coach.gender,
            )
        return coaches

    def _create_team_players(self, team, blueprint, team_index, account_rows, now):
        players = []
        for index in range(1, 7):
            handle = f"{blueprint['slug']}player{index}"
            email = self._email_for(handle)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=DEMO_PASSWORD,
                first_name=handle,
            )
            player = Player.objects.create(
                user=user,
                name=handle,
                email=email,
                role=Player.Role.PLAYER,
                team=team,
                status=PLAYER_STATUS_CYCLE[index - 1],
                gender=self._gender_for_team(team.gender_category, index),
                is_approved=True,
                medical_certification_expiry=now.date() + timedelta(days=30 * (index + team_index)),
                contract_expiry=now.date() + timedelta(days=120 + 15 * (index + team_index)),
            )
            players.append(player)
            self._append_account_row(
                account_rows,
                team=team.name,
                role="player",
                name=handle,
                email=email,
                approved=True,
                status=player.status,
                gender=player.gender,
            )
        return players

    def _create_inter_team_competition(self, team_contexts, now):
        for pair_index, (home_index, away_index) in enumerate([(0, 1), (2, 3), (4, 5)], start=1):
            home_context = team_contexts[home_index]
            away_context = team_contexts[away_index]
            home_team = home_context["team"]
            away_team = away_context["team"]

            game = UpcomingGame.objects.create(
                home_team=home_team,
                away_team=away_team,
                scheduled_at=now + timedelta(days=pair_index * 4, hours=19),
                venue=home_team.court_name,
                notes=f"{home_team.name} hosts {away_team.name} in a seeded demo fixture.",
                gender_category=home_context["gender_category"],
            )
            for player_index, player in enumerate(home_context["players"], start=1):
                GameAttendance.objects.create(
                    game=game,
                    player=player,
                    status=ATTENDANCE_STATUS_CYCLE[player_index - 1],
                )
                GameRoster.objects.create(game=game, player=player)
            for player_index, player in enumerate(away_context["players"], start=1):
                GameAttendance.objects.create(
                    game=game,
                    player=player,
                    status=ATTENDANCE_STATUS_CYCLE[-player_index],
                )
                GameRoster.objects.create(game=game, player=player)

            self._create_match_series(
                team_context=home_context,
                opponent_context=away_context,
                now=now,
                day_offsets=[12 + pair_index, 5 + pair_index],
                scorelines=[(3, 1), (2, 3)],
            )
            self._create_match_series(
                team_context=away_context,
                opponent_context=home_context,
                now=now,
                day_offsets=[10 + pair_index, 3 + pair_index],
                scorelines=[(3, 2), (1, 3)],
            )

    def _create_match_series(self, team_context, opponent_context, now, day_offsets, scorelines):
        for match_index, (day_offset, scoreline) in enumerate(zip(day_offsets, scorelines), start=1):
            goals_for, goals_against = scoreline
            match = Match.objects.create(
                opponent=opponent_context["team"].name,
                opponent_team=opponent_context["team"],
                team=team_context["team"],
                date=(now - timedelta(days=day_offset)).date(),
                goals_for=goals_for,
                goals_against=goals_against,
                notes=(
                    f"{team_context['team'].name} seeded demo match {match_index} against "
                    f"{opponent_context['team'].name}."
                ),
                gender_category=team_context["gender_category"],
            )
            for player_index, player in enumerate(team_context["players"], start=1):
                PlayerMatchStat.objects.create(
                    match=match,
                    player=player,
                    goals=max(0, goals_for - (player_index % 3)),
                    interceptions=1 + (player_index % 4),
                    points=7 + player_index + (match_index * 2),
                    blocks=player_index % 3,
                    assists=2 + (player_index % 4),
                    aces=player_index % 2,
                    returns=3 + player_index,
                    most_recent_injury=(
                        "Managed ankle soreness" if player.status == Player.Status.INJURED else ""
                    ),
                )

    def _create_global_team_goals(self):
        for description, metric, target_value in [
            ("League target: 18 total aces this month", TeamGoal.Metric.ACES, 18),
            ("League target: 60 total points this month", TeamGoal.Metric.POINTS, 60),
            ("League target: 14 blocks this month", TeamGoal.Metric.BLOCKS, 14),
            ("League target: 22 assists this month", TeamGoal.Metric.ASSISTS, 22),
            ("League target: 20 returns this month", TeamGoal.Metric.RETURNS, 20),
            ("League target: 12 interceptions this month", TeamGoal.Metric.INTERCEPTIONS, 12),
        ]:
            TeamGoal.objects.create(
                description=description,
                metric=metric,
                target_value=target_value,
            )

    def _append_account_row(self, account_rows, team, role, name, email, approved, status, gender):
        account_rows.append(
            {
                "team": team,
                "role": role,
                "name": name,
                "email": email,
                "approved": "yes" if approved else "no",
                "status": status,
                "gender": gender,
            }
        )

    def _email_for(self, handle):
        return f"{handle}@{DEMO_DOMAIN}"

    def _gender_for_team(self, gender_category, index):
        if gender_category == Team.GenderCategory.MENS:
            return Player.Gender.MALE
        if gender_category == Team.GenderCategory.WOMENS:
            return Player.Gender.FEMALE
        return Player.Gender.MALE if index % 2 else Player.Gender.FEMALE
