import importlib.util
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('autopatch', Path(__file__).with_name('devicecheck-autopatch.py'))
auto = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto)


def fixture(patched=False, second=False, moved=False):
    data = bytearray(4096)
    struct.pack_into('<IIIIIIII', data, 0, 0xfeedfacf, 0x0100000c, 0, 6, 1, 152, 0, 0)
    struct.pack_into('<II16sQQQQIIII', data, 32, 0x19, 152, b'__TEXT', 0, 4096, 0, 4096, 7, 5, 1, 0)
    offset, address, size = 1024, 0x100004000, 256
    struct.pack_into('<16s16sQQI', data, 104, b'__text', b'__TEXT', address, size, offset)
    locations = [72 if moved else 8]
    if second:
        locations.append(160)
    rows = []
    for index in locations:
        data[offset + index:offset + index + 8] = auto.PATCHED_PAIR if patched else auto.ORIGINAL_PAIR
        pc = address + index
        for delta, text in [(-8, 'bl 0x123 ; _objc_msgSend$generateTokenWithCompletionHandler:'),
                            (-4, 'mov x0, #0x0'), (8, 'bl 0x456 ; symbol stub for: _dispatch_time'),
                            (12, 'mov x1, x0'), (16, 'mov x0, x22'),
                            (20, 'bl 0x789 ; symbol stub for: _dispatch_semaphore_wait')]:
            rows.append(f'{pc + delta:016x}\t{text}')
    return bytes(data), '\n'.join(rows), offset + locations[0]


class DetectionTests(unittest.TestCase):
    def test_original_and_relocated_instruction_detection(self):
        for moved in (False, True):
            data, assembly, offset = fixture(moved=moved)
            result = auto.inspect_module(data, assembly)
            self.assertEqual(result['state'], 'original')
            self.assertEqual(result['instructions'][0][0], offset)
            patched = auto.patch.patched_copy(data, result['instructions'])
            self.assertEqual(patched[offset:offset + 8], auto.PATCHED_PAIR)
            self.assertEqual(patched[:offset], data[:offset])
            self.assertEqual(patched[offset + 8:], data[offset + 8:])

    def test_already_patched(self):
        data, assembly, _ = fixture(patched=True)
        self.assertEqual(auto.inspect_module(data, assembly)['state'], 'patched')

    def test_ambiguous_pattern_refused(self):
        data, assembly, _ = fixture(second=True)
        with self.assertRaises(RuntimeError):
            auto.inspect_module(data, assembly)

    def test_missing_context_refused(self):
        data, assembly, _ = fixture()
        with self.assertRaises(RuntimeError):
            auto.inspect_module(data, assembly.replace('_dispatch_time', '_different_call'))

    def test_unsupported_architecture_and_truncation(self):
        data, _, _ = fixture()
        for value in (b'', b'not-a-module', data[:80], b'FAT!' + data[4:]):
            with self.assertRaises(RuntimeError):
                auto.text_section(value)


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data, self.assembly, _ = fixture()
        self.module = root / 'devicecheck.node'
        self.module.write_bytes(self.data)
        self.runtime = root / 'state'
        self.context = patch.multiple(auto, RUNTIME=self.runtime)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.manager = patch.multiple(auto.patch, MODULE=self.module,
                                      app_info=lambda: ('new-version', 'new-build'),
                                      run=lambda args: SimpleNamespace(returncode=0, stdout=self.assembly),
                                      signature_identity=lambda path: '2DC432GLL2')
        self.manager.start()
        self.addCleanup(self.manager.stop)

    def status(self):
        return json.loads((self.runtime / 'status.json').read_text())

    def test_running_app_never_patched(self):
        with patch.object(auto.patch, 'app_is_running', return_value=True), patch.object(auto.patch, 'install') as install:
            auto.once()
            self.assertEqual(self.status()['status'], 'waiting-for-app-exit')
            install.assert_not_called()

    def test_idle_debounce_and_dynamic_target(self):
        def install(target):
            self.assertEqual(target['version'], 'new-version')
            self.assertEqual(target['sha256'], auto.patch.digest(self.data))
            self.module.write_bytes(auto.patch.patched_copy(self.data, target['instructions']))
            print(json.dumps({'backup_dir': 'backup', 'rollback_command': 'restore'}))
        with patch.object(auto.patch, 'app_is_running', return_value=False), patch.object(auto.patch, 'install', side_effect=install) as call:
            auto.once()
            call.assert_not_called()
            status = self.status()
            status['idle_since'] -= 6
            (self.runtime / 'status.json').write_text(json.dumps(status))
            auto.once()
            self.assertEqual(self.status()['status'], 'patched')
            call.assert_called_once()
            auto.once()
            call.assert_called_once()

    def test_unsigned_original_refused(self):
        with patch.object(auto.patch, 'app_is_running', return_value=False), patch.object(auto.patch, 'install') as install:
            auto.once()
            status = self.status()
            status['idle_since'] -= 6
            (self.runtime / 'status.json').write_text(json.dumps(status))
            with patch.object(auto.patch, 'signature_identity', return_value=None):
                auto.once()
            install.assert_not_called()
            self.assertEqual(self.status()['status'], 'error')


if __name__ == '__main__':
    unittest.main()
