import logging
import os

from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce

from .models import Match, Player, PlayerMatchStat


logger = logging.getLogger(__name__)

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
    return _build_generic_context()


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
        'is_ai_enabled': bool(os.getenv('OPENAI_API_KEY')),
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
    }


def _build_coach_context(coach):
    team = coach.team
    matches = Match.objects.none() if team is None else Match.objects.filter(team=team)
    players = Player.objects.none() if team is None else Player.objects.filter(
        role=Player.Role.PLAYER,
        is_active=True,
        team=team,
    )
    stats_queryset = PlayerMatchStat.objects.none() if team is None else PlayerMatchStat.objects.filter(
        match__team=team,
        player__team=team,
    )

    latest_match = matches.order_by('-date', '-id').first()
    season_totals = _metric_totals(stats_queryset)
    focus_metric, focus_value = _pick_metric(season_totals, highest=False)
    strongest_metric, strongest_value = _pick_metric(season_totals, highest=True)
    top_producer = (
        players
        .annotate(total_points=Coalesce(Sum('match_stats__points', filter=Q(match_stats__match__team=team)), Value(0)))
        .order_by('-total_points', 'name')
        .first()
        if team is not None
        else None
    )
    soreness_watch = []
    for player in players:
        latest_report = player.soreness_reports.first()
        if latest_report is not None and latest_report.soreness_level >= HIGH_SORENESS_LEVEL:
            soreness_watch.append((player, latest_report))

    if team is None:
        fallback_summary = (
            'Your coach account is not linked to a team yet, so the analytics hub cannot aggregate match '
            'or player data.'
        )
        action_items = ['Link this coach account to a team to unlock team-level AI summaries.']
    elif not matches.exists():
        fallback_summary = (
            'No team matches have been recorded yet. Once a match and player stats are logged, this page '
            'will summarize results, identify weaker team metrics, and flag recovery concerns.'
        )
        action_items = [
            'Record your next match to populate the AI summary.',
            'Have players log soreness so recovery alerts can appear here.',
        ]
    else:
        fallback_summary = (
            f'The latest recorded result is {_coach_result_sentence(latest_match)}. The team is producing most '
            f'in {AI_METRIC_LABELS[strongest_metric].lower()} ({strongest_value}) and least in '
            f'{AI_METRIC_LABELS[focus_metric].lower()} ({focus_value}), which makes that the clearest team focus. '
            f'{_coach_recovery_sentence(soreness_watch)}'
        )
        action_items = _coach_action_items(
            focus_metric=focus_metric,
            soreness_watch=soreness_watch,
            latest_match=latest_match,
        )

    summary = _generate_ai_summary(
        role_label='coach',
        stat_payload={
            'team_name': getattr(team, 'name', None),
            'match_count': matches.count(),
            'latest_match': _match_payload(latest_match) if latest_match else None,
            'strongest_metric': AI_METRIC_LABELS[strongest_metric],
            'strongest_value': strongest_value,
            'focus_metric': AI_METRIC_LABELS[focus_metric],
            'focus_value': focus_value,
            'top_producer': getattr(top_producer, 'name', None),
            'top_producer_points': getattr(top_producer, 'total_points', None),
            'soreness_watch_count': len(soreness_watch),
        },
        fallback_summary=fallback_summary,
    )

    insight_cards = [
        {
            'title': 'Latest result',
            'value': _match_result_badge(latest_match),
            'body': _match_result_body(latest_match),
        },
        {
            'title': 'Team strength',
            'value': f'{AI_METRIC_LABELS[strongest_metric]}: {strongest_value}',
            'body': 'This is the highest-volume team metric in the recorded season totals.',
        },
        {
            'title': 'Primary focus',
            'value': f'{AI_METRIC_LABELS[focus_metric]}: {focus_value}',
            'body': 'This is the lowest recorded team metric and the clearest improvement target.',
        },
        {
            'title': 'Recovery watch',
            'value': f'{len(soreness_watch)} player{"s" if len(soreness_watch) != 1 else ""}',
            'body': _coach_watch_list_body(soreness_watch),
        },
    ]

    return {
        'page_title': 'AI Analytics Hub',
        'page_intro': 'Team-level match intelligence built from recorded results, player stats, and soreness reports.',
        'analysis_summary': summary['text'],
        'analysis_source': summary['source'],
        'insight_cards': insight_cards,
        'action_items': action_items,
        'snapshot_items': [
            {'label': 'Team', 'value': getattr(team, 'name', 'Not assigned')},
            {'label': 'Matches logged', 'value': str(matches.count())},
            {'label': 'Active players', 'value': str(players.count())},
            {'label': 'Top scorer', 'value': getattr(top_producer, 'name', 'Not enough data')},
            {'label': 'Recovery watch', 'value': str(len(soreness_watch))},
        ],
        'is_ai_enabled': summary['is_ai_enabled'],
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
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return {
            'text': fallback_summary,
            'source': 'Built from live stats',
            'is_ai_enabled': False,
        }

    try:
        from openai import OpenAI
    except ImportError:
        return {
            'text': fallback_summary,
            'source': 'Built from live stats (OpenAI SDK not installed)',
            'is_ai_enabled': False,
        }

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
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
            return {
                'text': summary_text,
                'source': 'Generated with OpenAI',
                'is_ai_enabled': True,
            }
    except Exception:
        logger.exception('AI analytics summary generation failed')

    return {
        'text': fallback_summary,
        'source': 'Built from live stats',
        'is_ai_enabled': False,
    }
