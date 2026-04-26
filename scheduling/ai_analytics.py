import logging
import os
from hashlib import sha256
import json
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import GameAttendance, Match, Player, PlayerMatchStat, Team, UpcomingGame


logger = logging.getLogger(__name__)
GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
AI_SUMMARY_CACHE_SECONDS = 900

AI_METRIC_LABELS = {
    'goals': 'Goals',
    'points': 'Points',
    'assists': 'Assists',
    'blocks': 'Blocks',
    'aces': 'Aces',
    'interceptions': 'Interceptions',
    'returns': 'Returns',
}
HIGH_SORENESS_LEVEL = 7


def build_ai_analytics_context(user):
    profile = getattr(user, 'player_profile', None)
    if profile is None:
        return _build_generic_context()
    if profile.role == Player.Role.COACH:
        return _build_coach_context(profile)
    if profile.role == Player.Role.PLAYER:
        return _build_player_context(profile)
    if profile.role == Player.Role.LEAGUE_SYSTEM_HANDLER:
        return _build_league_handler_context(profile)
    return _build_generic_context()


def _build_league_handler_context(handler):
    teams = list(Team.objects.all().order_by('name'))
    all_matches = Match.objects.all()

    # Build standings: for each team, tally W/L/D and derive points (3/0/1)
    standings = []
    for team in teams:
        team_matches = all_matches.filter(team=team)
        wins = sum(1 for m in team_matches if m.result == Match.Result.WIN)
        losses = sum(1 for m in team_matches if m.result == Match.Result.LOSS)
        draws = sum(1 for m in team_matches if m.result == Match.Result.DRAW)
        played = wins + losses + draws
        points = wins * 3 + draws
        goals_for = sum(m.goals_for for m in team_matches)
        goals_against = sum(m.goals_against for m in team_matches)
        standings.append({
            'team': team,
            'played': played,
            'wins': wins,
            'losses': losses,
            'draws': draws,
            'points': points,
            'goals_for': goals_for,
            'goals_against': goals_against,
            'gd': goals_for - goals_against,
        })
    standings.sort(key=lambda r: (-r['points'], -r['gd'], r['team'].name))

    # Detect hot streaks: teams that won their last 3 matches
    hot_teams = []
    for entry in standings:
        last3 = list(
            all_matches.filter(team=entry['team']).order_by('-date', '-id')[:3]
        )
        if len(last3) == 3 and all(m.result == Match.Result.WIN for m in last3):
            hot_teams.append(entry['team'].name)

    total_teams = len(teams)
    total_matches = all_matches.count()

    if standings:
        leader = standings[0]
        leader_text = (
            f'{leader["team"].name} leads with {leader["points"]} point'
            f'{"s" if leader["points"] != 1 else ""} from '
            f'{leader["played"]} match{"es" if leader["played"] != 1 else ""}'
            f' ({leader["wins"]}W-{leader["losses"]}L-{leader["draws"]}D).'
        )
        analysis_summary = leader_text
        if hot_teams:
            analysis_summary += f' Current hot streak: {" and ".join(hot_teams)}.'
        insight_cards = [
            {
                'title': 'League leader',
                'value': f'{leader["team"].name}: {leader["points"]}pts',
                'body': leader_text,
            },
            {
                'title': 'Teams registered',
                'value': str(total_teams),
                'body': f'{total_matches} match result{"s" if total_matches != 1 else ""} recorded across all teams.',
            },
        ]
        if hot_teams:
            insight_cards.append({
                'title': 'On a hot streak',
                'value': ', '.join(hot_teams),
                'body': 'These teams won each of their last 3 recorded matches.',
            })
    else:
        analysis_summary = 'No teams are registered yet. Standings will populate once teams and matches are recorded.'
        insight_cards = [
            {
                'title': 'Teams registered',
                'value': '0',
                'body': 'Add teams through the team management page to unlock league-wide analytics.',
            },
        ]

    strategy_items = [
        f'Rank  Team                 Pts  W  L  D  Played  GD',
    ] + [
        f'{i + 1:>4}  {row["team"].name:<20} {row["points"]:>3}  '
        f'{row["wins"]:>1}  {row["losses"]:>1}  {row["draws"]:>1}  '
        f'{row["played"]:>6}  {row["gd"]:>+3}'
        for i, row in enumerate(standings)
    ]

    return {
        'page_title': 'AI Analytics Hub',
        'page_intro': 'League-wide standings and team performance overview.',
        'analysis_summary': analysis_summary,
        'analysis_source': 'Computed from recorded match results',
        'insight_cards': insight_cards,
        'action_items': [
            'Record match results for all teams to keep standings current.',
            'Use Opponent Analysis to compare any two teams head-to-head.',
        ] + (['Watch hot-streak teams: ' + ', '.join(hot_teams) + '.'] if hot_teams else []),
        'snapshot_items': [
            {'label': 'Teams', 'value': str(total_teams)},
            {'label': 'Matches recorded', 'value': str(total_matches)},
            {'label': 'League leader', 'value': standings[0]['team'].name if standings else 'N/A'},
        ],
        'is_ai_enabled': bool(os.getenv('GROQ_API_KEY')),
        'strategy_section_title': 'League Standings',
        'strategy_items': strategy_items,
        'secondary_section_title': '',
        'secondary_items': [],
    }


