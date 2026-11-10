#!/usr/bin/env python3
"""Install CLIProxyAPI wrappers and LaunchAgent using this checkout."""
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'local.codex.cliproxyapi'
INSTANCE = ROOT / '.local'
NODE = '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
PLIST = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')

for required in ['client-key', 'management-key', 'config.production.json', 'bin/cli-proxy-api']:
    if not (INSTANCE / required).is_file():
        raise SystemExit('Missing instance file: ' + required)
agent = {
    'Label': LABEL, 'ProgramArguments': [NODE, str(ROOT / 'deploy/macos/run.mjs')],
    'WorkingDirectory': str(INSTANCE), 'RunAtLoad': True,
    'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 10,
    'ProcessType': 'Background',
    'StandardOutPath': str(INSTANCE / 'state/service.log'),
    'StandardErrorPath': str(INSTANCE / 'state/service.log'),
}
PLIST.parent.mkdir(parents=True, exist_ok=True)
PLIST.write_bytes(plistlib.dumps(agent))
PLIST.chmod(0o600)
wrappers = Path.home() / '.local/bin'
wrappers.mkdir(parents=True, exist_ok=True)
cli = wrappers / 'codex-cliproxy'
cli.write_text('#!/bin/sh\nexport CODEX_LOCAL_GATEWAY_TOKEN="$(cat ' + shlex.quote(str(INSTANCE / 'client-key')) + ')"\nexec ' + shlex.quote(str(wrappers / 'codex')) + ' -c \'model_provider="gw"\' "$@"\n')
cli.chmod(0o700)
ctl = wrappers / 'cliproxyctl'
ctl.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'deploy/macos/control.py')) + ' "$@"\n')
ctl.chmod(0o700)
for alias, destination in [('codex-gateway', 'codex-cliproxy'), ('codex-gatewayctl', 'cliproxyctl')]:
    filename = wrappers / alias
    filename.unlink(missing_ok=True)
    filename.symlink_to(destination)
subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(PLIST)], check=True)
print('CLIProxyAPI installed on port 18474; CLI: codex-cliproxy; service: cliproxyctl')
