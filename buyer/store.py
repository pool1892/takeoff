"""Private, atomic run snapshots with one writer per task."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', value):
        raise ValueError('Invalid local record identifier')
    return value


def home():
    base = Path(os.environ.get('HERMES_HOME', '/opt/data')) / 'procurement'
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_symlink():
        raise ValueError('Procurement state cannot be a symlink')
    return base


def save(path, value):
    if path.is_symlink():
        raise ValueError('State cannot be a symlink')
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(out.name, path)


@contextmanager
def transaction(task_id):
    key = identifier(task_id)
    directory = home() / 'runs'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (key + '.json')
    lock_path = directory / (key + '.lock')
    if path.is_symlink() or lock_path.is_symlink():
        raise ValueError('State cannot be a symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {}
        yield state, lambda: save(path, state)


def config():
    path = home() / 'config.json'
    if path.is_symlink():
        raise ValueError('Configuration cannot be a symlink')
    return json.loads(path.read_text()) if path.exists() else {}


def event(state, kind, content, source_id=None):
    record = {'type': kind, 'at': now(), 'content': content}
    if source_id:
        record['source_id'] = source_id
    state.setdefault('events', []).append(record)
    return record
