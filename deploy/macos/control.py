#!/usr/bin/env python3
"""Control the per-user CLIProxyAPI LaunchAgent."""
import argparse
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'local.codex.cliproxyapi'

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('command', choices=['start', 'stop', 'restart', 'status'])
args = parser.parse_args()
target = f'gui/{os.getuid()}/{LABEL}'
if args.command == 'stop':
    subprocess.run(['launchctl', 'bootout', target], check=True)
elif args.command in ('start', 'restart'):
    loaded = subprocess.run(['launchctl', 'print', target], capture_output=True).returncode == 0
    if loaded:
        subprocess.run(['launchctl', 'kickstart', '-k', target], check=True)
    else:
        subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist'))], check=True)
else:
    loaded = subprocess.run(['launchctl', 'print', target], capture_output=True).returncode == 0
    print('LaunchAgent loaded:', loaded)
    request = urllib.request.Request('http://127.0.0.1:18474/v1/models', headers={
        'X-Codex-Local-Gateway': (ROOT / '.local/client-key').read_text().strip()})
    with urllib.request.urlopen(request, timeout=10) as response:
        print('CLIProxyAPI models HTTP:', response.status)
