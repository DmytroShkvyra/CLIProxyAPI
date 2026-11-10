#!/usr/bin/env python3
"""Maintain the verified DeviceCheck timeout patch while ChatGPT is closed."""
import argparse
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('devicecheck_patch', ROOT / 'manage-devicecheck-patch.py')
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)
LABEL = 'local.codex.devicecheck-autopatch'
RUNTIME = Path.home() / 'Library/Application Support/CodexDeviceCheckAutopatch'
AGENT = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
ORIGINAL_PAIR = struct.pack('<II', 0x52994001, 0x72a77341)
PATCHED_PAIR = struct.pack('<II', 0xd2aa8181, 0xf2c00041)


def text_section(data):
    if len(data) < 32 or struct.unpack_from('<II', data) != (0xfeedfacf, 0x0100000c):
        raise RuntimeError('Unsupported module architecture; expected arm64 Mach-O.')
    count, size = struct.unpack_from('<II', data, 16)
    end = 32 + size
    if end > len(data):
        raise RuntimeError('Truncated Mach-O load commands.')
    cursor = 32
    found = []
    for _ in range(count):
        if cursor + 8 > end:
            raise RuntimeError('Truncated Mach-O command.')
        command, length = struct.unpack_from('<II', data, cursor)
        if length < 8 or cursor + length > end:
            raise RuntimeError('Invalid Mach-O command length.')
        if command == 0x19:
            if length < 72:
                raise RuntimeError('Truncated segment command.')
            sections = struct.unpack_from('<I', data, cursor + 64)[0]
            if 72 + sections * 80 > length:
                raise RuntimeError('Truncated section table.')
            for index in range(sections):
                section = cursor + 72 + index * 80
                name = data[section:section + 16].rstrip(b'\0')
                segment = data[section + 16:section + 32].rstrip(b'\0')
                if name == b'__text' and segment == b'__TEXT':
                    address, size, offset = struct.unpack_from('<QQI', data, section + 32)
                    if offset + size > len(data):
                        raise RuntimeError('Text section extends past module.')
                    found.append((address, offset, size))
        cursor += length
    if len(found) != 1:
        raise RuntimeError('Expected exactly one executable text section.')
    return found[0]


def inspect_module(data, disassembly):
    address, offset, size = text_section(data)
    rows = {}
    for line in disassembly.splitlines():
        match = re.match(r'^\s*([0-9a-fA-F]{16})\s+(.+)$', line)
        if match:
            rows[int(match[1], 16)] = match[2]
    candidates = []
    text = data[offset:offset + size]
    for state, pair in [('original', ORIGINAL_PAIR), ('patched', PATCHED_PAIR)]:
        start = 0
        while True:
            index = text.find(pair, start)
            if index < 0:
                break
            start = index + 1
            if index % 4:
                continue
            pc = address + index
            before = rows.get(pc - 8, '')
            zero = re.sub(r'\s+', '', rows.get(pc - 4, ''))
            clock = rows.get(pc + 8, '')
            argument = re.sub(r'\s+', '', rows.get(pc + 12, ''))
            semaphore = rows.get(pc + 20, '')
            if (before.startswith('bl') and 'generateTokenWithCompletionHandler:' in before
                    and zero == 'movx0,#0x0' and clock.startswith('bl')
                    and '_dispatch_time' in clock and argument == 'movx1,x0'
                    and semaphore.startswith('bl') and '_dispatch_semaphore_wait' in semaphore):
                candidates.append({'state': state, 'instructions': tuple(
                    (offset + index + n * 4, word)
                    for n, word in enumerate(struct.unpack('<II', ORIGINAL_PAIR)))})
    if len(candidates) != 1:
        raise RuntimeError('Unsupported or ambiguous timeout implementation; automatic patch refused.')
    return candidates[0]


def save_state(value):
    previous = json.loads((RUNTIME / 'status.json').read_text()) if (RUNTIME / 'status.json').exists() else {}
    value['checked_at'] = time.time()
    temporary = RUNTIME / 'status.tmp'
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(RUNTIME / 'status.json')
    if any(previous.get(key) != value.get(key) for key in ('status', 'sha256', 'error')):
        print(json.dumps(value), flush=True)
    return value


def once():
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (RUNTIME / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            version, build = patch.app_info()
            data = patch.MODULE.read_bytes()
            fingerprint = patch.digest(data)
            previous = json.loads((RUNTIME / 'status.json').read_text()) if (RUNTIME / 'status.json').exists() else {}
            info = {'version': version, 'build': build, 'sha256': fingerprint}
            if previous.get('sha256') == fingerprint and previous.get('status') == 'patched':
                return
            assembly = patch.run(['/usr/bin/otool', '-tvV', str(patch.MODULE)])
            if assembly.returncode:
                raise RuntimeError('Cannot disassemble installed module.')
            target = inspect_module(data, assembly.stdout)
            if target['state'] == 'patched':
                save_state(dict(info, status='patched', timeout_ns=patch.TIMEOUT_NS))
                return
            if patch.app_is_running():
                save_state(dict(info, status='waiting-for-app-exit'))
                return
            # Require the same closed app/module on consecutive checks before writing.
            if previous.get('sha256') != fingerprint or previous.get('status') != 'waiting-for-stable-idle':
                save_state(dict(info, status='waiting-for-stable-idle', idle_since=time.time()))
                return
            if time.time() - previous.get('idle_since', time.time()) < 5:
                return
            verified = patch.run(['/usr/bin/codesign', '--verify', '--strict', str(patch.MODULE)])
            if verified.returncode or patch.signature_identity(patch.MODULE) != '2DC432GLL2':
                raise RuntimeError('New original module must have a valid OpenAI signature.')
            target.update(info)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                patch.install(target)
            installed = json.loads(output.getvalue())
            save_state(dict(info, status='patched', sha256=patch.digest(patch.MODULE.read_bytes()),
                            timeout_ns=patch.TIMEOUT_NS, backup_dir=installed['backup_dir'],
                            rollback_command=installed['rollback_command']))
        except (OSError, RuntimeError, ValueError, struct.error) as error:
            save_state({'status': 'error', 'error': str(error)})


def service(enable):
    domain = 'gui/' + str(os.getuid())
    if not enable:
        subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
        AGENT.unlink(missing_ok=True)
        print('Automatic patching disabled. Existing module was not changed.')
        return
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    value = {
        'Label': LABEL, 'ProgramArguments': [sys.executable, str(Path(__file__).resolve()), 'once'],
        'RunAtLoad': True, 'StartInterval': 15, 'ProcessType': 'Background',
        'WatchPaths': [str(patch.APP_INFO), str(patch.MODULE.parent)],
        'StandardOutPath': str(RUNTIME / 'agent.log'), 'StandardErrorPath': str(RUNTIME / 'agent.log'),
    }
    subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
    AGENT.write_bytes(plistlib.dumps(value))
    AGENT.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(AGENT)], check=True)
    print('Automatic patching enabled: ' + str(AGENT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['enable', 'disable', 'once', 'status'])
    args = parser.parse_args()
    if args.command in ('enable', 'disable'):
        service(args.command == 'enable')
    elif args.command == 'once':
        once()
    else:
        status = RUNTIME / 'status.json'
        print(status.read_text() if status.exists() else 'Not checked yet.')
        print('LaunchAgent installed: ' + str(AGENT.exists()))


if __name__ == '__main__':
    main()
