import argparse
import csv
import json
import os
from collections import OrderedDict

import requests


class JiraClient:
    def __init__(self, base_url, email, api_token):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

    def create_issue(self, fields):
        url = f'{self.base_url}/rest/api/3/issue'
        response = self.session.post(url, json={'fields': fields}, timeout=30)
        response.raise_for_status()
        return response.json()['key']

    def get_transitions(self, issue_key):
        url = f'{self.base_url}/rest/api/3/issue/{issue_key}/transitions'
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json().get('transitions', [])

    def transition_issue(self, issue_key, target_names):
        transitions = self.get_transitions(issue_key)
        target_id = None
        normalized_targets = {name.strip().lower() for name in target_names}

        for t in transitions:
            transition_name = t.get('name', '').strip().lower()
            if transition_name in normalized_targets:
                target_id = t['id']
                break

        if not target_id:
            return False

        url = f'{self.base_url}/rest/api/3/issue/{issue_key}/transitions'
        payload = {'transition': {'id': target_id}}
        response = self.session.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return True


def parse_args():
    parser = argparse.ArgumentParser(description='Import user stories and tasks from CSV into Jira.')
    parser.add_argument('--csv', required=True, help='Path to CSV file.')
    parser.add_argument('--project-key', default=os.getenv('JIRA_PROJECT_KEY'), help='Jira project key.')
    parser.add_argument('--epic-summary', default=os.getenv('JIRA_EPIC_SUMMARY', 'Volley Project Backlog'))
    parser.add_argument(
        '--epic-description',
        default=os.getenv(
            'JIRA_EPIC_DESCRIPTION',
            'Backlog imported from CSV containing implemented and pending user stories.',
        ),
    )
    parser.add_argument('--epic-link-field', default=os.getenv('JIRA_EPIC_LINK_FIELD', 'customfield_10014'))
    parser.add_argument('--dry-run', action='store_true', help='Print actions without creating Jira issues.')
    parser.add_argument(
        '--apply-status',
        action='store_true',
        help='Attempt to transition issues to Done/To Do based on Workflow Status column.',
    )
    return parser.parse_args()


def load_assignee_map():
    raw = os.getenv('JIRA_ASSIGNEE_MAP_JSON', '{}')
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def group_rows_by_story(rows):
    grouped = OrderedDict()
    for row in rows:
        parent_id = row['Parent ID'].strip()
        story_text = row['User Story'].strip()
        key = (parent_id, story_text)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(row)

    for key in grouped:
        grouped[key] = sorted(grouped[key], key=lambda r: int(r['Task #']))

    return grouped


def build_story_description(parent_id, story, status):
    return (
        f'Imported from CSV.\n\n'
        f'External Parent ID: {parent_id}\n'
        f'User Story: {story}\n'
        f'Workflow Status: {status}'
    )


def build_subtask_description(task_row):
    return (
        f"Type: {task_row.get('Type', '').strip()}\n"
        f"Fibonacci Scale: {task_row.get('Fibonacci Scale', '').strip()}\n"
        f"Workflow Status: {task_row.get('Workflow Status', '').strip()}"
    )


def normalize_status(value):
    v = (value or '').strip().lower()
    if v in {'done', 'completed'}:
        return 'Done'
    if v in {'to do', 'todo', 'to-do', 'open'}:
        return 'To Do'
    return 'To Do'


def transition_to_target(jira, issue_key, target):
    if target == 'Done':
        candidates = ['Done', 'Resolved', 'Closed']
    else:
        candidates = ['To Do', 'Open', 'Backlog', 'Selected for Development']
    return jira.transition_issue(issue_key, candidates)


def main():
    args = parse_args()

    base_url = os.getenv('JIRA_BASE_URL')
    email = os.getenv('JIRA_EMAIL')
    token = os.getenv('JIRA_API_TOKEN')

    if not args.dry_run and (not base_url or not email or not token):
        raise RuntimeError('Missing Jira env vars: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN')

    if not args.dry_run and not args.project_key:
        raise RuntimeError('Missing project key. Use --project-key or set JIRA_PROJECT_KEY.')

    with open(args.csv, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    required_cols = {
        'Parent ID', 'User Story', 'Task #', 'Task Description', 'Type', 'Assignee', 'Fibonacci Scale', 'Workflow Status'
    }
    missing = required_cols.difference(reader.fieldnames or [])
    if missing:
        raise RuntimeError(f'Missing required columns in CSV: {sorted(missing)}')

    stories = group_rows_by_story(rows)
    assignee_map = load_assignee_map()

    jira = JiraClient(base_url, email, token) if not args.dry_run else None

    print(f'Loaded {len(rows)} tasks across {len(stories)} stories from CSV.')

    epic_key = 'DRYRUN-EPIC'
    if not args.dry_run:
        epic_fields = {
            'project': {'key': args.project_key},
            'summary': args.epic_summary,
            'description': args.epic_description,
            'issuetype': {'name': 'Epic'},
        }
        epic_key = jira.create_issue(epic_fields)
    print(f'Epic: {epic_key}')

    created_story_count = 0
    created_subtask_count = 0

    for (parent_id, story_text), task_rows in stories.items():
        status = normalize_status(task_rows[0].get('Workflow Status'))
        story_fields = {
            'project': {'key': args.project_key},
            'summary': story_text,
            'description': build_story_description(parent_id, story_text, status),
            'issuetype': {'name': 'Story'},
            args.epic_link_field: epic_key,
            'labels': [f'external-{parent_id.lower()}', f'status-{status.lower().replace(" ", "-")}'],
        }

        story_key = f'DRYRUN-{parent_id}'
        if not args.dry_run:
            story_key = jira.create_issue(story_fields)
            if args.apply_status:
                transitioned = transition_to_target(jira, story_key, status)
                if not transitioned:
                    print(f'WARN: Could not transition story {story_key} to {status}')
        print(f'Story: {story_key} [{status}]')
        created_story_count += 1

        for row in task_rows:
            task_status = normalize_status(row.get('Workflow Status'))
            assignee_name = row.get('Assignee', '').strip()
            account_id = assignee_map.get(assignee_name)

            subtask_fields = {
                'project': {'key': args.project_key},
                'summary': row['Task Description'].strip(),
                'description': build_subtask_description(row),
                'issuetype': {'name': 'Sub-task'},
                'parent': {'key': story_key},
                'labels': [
                    f'external-{parent_id.lower()}',
                    f'type-{row.get("Type", "").strip().lower().replace(" ", "-")}',
                    f'estimate-{row.get("Fibonacci Scale", "").strip() or "na"}',
                    f'status-{task_status.lower().replace(" ", "-")}',
                ],
            }

            if account_id:
                subtask_fields['assignee'] = {'id': account_id}

            subtask_key = f'DRYRUN-{parent_id}-{row["Task #"]}'
            if not args.dry_run:
                subtask_key = jira.create_issue(subtask_fields)
                if args.apply_status:
                    transitioned = transition_to_target(jira, subtask_key, task_status)
                    if not transitioned:
                        print(f'WARN: Could not transition sub-task {subtask_key} to {task_status}')

            assignee_display = assignee_name if assignee_name else 'Unassigned'
            print(f'  Sub-task: {subtask_key} | Assignee: {assignee_display} | Status: {task_status}')
            created_subtask_count += 1

    print(f'Created {created_story_count} stories and {created_subtask_count} sub-tasks.')


if __name__ == '__main__':
    main()