def generate_scouting_narrative(player):
    """Return an AI or rule-based scouting narrative string for a player."""
    stats_qs = (
        PlayerMatchStat.objects.filter(player=player)
        .select_related('match')
        .order_by('-match__date', '-match__id')
    )
    totals = _metric_totals(stats_qs)
    matches_played = stats_qs.count()
    strongest_metric, strongest_value = _pick_metric(totals, highest=True)
    focus_metric, focus_value = _pick_metric(totals, highest=False)
    latest_soreness = player.soreness_reports.first()
    latest_stat = stats_qs.first()
    latest_injury = next((s.most_recent_injury for s in stats_qs if s.most_recent_injury), '')

    fallback = (
        f'{player.name} has {matches_played} recorded match'
        f'{"es" if matches_played != 1 else ""}. '
        f'Strongest metric: {AI_METRIC_LABELS[strongest_metric]} ({strongest_value}). '
        f'Development area: {AI_METRIC_LABELS[focus_metric]} ({focus_value}). '
        + _player_recovery_sentence(latest_soreness, latest_injury)
    ) if matches_played else (
        f'{player.name} has no recorded match stats yet. '
        'Evaluation should rely on training observations.'
    )

    result = _generate_ai_summary(
        role_label='scouting report',
        stat_payload={
            'player_name': player.name,
            'position': getattr(player, 'position', None),
            'matches_played': matches_played,
            'strongest_metric': AI_METRIC_LABELS[strongest_metric],
            'strongest_value': strongest_value,
            'focus_metric': AI_METRIC_LABELS[focus_metric],
            'focus_value': focus_value,
            'latest_soreness': getattr(latest_soreness, 'soreness_level', None),
            'latest_injury': latest_injury or None,
            'latest_match': _match_payload(latest_stat.match) if latest_stat else None,
        },
        fallback_summary=fallback,
    )
    return result['text']


def generate_opponent_analysis(team1_name, t1_record, team2_name, t2_record):
    """Return an AI or rule-based opponent analysis string comparing two teams."""
    fallback_lines = [
        f'Head-to-head comparison: {team1_name} vs {team2_name}.',
        f'{team1_name}: {t1_record["wins"]}W-{t1_record["losses"]}L-{t1_record["draws"]}D '
        f'({t1_record["goals_for"]} GF / {t1_record["goals_against"]} GA).',
        f'{team2_name}: {t2_record["wins"]}W-{t2_record["losses"]}L-{t2_record["draws"]}D '
        f'({t2_record["goals_for"]} GF / {t2_record["goals_against"]} GA).',
    ]
    t1_pts = t1_record['wins'] * 3 + t1_record['draws']
    t2_pts = t2_record['wins'] * 3 + t2_record['draws']
    if t1_pts > t2_pts:
        fallback_lines.append(
            f'{team1_name} currently holds a points advantage ({t1_pts} vs {t2_pts}).'
        )
    elif t2_pts > t1_pts:
        fallback_lines.append(
            f'{team2_name} currently holds a points advantage ({t2_pts} vs {t1_pts}).'
        )
    else:
        fallback_lines.append('Both teams are level on points.')

    result = _generate_ai_summary(
        role_label='opponent analysis',
        stat_payload={
            'team1': team1_name,
            'team1_record': t1_record,
            'team1_points': t1_pts,
            'team2': team2_name,
            'team2_record': t2_record,
            'team2_points': t2_pts,
        },
        fallback_summary=' '.join(fallback_lines),
    )
    return result


