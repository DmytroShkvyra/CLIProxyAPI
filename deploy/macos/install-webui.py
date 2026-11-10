#!/usr/bin/env python3
"""Install a built single-file management panel and preserve its predecessor."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='Web UI source checkout containing dist/index.html')
args = parser.parse_args()
source = args.source.resolve(strict=True)
built = source / 'dist/index.html'
data = built.read_bytes()
if not data.lstrip().lower().startswith(b'<!doctype html'):
    raise SystemExit('Expected a built HTML document')
directory = ROOT / '.local/state/static'
directory.mkdir(parents=True, exist_ok=True)
target = directory / 'management.html'
if target.exists():
    backup = directory / ('management.before-local-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.html')
    shutil.copy2(target, backup)
temporary = directory / 'management.tmp'
temporary.write_bytes(data)
temporary.replace(target)
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
manifest = {'source': str(source), 'commit': commit, 'sha256': hashlib.sha256(data).hexdigest(), 'auto_update_disabled': True}
(ROOT / '.local/webui.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Management panel installed. Restart CLIProxyAPI to pin the local panel.')
