#!/usr/bin/env python3
"""Admit one actual contractor DM into the configured fresh procurement run."""
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from bridge import API, BridgeError, CONTRACTOR, WORKSPACE, identifier
except ModuleNotFoundError:
    from integrations.ambiguous.bridge import API, BridgeError, CONTRACTOR, WORKSPACE, identifier
from buyer import store


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise BridgeError('Source message timestamp is invalid') from None


def pages(api, path, **query):
    rows, offset = [], 0
    for _ in range(20):
        page = api.call(path, limit=100, offset=offset, **query)
        current = page.get('data', [])
        rows.extend(current)
        if not page.get('has_more'):
            return rows
        if not current:
            raise BridgeError('Intake pagination did not advance')
        offset += len(current)
    raise BridgeError('Intake listing exceeded its review bound')


def source_message(api, agent_id, message_id, not_before):
    channel_page = api.call('/api/channels')
    if channel_page.get('has_more'):
        raise BridgeError('Channel listing is incomplete; review before intake')
    channels = channel_page.get('data', [])
    matches = []
    for channel in channels:
        if channel.get('type') != 'dm' or channel.get('archived_at'):
            continue
        detail = api.call('/api/channels/' + identifier(channel['id']))
        members = {m.get('user_id') for m in detail.get('members', [])}
        if detail.get('type') == 'dm' and members == {CONTRACTOR, agent_id}:
            matches.append(detail)
    if len(matches) != 1:
        raise BridgeError('A unique contractor DM is required')
    channel_id = identifier(matches[0]['id'])
    message = api.call('/api/channels/' + channel_id + '/messages/' + message_id)
    message = message.get('message', message)
    if (message.get('id') != message_id or message.get('channel_id') != channel_id
            or (message.get('author') or {}).get('id') != CONTRACTOR
            or message.get('edited_at') or message.get('deleted_at')
            or not isinstance(message.get('content'), str) or not message['content'].strip()
            or timestamp(message.get('created_at')) < not_before):
        raise BridgeError('Intake requires a fresh unedited contractor message')
    return message


def task_description(message, run_id):
    reference = ('https://app.ambiguous.ai/chat/' + message['channel_id']
                 + '?message=' + message['id'])
    # Keep the exact original text as the entire leading body, without rewriting specifications.
    return (message['content'] + '\n\n---\n\n'
            'Created by Chip from the contractor’s original chat request. '
            '[Original message](' + reference + ').\n\n'
            '<!-- takeoff-intake:' + message['id'] + ':' + run_id + ' -->')


