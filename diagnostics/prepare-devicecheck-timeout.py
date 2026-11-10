#!/usr/bin/env python3
"""Prepare an isolated 10-second DeviceCheck test module; never modify ChatGPT."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess


SOURCE = Path('/Applications/ChatGPT.app/Contents/Resources/native/devicecheck.node')
EXPECTED_SHA256 = 'd69b4a345457ce3fd022abeb068d2520077b99d48fe7340a7a7d55179affc0cc'
DESTINATION = Path(__file__).resolve().parent / 'devicecheck-10s-25894'
PATCHES = ((0x22e4, 0x52994001), (0x22e8, 0x72a77341))
NEW_TIMEOUT_NS = 10_000_007_168


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    original = SOURCE.read_bytes()
    if sha256(original) != EXPECTED_SHA256:
        raise SystemExit('Unsupported module hash. Reinspect the installed build; no files changed.')
    if struct.unpack_from('<II', original) != (0xfeedfacf, 0x0100000c):
        raise SystemExit('Expected the inspected arm64 Mach-O module.')
    for offset, expected in PATCHES:
        if struct.unpack_from('<I', original, offset)[0] != expected:
            raise SystemExit('Unexpected instruction; no files changed.')

    patched = bytearray(original)
    # Use X-register moves to encode the upper 32 bits; the low 16 bits are zero.
    encoded = (0xd2a00001 | (((NEW_TIMEOUT_NS >> 16) & 0xffff) << 5),
               0xf2c00001 | (((NEW_TIMEOUT_NS >> 32) & 0xffff) << 5))
    for (offset, _), instruction in zip(PATCHES, encoded):
        struct.pack_into('<I', patched, offset, instruction)
    changed = [i for i, pair in enumerate(zip(original, patched)) if pair[0] != pair[1]]
    allowed = {i for offset, _ in PATCHES for i in range(offset, offset + 4)}
    if not changed or not set(changed) <= allowed:
        raise SystemExit('Unexpected binary differences; no files changed.')

    DESTINATION.mkdir(exist_ok=True)
    baseline = DESTINATION / 'original.node'
    output = DESTINATION / 'devicecheck.node'
    baseline.write_bytes(original)
    output.write_bytes(patched)
    manifest = {
        'status': 'isolated diagnostic copy, not installed',
        'source': str(SOURCE),
        'source_sha256': EXPECTED_SHA256,
        'timeout_before_ns': 1_000_000_000,
        'timeout_after_ns': NEW_TIMEOUT_NS,
        'changed_offsets_before_signing': [hex(i) for i in changed],
        'patched_unsigned_sha256': sha256(patched),
        'signature': 'not signed yet',
    }
    manifest_path = DESTINATION / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    # Sign only this diagnostic copy. It no longer has an OpenAI signature.
    subprocess.run(['codesign', '--force', '--sign', '-', str(output)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(output)], check=True)
    manifest['signature'] = 'local ad-hoc signature; not OpenAI signed'
    manifest['patched_signed_sha256'] = sha256(output.read_bytes())
    if sha256(SOURCE.read_bytes()) != EXPECTED_SHA256:
        raise SystemExit('Installed source changed during preparation; inspect before testing.')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(output)
    print('Installed ChatGPT module unchanged. Only isolated copy was patched and ad-hoc signed.')


if __name__ == '__main__':
    main()