def _build_generic_context():
    return {
        'page_title': 'AI Analytics Hub',
        'page_intro': 'AI insights are currently configured for player and coach accounts.',
        'analysis_summary': (
            'This hub is ready, but there is not enough role-specific sports data on this account '
            'to build recommendations yet.'
        ),
        'analysis_source': 'Built from live app data',
        'insight_cards': [
            {
                'title': 'Current coverage',
                'value': 'Players and coaches',
                'body': 'Switch into a player or coach account to see stat-driven feedback and focus areas.',
            },
        ],
        'action_items': [
            'Use a player account to review individual performance trends.',
            'Use a coach account to review team-level match and recovery signals.',
        ],
        'snapshot_items': [],
        'is_ai_enabled': bool(os.getenv('GROQ_API_KEY')),
        'strategy_section_title': '',
        'strategy_items': [],
        'secondary_section_title': '',
        'secondary_items': [],
    }


def _build_player_context(player):
    stats_queryset = (
        PlayerMatchStat.objects.filter(player=player)
        .select_related('match')
        .order_by('-match__date', '-match__id')
    )
    totals = _metric_totals(stats_queryset)
    strongest_metric, strongest_value = _pick_metric(totals, highest=True)
    focus_metric, focus_value = _pick_metric(totals, highest=False)
    latest_stat = stats_queryset.first()
    latest_soreness = player.soreness_reports.first()
    latest_injury = next((stat.most_recent_injury for stat in stats_queryset if stat.most_recent_injury), '')
    matches_played = stats_queryset.count()

    if matches_played == 0:
        fallback_summary = (
            'No recorded match stats are available yet. Once stats are logged, this page will highlight '
            'your best contribution area, your next focus metric, and any recovery flags.'
        )
        action_items = [
            'Ask your coach or league handler to record your next match stats.',
            'Log soreness regularly so recovery-based feedback can be included here.',
        ]
        insight_cards = [
            {
                'title': 'Match history',
                'value': '0 matches',
                'body': 'Your analytics feed starts once at least one match stat line is recorded.',
            },
            {
                'title': 'Recovery signal',
                'value': _format_soreness_value(latest_soreness),
                'body': 'Wellness data is already supported and will be blended into future recommendations.',
            },
        ]
    else:
        fallback_summary = (
            f'Your strongest recorded contribution so far is {AI_METRIC_LABELS[strongest_metric].lower()} '
            f'with a total of {strongest_value}. Your lowest-volume tracked area is '
            f'{AI_METRIC_LABELS[focus_metric].lower()} at {focus_value}, so that is the clearest place to '
            f'focus next. {_player_recovery_sentence(latest_soreness, latest_injury)}'
        )
        action_items = _player_action_items(
            focus_metric=focus_metric,
            latest_soreness=latest_soreness,
            latest_stat=latest_stat,
        )
        insight_cards = [
            {
                'title': 'Best contribution',
                'value': f'{AI_METRIC_LABELS[strongest_metric]}: {strongest_value}',
                'body': 'This is the stat where your logged production is currently strongest.',
            },
            {
                'title': 'Next focus',
                'value': f'{AI_METRIC_LABELS[focus_metric]}: {focus_value}',
                'body': 'This is the weakest recorded metric in your current match history.',
            },
            {
                'title': 'Last logged match',
                'value': _match_label(latest_stat.match) if latest_stat else 'No match yet',
                'body': _last_match_body(latest_stat),
            },
            {
                'title': 'Recovery status',
                'value': _format_soreness_value(latest_soreness),
                'body': latest_injury or 'No recent injury note is recorded in your stat history.',
            },
        ]

    summary = _generate_ai_summary(
        role_label='player',
        stat_payload={
            'player_name': player.name,
            'matches_played': matches_played,
            'strongest_metric': AI_METRIC_LABELS[strongest_metric],
            'strongest_value': strongest_value,
            'focus_metric': AI_METRIC_LABELS[focus_metric],
            'focus_value': focus_value,
            'latest_soreness': getattr(latest_soreness, 'soreness_level', None),
            'latest_injury': latest_injury or None,
            'latest_match': _match_payload(latest_stat.match) if latest_stat else None,
        },
        fallback_summary=fallback_summary,
    )

    return {
        'page_title': 'AI Analytics Hub',
        'page_intro': 'Personalized performance guidance built from your recorded match and recovery data.',
        'analysis_summary': summary['text'],
        'analysis_source': summary['source'],
        'insight_cards': insight_cards,
        'action_items': action_items,
        'snapshot_items': [
            {'label': 'Matches logged', 'value': str(matches_played)},
            {'label': 'Strongest metric', 'value': AI_METRIC_LABELS[strongest_metric]},
            {'label': 'Focus metric', 'value': AI_METRIC_LABELS[focus_metric]},
            {'label': 'Latest soreness', 'value': _format_soreness_value(latest_soreness)},
        ],
        'is_ai_enabled': summary['is_ai_enabled'],
        'strategy_section_title': 'Readiness Focus',
        'strategy_items': _player_readiness_items(
            focus_metric=focus_metric,
            latest_soreness=latest_soreness,
            latest_injury=latest_injury,
        ),
        'secondary_section_title': 'Next Match Prep',
        'secondary_items': _player_next_match_prep(player, focus_metric, latest_soreness),
    }


