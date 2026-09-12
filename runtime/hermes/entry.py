"""Runs inside the container, never on the host."""
import os
import sys
from pathlib import Path

if not Path('/.dockerenv').exists() or os.environ.get('TAKEOFF_SANDBOX') != '1':
    raise SystemExit('Use scripts/hermes to enter the Takeoff container.')

from dotenv import load_dotenv

load_dotenv('/workspace/.local/hermes/.env', override=True)
os.chdir('/opt/data/workspace')
args = sys.argv[1:]
if args and args[0] == 'exec':
    args = args[1:]
    if not args:
        raise SystemExit('exec requires a command')
else:
    args = ['/opt/hermes/.venv/bin/hermes', *args]
os.execvp(args[0], args)
