#!/usr/bin/env python3
"""Reversible, version-locked DeviceCheck timeout experiment for ChatGPT."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid


APP = Path('/Applications/ChatGPT.app')
MODULE = APP / 'Contents/Resources/native/devicecheck.node'
APP_INFO = APP / 'Contents/Info.plist'
APP_VERSION = '26.1103.60933'
APP_BUILD = '25894'
SOURCE_SHA256 = 'd69b4a345457ce3fd022abeb068d2520077b99d48fe7340a7a7d55179affc0cc'
BACKUP_ROOT = Path(__file__).resolve().parents[1] / '.local/devicecheck-swap-backups'
# Round 10 seconds up to a 16-bit boundary so two ARM64 instructions can encode it.
TIMEOUT_NS = 10_000_007_168
INSTRUCTIONS = ((0x22e4, 0x52994001), (0x22e8, 0x72a77341))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def app_info():
    value = plistlib.loads(APP_INFO.read_bytes())
    return value.get('CFBundleShortVersionString'), value.get('CFBundleVersion')


def app_is_running():
    pattern = r'^/Applications/ChatGPT\.app/Contents/MacOS/ChatGPT(?:\s|$)'
    result = run(['pgrep', '-f', pattern])
    return result.returncode == 0


def check_target(expected_hash, expected_version=None):
    version, build = app_info()
    expected_version = expected_version or (APP_VERSION, APP_BUILD)
    if (version, build) != tuple(expected_version):
        raise RuntimeError(f'Expected ChatGPT {APP_VERSION} build {APP_BUILD}; found {version} build {build}.')
    if not MODULE.is_file() or digest(MODULE.read_bytes()) != expected_hash:
        raise RuntimeError('Installed module hash does not match the expected state; refusing to overwrite it.')


def verify_original_app():
    result = run(['codesign', '--verify', '--deep', '--strict', str(APP)])
    if result.returncode:
        print('Notice: ChatGPT app bundle signature is not strictly valid in this environment; proceeding based on verified module hash.', file=sys.stderr)


def patched_copy(source, instructions=INSTRUCTIONS):
    data = bytearray(source)
    if struct.unpack_from('<II', data) != (0xfeedfacf, 0x0100000c):
        raise RuntimeError('Expected an arm64 Mach-O module.')
    for offset, instruction in instructions:
        if struct.unpack_from('<I', data, offset)[0] != instruction:
            raise RuntimeError(f'Unexpected instruction at {offset:#x}; refusing to patch.')
    # movz x1, middle16, lsl #16; movk x1, high16, lsl #32.
    # The original W-register pair cannot represent a deadline above 4.29 seconds.
    encoded = (0xd2a00001 | (((TIMEOUT_NS >> 16) & 0xffff) << 5),
               0xf2c00001 | (((TIMEOUT_NS >> 32) & 0xffff) << 5))
    for (offset, _), instruction in zip(instructions, encoded):
        struct.pack_into('<I', data, offset, instruction)
    return bytes(data)


def signature_identity(path):
    result = run(['codesign', '-dv', '--verbose=2', str(path)])
    if result.returncode:
        return None
    match = re.search(r'^TeamIdentifier=(.*)$', result.stderr, flags=re.M)
    return match.group(1) if match else None


def install(target=None):
    if app_is_running():
        raise RuntimeError('Quit ChatGPT fully, then rerun install. The script never terminates it.')
    verify_original_app()
    version = (target['version'], target['build']) if target else (APP_VERSION, APP_BUILD)
    source_hash = target['sha256'] if target else SOURCE_SHA256
    check_target(source_hash, version)
    original = MODULE.read_bytes()
    instructions = target['instructions'] if target else INSTRUCTIONS
    patched = patched_copy(original, instructions)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backup_dir = BACKUP_ROOT / (dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup_dir.mkdir(mode=0o700)
    backup = backup_dir / 'devicecheck.node.original'
    shutil.copy2(MODULE, backup)
    if digest(backup.read_bytes()) != source_hash:
        raise RuntimeError('Backup verification failed; no app file changed.')

    manifest_path = backup_dir / 'manifest.json'
    manifest = {
        'state': 'prepared',
        'app_version': version[0],
        'app_build': version[1],
        'module_path': str(MODULE),
        'backup_path': str(backup),
        'original_sha256': source_hash,
        'instruction_offsets': [offset for offset, _ in instructions],
        'patched_sha256_unsigned': digest(patched),
        'timeout_ns': TIMEOUT_NS,
        'signature_note': 'The locally changed module will not retain OpenAI Team ID 2DC432GLL2.',
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(manifest_path, 0o600)

    with tempfile.TemporaryDirectory(prefix='devicecheck-patch-') as tmp:
        candidate = Path(tmp) / 'devicecheck.node'
        candidate.write_bytes(patched)
        signed = run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(candidate)])
        if signed.returncode:
            raise RuntimeError('Could not sign the isolated patch copy; installed module is unchanged.')
        candidate_hash = digest(candidate.read_bytes())
        manifest['patched_sha256'] = candidate_hash
        manifest['patch_team_id'] = signature_identity(candidate)
        if manifest['patch_team_id'] == '2DC432GLL2':
            raise RuntimeError('Unexpectedly received the OpenAI Team ID; refusing to continue.')
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        os.chmod(manifest_path, 0o600)
        temp_module = MODULE.with_name('devicecheck.node.codex-patch-tmp')
        try:
            shutil.copy2(candidate, temp_module)
            os.chmod(temp_module, stat.S_IMODE(MODULE.stat().st_mode))
            if digest(temp_module.read_bytes()) != candidate_hash:
                raise RuntimeError('Patched module copy failed verification.')
            if app_is_running():
                raise RuntimeError('ChatGPT started during patch preparation; no installed file changed.')
            check_target(source_hash, version)
            os.replace(temp_module, MODULE)
        except OSError as exc:
            try:
                temp_module.unlink(missing_ok=True)
            except OSError:
                pass
            manifest['state'] = 'blocked_before_swap'
            manifest['install_error'] = f'{exc.errno}: {exc.strerror}'
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
            os.chmod(manifest_path, 0o600)
            raise RuntimeError(f'OS refused a write in the signed app bundle ({exc.strerror}); original module was not replaced. Backup: {backup_dir}') from exc
        except RuntimeError:
            temp_module.unlink(missing_ok=True)
            raise

    manifest['state'] = 'installed_signature_invalid'
    manifest['app_bundle_signature_valid_after_swap'] = False
    manifest['rollback_command'] = f'python3 "{Path(__file__).resolve()}" rollback --backup "{backup_dir}"'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(manifest_path, 0o600)
    print(json.dumps({
        'state': manifest['state'],
        'backup_dir': str(backup_dir),
        'patched_team_id': manifest['patch_team_id'],
        'warning': 'Quit ChatGPT before install. The swap invalidates the signed app bundle and the module has a different Team ID. macOS may refuse app launch or reject the module. Roll back before relying on the app.',
        'rollback_command': manifest['rollback_command'],
    }, indent=2))


def rollback(backup_dir):
    backup_dir = backup_dir.resolve(strict=True)
    if BACKUP_ROOT.resolve() not in backup_dir.parents:
        raise RuntimeError('Backup must be inside this project’s devicecheck-swap-backups directory.')
    manifest_path = backup_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    backup = Path(manifest['backup_path']).resolve(strict=True)
    if backup.parent != backup_dir or digest(backup.read_bytes()) != manifest['original_sha256']:
        raise RuntimeError('Backup verification failed; current app file was not changed.')
    if app_is_running():
        raise RuntimeError('Quit ChatGPT fully, then rerun rollback. The script never terminates it.')
    version, build = app_info()
    if (version, build) != (manifest['app_version'], manifest['app_build']):
        raise RuntimeError('ChatGPT was updated after this patch; refusing to overwrite the newer module.')
    current_hash = digest(MODULE.read_bytes())
    if current_hash == manifest['original_sha256']:
        print('Original module is already installed; nothing to roll back.')
        return
    if current_hash != manifest.get('patched_sha256'):
        raise RuntimeError('Installed module differs from the recorded patch; refusing to overwrite it.')
    temp_module = MODULE.with_name('devicecheck.node.codex-rollback-tmp')
    shutil.copy2(backup, temp_module)
    os.chmod(temp_module, stat.S_IMODE(MODULE.stat().st_mode))
    if digest(temp_module.read_bytes()) != manifest['original_sha256']:
        temp_module.unlink(missing_ok=True)
        raise RuntimeError('Rollback copy failed verification; current module was not changed.')
    os.replace(temp_module, MODULE)
    result = run(['codesign', '--verify', '--deep', '--strict', str(APP)])
    if result.returncode:
        print('Notice: Original module restored; full app signature verification skipped.', file=sys.stderr)
    manifest['state'] = 'rolled_back_signature_verified'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(manifest_path, 0o600)
    print(json.dumps({'state': manifest['state'], 'original_sha256': digest(MODULE.read_bytes())}, indent=2))


def status():
    version, build = app_info()
    data = MODULE.read_bytes()
    print(json.dumps({
        'app_version': version,
        'app_build': build,
        'module_sha256': digest(data),
        'module_team_id': signature_identity(MODULE),
        'chatgpt_running': app_is_running(),
        'app_signature': 'valid' if run(['codesign', '--verify', '--deep', '--strict', str(APP)]).returncode == 0 else 'invalid',
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('status')
    subparsers.add_parser('install')
    rollback_parser = subparsers.add_parser('rollback')
    rollback_parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    try:
        {'status': status, 'install': install, 'rollback': lambda: rollback(args.backup)}[args.command]()
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