def _build_coach_context(coach):
    team = coach.team
    matches = Match.objects.none() if team is None else Match.objects.filter(team=team)
    stats_queryset = PlayerMatchStat.objects.none() if team is None else PlayerMatchStat.objects.filter(
        match__team=team,
        player__team=team,
    )

    latest_match = matches.order_by('-date', '-id').first()
    season_totals = _metric_totals(stats_queryset)
    focus_metric, focus_value = _pick_metric(season_totals, highest=False)
    strongest_metric, strongest_value = _pick_metric(season_totals, highest=True)

    # --- Our team W/L/D ---
    all_our_matches = list(matches)
    our_wins = sum(1 for m in all_our_matches if m.result == Match.Result.WIN)
    our_losses = sum(1 for m in all_our_matches if m.result == Match.Result.LOSS)
    our_draws = sum(1 for m in all_our_matches if m.result == Match.Result.DRAW)
    our_record = {'wins': our_wins, 'losses': our_losses, 'draws': our_draws}

    # --- Upcoming opponent ---
    next_game = _next_game_for_team(team) if team is not None else None
    opponent_team_obj = None
    if next_game is not None and team is not None:
        opponent_team_obj = (
            next_game.away_team if next_game.home_team_id == team.id else next_game.home_team
        )

    # --- Opponent team stats ---
    opp_strongest_metric = opp_weakest_metric = None
    opp_strongest_value = opp_weakest_value = 0
    opp_record = None
    has_opponent_stats = False
    if opponent_team_obj is not None:
        opp_matches = list(Match.objects.filter(team=opponent_team_obj))
        if opp_matches:
            has_opponent_stats = True
            opp_stats_qs = PlayerMatchStat.objects.filter(
                player__team=opponent_team_obj,
                match__team=opponent_team_obj,
            )
            opp_totals = _metric_totals(opp_stats_qs)
            opp_strongest_metric, opp_strongest_value = _pick_metric(opp_totals, highest=True)
            opp_weakest_metric, opp_weakest_value = _pick_metric(opp_totals, highest=False)
            opp_wins = sum(1 for m in opp_matches if m.result == Match.Result.WIN)
            opp_losses = sum(1 for m in opp_matches if m.result == Match.Result.LOSS)
            opp_draws = sum(1 for m in opp_matches if m.result == Match.Result.DRAW)
            opp_record = {'wins': opp_wins, 'losses': opp_losses, 'draws': opp_draws}

    # --- AI opponent brief ---
    opponent_name = getattr(opponent_team_obj, 'name', None)
    if team is None:
        brief_fallback = 'Your coach account is not linked to a team yet.'
        brief_payload = {'status': 'no_team'}
    elif next_game is None:
        brief_fallback = (
            f'No upcoming game is scheduled for {team.name}. '
            f'Focus on improving {AI_METRIC_LABELS[focus_metric].lower()} in the next training sessions.'
        )
        brief_payload = {
            'status': 'no_upcoming_game',
            'team': team.name,
            'focus_metric': AI_METRIC_LABELS[focus_metric],
        }
    else:
        past_meetings = list(
            Match.objects.filter(team=team, opponent_team=opponent_team_obj).order_by('-date', '-id')
        )
        h2h_wins = sum(1 for m in past_meetings if m.result == Match.Result.WIN)
        h2h_losses = sum(1 for m in past_meetings if m.result == Match.Result.LOSS)
        h2h_draws = sum(1 for m in past_meetings if m.result == Match.Result.DRAW)
        brief_fallback = (
            f'Next opponent is {opponent_name} on {next_game.scheduled_at:%b %d, %Y}. '
            f'Head-to-head record: {h2h_wins}W-{h2h_losses}L-{h2h_draws}D. '
            f'Focus on improving {AI_METRIC_LABELS[focus_metric].lower()} before this match.'
        )
        brief_payload = {
            'our_team': team.name,
            'our_strength': AI_METRIC_LABELS[strongest_metric],
            'our_weakness': AI_METRIC_LABELS[focus_metric],
            'our_record': f'{our_wins}W-{our_losses}L-{our_draws}D',
            'opponent': opponent_name,
            'match_date': next_game.scheduled_at.isoformat(),
            'h2h_wins': h2h_wins,
            'h2h_losses': h2h_losses,
            'h2h_draws': h2h_draws,
        }
        if has_opponent_stats:
            brief_payload['opponent_strength'] = AI_METRIC_LABELS[opp_strongest_metric]
            brief_payload['opponent_weakness'] = AI_METRIC_LABELS[opp_weakest_metric]
            brief_payload['opponent_record'] = (
                f'{opp_record["wins"]}W-{opp_record["losses"]}L-{opp_record["draws"]}D'
            )

    brief_result = _generate_ai_summary(
        role_label='coach opponent brief',
        stat_payload=brief_payload,
        fallback_summary=brief_fallback,
    )

    # --- AI-Recommended Focus Areas ---
    if team is None:
        focus_areas = ['Link this coach account to a team to unlock team-level analytics.']
    elif not all_our_matches:
        focus_areas = [
            'Record your first match to populate AI-recommended focus areas.',
            'Set up player stat tracking so metric-based guidance can appear here.',
        ]
    else:
        focus_areas = _coach_action_items(
            focus_metric=focus_metric,
            soreness_watch=[],
            latest_match=latest_match,
        )

    return {
        'page_title': 'AI Analytics Hub',
        'page_intro': 'Team-level match intelligence built from recorded results and player stats.',
        'is_coach_view': True,
        # Opponent Brief
        'opponent_brief_text': brief_result['text'],
        'opponent_brief_source': brief_result['source'],
        'opponent_brief_is_ai': brief_result['is_ai_enabled'],
        'opponent_name': opponent_name or '',
        'next_game': next_game,
        # Latest Result
        'latest_result_value': _match_result_badge(latest_match),
        'latest_result_body': _match_result_body(latest_match),
        # AI-Recommended Focus Areas
        'focus_areas': focus_areas,
        # Our Team
        'our_team_name': getattr(team, 'name', 'Your Team'),
        'our_strength_metric': AI_METRIC_LABELS[strongest_metric],
        'our_strength_value': strongest_value,
        'our_weakness_metric': AI_METRIC_LABELS[focus_metric],
        'our_weakness_value': focus_value,
        'our_record': our_record,
        # Opponent Team
        'has_opponent_stats': has_opponent_stats,
        'opponent_strength_metric': AI_METRIC_LABELS[opp_strongest_metric] if opp_strongest_metric else None,
        'opponent_strength_value': opp_strongest_value,
        'opponent_weakness_metric': AI_METRIC_LABELS[opp_weakest_metric] if opp_weakest_metric else None,
        'opponent_weakness_value': opp_weakest_value,
        'opp_record': opp_record,
        # Generic keys so the template else-branch never KeyErrors
        'is_ai_enabled': brief_result['is_ai_enabled'],
        'analysis_summary': '',
        'analysis_source': '',
        'insight_cards': [],
        'action_items': focus_areas,
        'snapshot_items': [],
        'strategy_section_title': '',
        'strategy_items': [],
        'secondary_section_title': '',
        'secondary_items': [],
    }


