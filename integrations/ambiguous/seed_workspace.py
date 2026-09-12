#!/usr/bin/env python3
"""Preview or seed authored background work without changing live procurement tasks."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.ambiguous.bridge import API, BridgeError, CONTRACTOR, WORKSPACE, identifier, save

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = ROOT / 'examples/workspace/residential-projects.json'


def marker(seed, key):
    return f'<!-- takeoff-workspace-seed:{seed}:{key} -->'


def load_fixture(path):
    fixture = json.loads(path.read_text())
    keys = set()
    for project in fixture['projects']:
        if project['key'] in keys:
            raise BridgeError('Duplicate scenario project key')
        keys.add(project['key'])
        task_keys = set()
        for task in project['tasks']:
            if task['key'] in task_keys or task['status'] not in ('todo', 'in_progress', 'done'):
                raise BridgeError('Invalid scenario task key or status')
            task_keys.add(task['key'])
            if task['owner'] not in ('contractor', 'unassigned'):
                raise BridgeError('Background task cannot be assigned to an agent')
    return fixture


def project_body(fixture, project):
    return {'name': project['name'], 'visibility': 'workspace', 'color': project['color'],
            'description': project['description'] + '\n\n' + marker(fixture['id'], project['key'])}


def task_body(fixture, project, task, project_id):
    body = {key: task[key] for key in ('title', 'description', 'status', 'priority', 'start_date', 'due_date')}
    body['description'] += '\n\n' + marker(fixture['id'], project['key'] + '/' + task['key'])
    body.update(project_id=project_id, subscriber_ids=[CONTRACTOR])
    if task['owner'] == 'contractor':
        body['assignee_id'] = CONTRACTOR
    return body


def pages(api, path, **query):
    rows, offset = [], 0
    while True:
        response = api.call(path, limit=100, offset=offset, **query)
        data = response['data']
        rows.extend(data)
        if not response.get('has_more'):
            return rows
        if not data:
            raise BridgeError('Pagination did not advance')
        offset += len(data)


def match(rows, tag, title_key, title):
    found = [row for row in rows if tag in (row.get('description') or '')]
    if len(found) > 1:
        raise BridgeError('Duplicate seed markers require manual reconciliation')
    if found:
        return found[0]
    if any(row.get(title_key) == title for row in rows):
        raise BridgeError('An unmarked resource already has the proposed name; preserve it and review')
    return None


class Seeder:
    def __init__(self, api, fixture, journal_path, apply=False):
        self.api, self.fixture, self.path, self.apply = api, fixture, journal_path, apply
        self.journal = json.loads(journal_path.read_text()) if journal_path.exists() else {
            'seed_id': fixture['id'], 'workspace_id': WORKSPACE, 'operations': {}}
        if self.journal.get('seed_id') != fixture['id'] or self.journal.get('workspace_id') != WORKSPACE:
            raise BridgeError('Journal belongs to another scenario or workspace')
        self.operations = []

    def mutation(self, key, path, method, body):
        if self.journal['operations'].get(key, {}).get('status') == 'sending':
            raise BridgeError('Uncertain prior write was not found remotely; review before retrying')
        self.journal['operations'][key] = {'status': 'sending', 'path': path, 'method': method}
        save(self.path, self.journal)
        result = self.api.call(path, method, body)
        self.journal['operations'][key]['status'] = 'sent'
        save(self.path, self.journal)
        return result

    def reconcile(self, key, resource_id):
        if self.apply:
            self.journal['operations'][key] = {'status': 'verified', 'id': resource_id}
            save(self.path, self.journal)

    def membership(self, project_id, project_name):
        key = 'member:' + project_id
        members = pages(self.api, f'/api/projects/{project_id}/members')
        if not any(row.get('user_id') == CONTRACTOR for row in members):
            self.operations.append({'action': 'add_contractor_member', 'project': project_name})
            if self.apply:
                self.mutation(key, f'/api/projects/{project_id}/members', 'POST',
                              {'user_id': CONTRACTOR, 'role': 'editor'})
                members = pages(self.api, f'/api/projects/{project_id}/members')
                if not any(row.get('user_id') == CONTRACTOR for row in members):
                    raise BridgeError('Contractor project membership was not confirmed')
        if self.apply:
            self.reconcile(key, project_id)

    def subscription(self, task_id, title):
        key = 'subscribe:' + task_id
        response = self.api.call(f'/api/tasks/{task_id}/subscriptions')
        if response.get('has_more'):
            raise BridgeError('Subscription list is incomplete; review visibility before continuing')
        if not any(row.get('user_id') == CONTRACTOR for row in response['data']):
            self.operations.append({'action': 'subscribe_contractor', 'task': title})
            if self.apply:
                self.mutation(key, f'/api/tasks/{task_id}/subscribe', 'POST', {'user_id': CONTRACTOR})
                response = self.api.call(f'/api/tasks/{task_id}/subscriptions')
                if not any(row.get('user_id') == CONTRACTOR for row in response['data']):
                    raise BridgeError('Contractor task subscription was not confirmed')
        if self.apply:
            self.reconcile(key, task_id)

    def run(self, main_project_id=None):
        me = self.api.call('/api/users/me')
        if me.get('workspace_id') != WORKSPACE or me.get('type') != 'agent' or me.get('id') == CONTRACTOR:
            raise BridgeError('Expected the configured buyer agent and workspace')
        projects = pages(self.api, '/api/projects')
        # Read and resolve every existing seed resource before the first write.
        resolved = []
        for project in self.fixture['projects']:
            found = match(projects, marker(self.fixture['id'], project['key']), 'name', project['name'])
            tasks = pages(self.api, '/api/tasks', project_id=found['id'], show_archived='true') if found else []
            found_tasks = []
            for task in project['tasks']:
                existing = match(tasks, marker(self.fixture['id'], project['key'] + '/' + task['key']),
                                 'title', task['title'])
                if existing and existing.get('assignee_id') not in (None, CONTRACTOR):
                    raise BridgeError('Existing background task is assigned to another identity; review')
                found_tasks.append(existing)
            resolved.append((project, found, found_tasks))
        main = None
        if main_project_id:
            main = next((p for p in projects if p['id'] == main_project_id), None)
            if not main:
                raise BridgeError('Main project was not found in the configured workspace')
            if any(p and p['id'] == main_project_id for _, p, _ in resolved):
                raise BridgeError('Main project must be separate from background projects')
        for project, found, found_tasks in resolved:
            key = 'project:' + project['key']
            if not found:
                self.operations.append({'action': 'create_project', 'name': project['name'],
                                        'visibility': 'workspace'})
                if self.apply:
                    found = self.mutation(key, '/api/projects', 'POST', project_body(self.fixture, project))['project']
            if found:
                self.reconcile(key, found['id'])
                self.membership(found['id'], project['name'])
            else:
                self.operations.append({'action': 'add_contractor_member', 'project': project['name']})
            for task, existing in zip(project['tasks'], found_tasks):
                task_key = 'task:' + project['key'] + '/' + task['key']
                if not existing:
                    self.operations.append({'action': 'create_task', 'project': project['name'],
                        'title': task['title'], 'status': task['status'], 'due_date': task['due_date'],
                        'owner': task['owner'], 'subscriber': self.fixture['contractor_alias']})
                    if self.apply:
                        existing = self.mutation(task_key, '/api/tasks', 'POST',
                            task_body(self.fixture, project, task, found['id']))['task']
                if existing:
                    self.reconcile(task_key, existing['id'])
                    self.subscription(existing['id'], task['title'])
        if main:
            name = self.fixture['main_project_name']
            key = 'rename-main:' + main['id']
            if main['name'] != name:
                self.operations.append({'action': 'rename_main_project', 'from': main['name'], 'to': name})
                if self.apply:
                    self.mutation(key, '/api/projects/' + main['id'], 'PATCH', {'name': name})
                    actual = self.api.call('/api/projects/' + main['id'])['project']
                    if actual['name'] != name:
                        raise BridgeError('Main project rename was not confirmed')
            self.reconcile(key, main['id'])
            self.membership(main['id'], name)
        return {'mode': 'applied' if self.apply else 'read_only_check', 'seed_id': self.fixture['id'],
                'operations': self.operations, 'existing_task_content_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--preview', action='store_true', help='Offline scenario preview (default)')
    group.add_argument('--check', action='store_true', help='Read-only API reconciliation preview')
    group.add_argument('--apply', action='store_true', help='Create missing background resources and repair visibility')
    parser.add_argument('--fixture', type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument('--main-project-id', type=identifier, help='Optionally rename this project; preserve its tasks')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    if not args.check and not args.apply:
        print(json.dumps({'mode': 'offline_preview', 'scenario': fixture,
            'optional_main_rename': bool(args.main_project_id),
            'visibility': 'workspace; contractor project member and task subscriber'}, indent=2))
        return
    runtime_home = os.environ.get('HERMES_HOME')
    if not runtime_home and not args.journal:
        raise BridgeError('HERMES_HOME or an explicit private journal path is required')
    path = args.journal or Path(runtime_home) / 'workspace-seed' / (fixture['id'] + '.json')
    api = API()
    if args.apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = Seeder(api, fixture, path, apply=True).run(args.main_project_id)
    else:
        result = Seeder(api, fixture, path).run(args.main_project_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (BridgeError, BlockingIOError) as error:
        raise SystemExit(str(error)) from None