def admit(api, home, message_id, agent_id, mailbox_id=None):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    with (home / 'intake-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_path = home / 'intake-config.json'
        if not config_path.exists():
            raise BridgeError('Fresh procurement intake is not configured')
        setup = json.loads(config_path.read_text())
        if not setup.get('enabled') or not setup.get('run_id') or not setup.get('suppliers') or not setup.get('catalog_urls'):
            raise BridgeError('Fresh procurement intake is disabled or incomplete')
        if setup.get('expected_mailbox_id') and setup['expected_mailbox_id'] != mailbox_id:
            raise BridgeError('Configured shared mailbox is not active in this runtime')
        run_id = store.identifier(setup['run_id'])
        project_id = setup.get('project_id')
        if not project_id:
            project_id = json.loads((home / 'shared-project.json').read_text())['id']
        project_id = identifier(project_id)
        not_before = (timestamp(setup['armed_at']) if setup.get('armed_at') else
                      datetime.fromtimestamp(config_path.stat().st_mtime, timezone.utc))
        identity = api.call('/api/users/me')
        if identity.get('id') != agent_id or identity.get('workspace_id') != WORKSPACE or identity.get('type') != 'agent':
            raise BridgeError('Intake requires the configured buyer agent')
        message = source_message(api, agent_id, message_id, not_before)
        directory = home / 'intake'
        directory.mkdir(exist_ok=True)
        path = directory / (message_id + '.json')
        journal = json.loads(path.read_text()) if path.exists() else {}
        if journal and (journal.get('run_id') != run_id or journal.get('source_digest') != store.digest(message['content'])):
            raise BridgeError('Original intake source or run changed; preserve prior work')
        for other in directory.glob('*.json'):
            saved = json.loads(other.read_text())
            if saved.get('run_id') == run_id and other != path:
                raise BridgeError('This supplier run is already bound to another request')
        for other in (home / 'runs').glob('*.json'):
            saved = json.loads(other.read_text())
            if saved.get('run_id') == run_id and saved.get('task_id') != journal.get('task_id'):
                raise BridgeError('This supplier run already has another procurement task')
        title = setup.get('task_title', 'House materials — fresh quotes and buying plan')
        description = task_description(message, run_id)
        if not journal:
            journal = {'run_id': run_id, 'message_id': message_id, 'channel_id': message['channel_id'],
                       'source_digest': store.digest(message['content']), 'created_at': store.now()}
            store.save(path, journal)
        project = api.call('/api/projects/' + project_id)
        project = project.get('project', project)
        if project.get('id') != project_id:
            raise BridgeError('Configured project could not be verified')
        members = pages(api, '/api/projects/' + project_id + '/members')
        if not any(m.get('user_id') == CONTRACTOR for m in members):
            if journal.get('membership_pending'):
                raise BridgeError('Uncertain contractor membership needs review')
            journal['membership_pending'] = True
            store.save(path, journal)
            api.call('/api/projects/' + project_id + '/members', 'POST', {'user_id': CONTRACTOR, 'role': 'editor'})
            members = pages(api, '/api/projects/' + project_id + '/members')
            if not any(m.get('user_id') == CONTRACTOR for m in members):
                raise BridgeError('Contractor project access was not confirmed')
        journal.pop('membership_pending', None)
        if journal.get('task_id'):
            task = api.call('/api/tasks/' + identifier(journal['task_id']))['task']
        else:
            rows = pages(api, '/api/tasks', project_id=project_id, show_archived='true')
            matches = [t for t in rows if t.get('title') == title and t.get('description') == description
                       and t.get('creator_id') == agent_id]
            if len(matches) > 1:
                raise BridgeError('Duplicate intake tasks require review')
            if matches:
                task = api.call('/api/tasks/' + identifier(matches[0]['id']))['task']
            else:
                if journal.get('task_pending'):
                    raise BridgeError('Uncertain task creation is not visible; do not retry')
                journal['task_pending'] = True
                store.save(path, journal)
                task = api.call('/api/tasks', 'POST', {'title': title, 'description': description,
                    'status': 'todo', 'priority': 'high', 'assignee_id': agent_id,
                    'project_id': project_id, 'subscriber_ids': [CONTRACTOR]})['task']
            journal['task_id'] = identifier(task['id'])
            store.save(path, journal)
        task = api.call('/api/tasks/' + journal['task_id'])['task']
        if (task.get('title') != title or task.get('description') != description
                or task.get('creator_id') != agent_id or task.get('assignee_id') != agent_id
                or task.get('project_id') != project_id):
            raise BridgeError('Created task does not match the original contractor request')
        subscription_page = api.call('/api/tasks/' + task['id'] + '/subscriptions')
        if subscription_page.get('has_more'):
            raise BridgeError('Contractor subscription listing is incomplete')
        subscriptions = subscription_page.get('data', [])
        if not any(s.get('user_id') == CONTRACTOR for s in subscriptions):
            if journal.get('subscription_pending'):
                raise BridgeError('Uncertain contractor subscription needs review')
            journal['subscription_pending'] = True
            store.save(path, journal)
            api.call('/api/tasks/' + task['id'] + '/subscribe', 'POST', {'user_id': CONTRACTOR})
            subscription_page = api.call('/api/tasks/' + task['id'] + '/subscriptions')
            if subscription_page.get('has_more'):
                raise BridgeError('Contractor subscription listing is incomplete')
            subscriptions = subscription_page.get('data', [])
            if not any(s.get('user_id') == CONTRACTOR for s in subscriptions):
                raise BridgeError('Contractor task subscription was not confirmed')
        journal.pop('subscription_pending', None)
        # Re-read the human source immediately before enabling work.
        current = source_message(api, agent_id, message_id, not_before)
        if current['content'] != message['content']:
            raise BridgeError('Contractor source changed before activation')
        config = {'enabled': True, 'run_id': run_id, 'task_ids': [task['id']],
                  'suppliers': setup['suppliers'], 'catalog_urls': setup['catalog_urls']}
        active_path = home / 'config.json'
        if active_path.exists() and not journal.get('prior_config_saved'):
            backup = home / ('config-before-intake-' + message_id + '.json')
            if not backup.exists():
                store.save(backup, json.loads(active_path.read_text()))
            journal['prior_config_saved'] = True
            store.save(path, journal)
        store.save(active_path, config)
        journal.update(verified=True, activated=True, mailbox_id=mailbox_id,
                       task_url='https://app.ambiguous.ai/tasks?task=' + task['id'])
        journal.pop('task_pending', None)
        store.save(path, journal)
        return {'task_id': task['id'], 'task_url': journal['task_url'], 'run_id': run_id,
                'source_message_id': message_id, 'enabled': True, 'mailbox_id': mailbox_id,
                'source_preserved': True, 'contractor_subscribed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message-id', required=True, type=identifier)
    args = parser.parse_args()
    if os.environ.get('TAKEOFF_SANDBOX') != '1' or not Path('/.dockerenv').exists():
        raise BridgeError('Run intake only inside isolated Takeoff Docker')
    agent_id = identifier(os.environ.get('TAKEOFF_AMBIGUOUS_USER_ID'))
    mailbox = os.environ.get('TAKEOFF_AMBIGUOUS_MAILBOX_ID') or None
    if mailbox:
        mailbox = identifier(mailbox)
    print(json.dumps(admit(API(), store.home(), args.message_id, agent_id, mailbox), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (BridgeError, BlockingIOError) as error:
        raise SystemExit(str(error)) from None