def _metric_totals(stats_queryset):
    totals = stats_queryset.aggregate(
        total_goals=Coalesce(Sum('goals'), Value(0)),
        total_points=Coalesce(Sum('points'), Value(0)),
        total_assists=Coalesce(Sum('assists'), Value(0)),
        total_blocks=Coalesce(Sum('blocks'), Value(0)),
        total_aces=Coalesce(Sum('aces'), Value(0)),
        total_interceptions=Coalesce(Sum('interceptions'), Value(0)),
        total_returns=Coalesce(Sum('returns'), Value(0)),
    )
    return {
        'goals': totals['total_goals'],
        'points': totals['total_points'],
        'assists': totals['total_assists'],
        'blocks': totals['total_blocks'],
        'aces': totals['total_aces'],
        'interceptions': totals['total_interceptions'],
        'returns': totals['total_returns'],
    }


def _pick_metric(metric_totals, highest):
    if highest:
        ranked_metrics = sorted(
            metric_totals.items(),
            key=lambda item: (-item[1], AI_METRIC_LABELS[item[0]].lower()),
        )
    else:
        ranked_metrics = sorted(
            metric_totals.items(),
            key=lambda item: (item[1], AI_METRIC_LABELS[item[0]].lower()),
        )
    return ranked_metrics[0]


