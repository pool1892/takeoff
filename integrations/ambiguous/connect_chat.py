"""Create/find the contractor's DM and check Hermes response extraction."""
import json
import os
from pathlib import Path
from bridge import API, CONTRACTOR, WORKSPACE, BridgeError, run_hermes

if os.environ.get('TAKEOFF_SANDBOX') != '1' or not Path('/.dockerenv').exists():
    raise SystemExit('Use the Takeoff container launcher.')

try:
    api = API()
    me = api.call('/api/users/me')
    agent = os.environ.get('TAKEOFF_AMBIGUOUS_USER_ID')
    if me.get('id') != agent or me.get('workspace_id') != WORKSPACE or me.get('type') != 'agent':
        raise BridgeError('Unexpected agent identity')
    channels = api.call('/api/channels')
    if channels.get('has_more'):
        raise BridgeError('Incomplete channel list')
    channel = None
    for item in channels['data']:
        if item.get('type') != 'dm':
            continue
        detail = api.call('/api/channels/' + item['id'])
        if {m['user_id'] for m in detail['members']} == {CONTRACTOR, agent}:
            channel = detail
            break
    if channel is None:
        channel = api.call('/api/channels', 'POST', {'type': 'dm', 'member_ids': [CONTRACTOR, agent]})
    detail = api.call('/api/channels/' + channel['id'])
    if {m['user_id'] for m in detail['members']} != {CONTRACTOR, agent}:
        raise BridgeError('DM membership mismatch')
    response = run_hermes({'content': 'Connection test: reply with exactly CHIP_CHAT_READY. Do not use tools.'},
                         [], Path('/opt/data/workspace'))
    if response != 'CHIP_CHAT_READY':
        raise BridgeError('Unexpected model connection-test response')
    print(json.dumps({'chat_ready': True, 'display_name': me['display_name'],
                      'url': 'https://app.ambiguous.ai/chat/' + channel['id'],
                      'model_response_extraction': 'passed'}))
except BridgeError as error:
    raise SystemExit(str(error)) from None
