"""Live, unauthenticated checks of allowed API access and denied egress."""
import json
from pathlib import Path
import socket
import urllib.error
import urllib.request

routes = Path('/proc/net/route').read_text().splitlines()[1:]
assert not any(row.split()[1] == '00000000' for row in routes), 'Buyer has a default route'
for host, port in [('172.17.0.1', 22), ('1.1.1.1', 443)]:
    try:
        connection = socket.create_connection((host, port), timeout=2)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError(f'Direct connection escaped the isolated network: {host}:{port}')
try:
    urllib.request.urlopen('https://example.com', timeout=10)
except urllib.error.URLError as error:
    assert '403' in str(error.reason), 'Expected explicit proxy rejection'
else:
    raise AssertionError('Unapproved external hostname was reachable')

with urllib.request.urlopen('https://api.ambiguous.ai/api/openapi.json', timeout=30) as response:
    assert response.status == 200
try:
    urllib.request.urlopen('https://api.openai.com/v1/models', timeout=30)
except urllib.error.HTTPError as error:
    assert error.code == 401, f'Unexpected OpenAI response: {error.code}'
else:
    raise AssertionError('Unauthenticated OpenAI request did not return 401')
print(json.dumps({'network_isolation': 'passed', 'default_route': False,
                  'direct_host_and_internet': 'blocked', 'unapproved_domains': 'blocked',
                  'ambiguous_public_schema': 200, 'openai_without_key': 401}))