def _player_action_items(focus_metric, latest_soreness, latest_stat):
    items = [
        f'Prioritize drills that create more {AI_METRIC_LABELS[focus_metric].lower()} in your next session.',
    ]
    if latest_stat is not None:
        items.append(f'Review the last recorded match against {latest_stat.match.opponent} for repeatable patterns.')
    if latest_soreness is not None and latest_soreness.soreness_level >= HIGH_SORENESS_LEVEL:
        items.append('Your soreness is elevated, so balance improvement work with recovery before the next session.')
    return items


def _coach_action_items(focus_metric, soreness_watch, latest_match):
    items = [
        f'Build the next team session around improving {AI_METRIC_LABELS[focus_metric].lower()}.',
    ]
    if latest_match is not None:
        items.append(f'Use the latest match against {latest_match.opponent} as the review baseline.')
    if soreness_watch:
        watched_names = ', '.join(player.name for player, _ in soreness_watch[:3])
        items.append(f'Check workload and recovery for {watched_names}.')
    return items


def _player_readiness_items(focus_metric, latest_soreness, latest_injury):
    items = [
        f'Build your next self-review around creating more {AI_METRIC_LABELS[focus_metric].lower()}.',
    ]
    if latest_soreness is not None and latest_soreness.soreness_level >= HIGH_SORENESS_LEVEL:
        items.append('Recovery is elevated right now, so reduce unnecessary load before adding more volume.')
    if latest_injury:
        items.append(f'Keep the latest injury note in mind during training: {latest_injury}.')
    else:
        items.append('No recent injury note is logged, so focus on consistent execution and recovery tracking.')
    return items


def _player_next_match_prep(player, focus_metric, latest_soreness):
    next_game = _next_game_for_team(player.team)
    if next_game is None or player.team is None:
        return [
            'No upcoming game is scheduled yet, so keep building consistency in training and stats logging.',
        ]

    opponent = next_game.away_team if next_game.home_team_id == player.team_id else next_game.home_team
    attendance = GameAttendance.objects.filter(game=next_game, player=player).first()
    attendance_text = attendance.get_status_display() if attendance is not None else 'Not submitted'
    items = [
        f'Next match: {opponent.name} on {next_game.scheduled_at:%b %d, %Y at %H:%M}.',
        f'Your current game attendance status is {attendance_text}.',
        f'Before the match, emphasize actions that improve your {AI_METRIC_LABELS[focus_metric].lower()}.',
    ]
    if latest_soreness is not None and latest_soreness.soreness_level >= HIGH_SORENESS_LEVEL:
        items.append('Your recovery signal is elevated, so treat workload and warm-up quality as part of match prep.')
    return items


