"""Verify real container isolation without any model call or credentials."""
import json
import os
from pathlib import Path

repo = Path('/workspace')
assert Path('/.dockerenv').exists(), 'Must run inside Docker'
assert os.getuid() != 0, 'Runtime must not be root'
assert Path(os.environ['HERMES_HOME']).is_relative_to(repo)
assert Path(os.environ['HOME']).is_relative_to(repo)
for path in ('/home/cs', '/var/run/docker.sock', '/run/user/1000', '/host'):
    assert not Path(path).exists(), f'Host path exposed: {path}'
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(), 16) == 0, 'Capabilities must be dropped'
assert status['NoNewPrivs'].strip() == '1'
probe = repo / '.local/hermes/isolation-write-probe'
probe.write_text('repo writes work')
probe.unlink()
try:
    Path('/opt/hermes/takeoff-write-probe').write_text('must fail')
except OSError:
    pass
else:
    raise AssertionError('Image filesystem is writable')
try:
    (repo / 'runtime/hermes/image.txt').open('a').close()
except OSError:
    pass
else:
    raise AssertionError('Agent can edit host launcher/configuration source')
escape = repo / '.local/hermes/isolation-symlink-probe'
try:
    escape.symlink_to('/home/cs/.ssh')
    assert not escape.exists(), 'Symlink can see host home'
finally:
    escape.unlink(missing_ok=True)
print(json.dumps({'isolation': 'passed', 'uid': os.getuid(), 'repo': str(repo),
                  'host_home': 'not mounted', 'docker_socket': 'not mounted',
                  'image_filesystem': 'read-only', 'repo_source': 'read-only',
                  'writable_state': '/workspace/.local/hermes', 'capabilities': 'none'}))
