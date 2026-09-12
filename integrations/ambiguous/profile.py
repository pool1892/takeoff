"""Update only the connected agent's own display name, inside the sandbox."""
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from bridge import NoRedirect

if os.environ.get('TAKEOFF_SANDBOX') != '1' or not Path('/.dockerenv').exists():
    raise SystemExit('Use scripts/hermes exec to run this inside the Takeoff sandbox.')
if len(sys.argv) != 2 or not sys.argv[1].strip():
    raise SystemExit('Usage: profile.py <display-name>')

origin = os.environ.get('AMBI_API_URL', 'https://api.ambiguous.ai').rstrip('/')
if origin not in ('https://api.ambiguous.ai', 'https://app.ambiguous.ai'):
    raise SystemExit('Unverified API origin.')


def request(method, body=None):
    req = urllib.request.Request(origin + '/api/users/me', method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['AMBI_API_TOKEN'],
                 'Content-Type': 'application/json', 'API-Version': '1'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Profile {method}: HTTP {error.code}; response body withheld.') from None
    except Exception:
        raise SystemExit(f'Profile {method}: request failed; no credentials displayed.') from None


me = request('GET')
if (me.get('id') != os.environ.get('TAKEOFF_AMBIGUOUS_USER_ID') or
        me.get('workspace_id') != os.environ.get('TAKEOFF_AMBIGUOUS_WORKSPACE_ID') or
        me.get('type') != 'agent'):
    raise SystemExit('Profile identity mismatch; no changes made.')
request('PATCH', {'display_name': sys.argv[1].strip()})
updated = request('GET')
if updated.get('display_name') != sys.argv[1].strip():
    raise SystemExit('Could not verify the requested display name.')
print(json.dumps({key: updated.get(key) for key in ('id', 'display_name', 'username', 'workspace_email')}))