def _coach_upcoming_brief(team, focus_metric, soreness_watch):
    next_game = _next_game_for_team(team)
    if next_game is None:
        return [
            'No upcoming game is scheduled yet, so the coach brief will expand once the next opponent is posted.',
            f'In the meantime, keep practice centered on improving {AI_METRIC_LABELS[focus_metric].lower()}.',
        ]

    opponent = next_game.away_team if next_game.home_team_id == team.id else next_game.home_team
    past_meetings = Match.objects.filter(team=team, opponent=opponent.name).order_by('-date', '-id')
    confirmed_attendance = GameAttendance.objects.filter(
        game=next_game,
        player__team=team,
        status=GameAttendance.Status.GOING,
    ).count()
    injured_attendance = GameAttendance.objects.filter(
        game=next_game,
        player__team=team,
        status=GameAttendance.Status.INJURED,
    ).count()

    brief_items = [
        f'Next opponent: {opponent.name} on {next_game.scheduled_at:%b %d, %Y at %H:%M}.',
    ]
    if next_game.venue:
        brief_items.append(f'Venue: {next_game.venue}.')

    if past_meetings.exists():
        wins = sum(1 for match in past_meetings if match.result == Match.Result.WIN)
        losses = sum(1 for match in past_meetings if match.result == Match.Result.LOSS)
        draws = sum(1 for match in past_meetings if match.result == Match.Result.DRAW)
        latest_meeting = past_meetings.first()
        brief_items.append(
            f'Past record vs {opponent.name}: {wins}W-{losses}L-{draws}D across {past_meetings.count()} logged meeting'
            f'{"s" if past_meetings.count() != 1 else ""}.'
        )
        brief_items.append(
            f'Latest meeting finished {latest_meeting.goals_for}-{latest_meeting.goals_against} '
            f'({latest_meeting.result.upper()}).'
        )
    else:
        brief_items.append(
            f'No prior logged match exists against {opponent.name}, so preparation should lean on your own team trends first.'
        )

    brief_items.append(
        f'Primary tactical focus: raise team {AI_METRIC_LABELS[focus_metric].lower()} output before this match.'
    )
    brief_items.append(
        f'Confirmed availability is {confirmed_attendance} player{"s" if confirmed_attendance != 1 else ""}'
        f' with {injured_attendance} marked injured.'
    )
    if soreness_watch:
        watched_names = ', '.join(player.name for player, _ in soreness_watch[:3])
        brief_items.append(f'High-soreness watch list before kickoff: {watched_names}.')
    else:
        brief_items.append('No high-soreness watch list is currently active from the latest reports.')

    return brief_items


def _coach_tactical_recommendations(team, matches, focus_metric, soreness_watch):
    if team is None:
        return []

    latest_matches = list(matches.order_by('-date', '-id')[:3])
    recommendations = [
        f'Center the next match plan on improving team {AI_METRIC_LABELS[focus_metric].lower()}.',
    ]

    if latest_matches:
        recent_losses = sum(1 for match in latest_matches if match.result == Match.Result.LOSS)
        if recent_losses >= 2:
            recommendations.append('Shorten review loops and simplify rotations, because recent results show pressure points late in matches.')
        elif any(match.result == Match.Result.WIN for match in latest_matches):
            recommendations.append('Carry over the strongest recent patterns from your latest win and repeat them early.')

        avg_goals_against = sum(match.goals_against for match in latest_matches) / len(latest_matches)
        if avg_goals_against >= 2:
            recommendations.append('Prioritize defensive organization early, because recent opponents are scoring at a meaningful rate.')

    next_game = _next_game_for_team(team)
    if next_game is not None:
        confirmed = GameAttendance.objects.filter(
            game=next_game,
            player__team=team,
            status=GameAttendance.Status.GOING,
        ).count()
        maybe_count = GameAttendance.objects.filter(
            game=next_game,
            player__team=team,
            status=GameAttendance.Status.MAYBE,
        ).count()
        if maybe_count > 0:
            recommendations.append(f'Lock down availability before match day: {confirmed} confirmed and {maybe_count} still undecided.')

    if soreness_watch:
        watched_names = ', '.join(player.name for player, _ in soreness_watch[:2])
        recommendations.append(f'Adjust workload for {watched_names} so recovery risk does not undercut the game plan.')

    return recommendations[:4]


def _next_game_for_team(team):
    if team is None:
        return None

    cutoff = timezone.now() - timedelta(hours=12)
    return (
        UpcomingGame.objects
        .filter(Q(home_team=team) | Q(away_team=team), scheduled_at__gte=cutoff)
        .select_related('home_team', 'away_team')
        .order_by('scheduled_at', 'id')
        .first()
    )


def _player_recovery_sentence(latest_soreness, latest_injury):
    if latest_soreness is not None and latest_soreness.soreness_level >= HIGH_SORENESS_LEVEL:
        return f'Your latest soreness report is {latest_soreness.soreness_level}/10, so recovery should stay part of the plan.'
    if latest_injury:
        return f'The latest injury note on file is "{latest_injury}", so keep that in mind while progressing workload.'
    return 'No major recovery warning is visible in the latest logged data.'


def _coach_recovery_sentence(soreness_watch):
    if not soreness_watch:
        return 'No players are currently on a high-soreness watch from the latest reports.'
    watched_names = ', '.join(player.name for player, _ in soreness_watch[:3])
    return f'High soreness is currently showing up for {watched_names}.'


def _last_match_body(latest_stat):
    if latest_stat is None:
        return 'No player stat line has been recorded yet.'
    return (
        f'Logged line: {latest_stat.points} points, {latest_stat.aces} aces, '
        f'{latest_stat.blocks} blocks, {latest_stat.assists} assists.'
    )


def _format_soreness_value(report):
    if report is None:
        return 'No report'
    return f'{report.soreness_level}/10'


def _match_label(match):
    return f'{match.opponent} on {match.date:%b %d, %Y}'


def _coach_result_sentence(match):
    if match is None:
        return 'no result yet because no matches are on file'
    return f'a {match.result.upper()} against {match.opponent} by a {match.goals_for}-{match.goals_against} score'


def _match_result_badge(match):
    if match is None:
        return 'No match yet'
    return match.result.upper()


def _match_result_body(match):
    if match is None:
        return 'Record a match to unlock team-level AI result summaries.'
    return f'{match.goals_for}-{match.goals_against} vs {match.opponent} on {match.date:%b %d, %Y}.'


def _coach_watch_list_body(soreness_watch):
    if not soreness_watch:
        return 'No high-soreness flags are present in the latest player reports.'
    return ', '.join(f'{player.name} ({report.soreness_level}/10)' for player, report in soreness_watch[:3])


def _match_payload(match):
    if match is None:
        return None
    return {
        'opponent': match.opponent,
        'date': match.date.isoformat(),
        'goals_for': match.goals_for,
        'goals_against': match.goals_against,
        'result': match.result,
    }


def _generate_ai_summary(role_label, stat_payload, fallback_summary):
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        return {
            'text': fallback_summary,
            'source': 'Based on recorded stats',
            'is_ai_enabled': False,
        }

    try:
        from openai import OpenAI
    except ImportError:
        return {
            'text': fallback_summary,
            'source': 'Based on recorded stats',
            'is_ai_enabled': False,
        }

    payload_digest = sha256(
        json.dumps(
            {
                'role_label': role_label,
                'stat_payload': stat_payload,
                'model': os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'),
            },
            sort_keys=True,
            default=str,
        ).encode('utf-8')
    ).hexdigest()
    cache_key = f'ai_summary:{payload_digest}'
    cached_summary = cache.get(cache_key)
    if cached_summary is not None:
        return cached_summary

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
        )
        response = client.responses.create(
            model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'),
            input=(
                f'You are generating a short volleyball analytics note for a {role_label}. '
                'Use only the supplied stats. Keep the tone practical and specific. '
                'Return 3 to 4 sentences with no bullet points.\n\n'
                f'Stats payload: {stat_payload}'
            ),
            max_output_tokens=180,
        )
        summary_text = (getattr(response, 'output_text', '') or '').strip()
        if summary_text:
            result = {
                'text': summary_text,
                'source': 'AI-generated',
                'is_ai_enabled': True,
            }
            cache.set(cache_key, result, AI_SUMMARY_CACHE_SECONDS)
            return result
    except Exception:
        logger.exception('Groq AI analytics summary generation failed')

    return {
        'text': fallback_summary,
        'source': 'Based on recorded stats',
        'is_ai_enabled': False,
    }
