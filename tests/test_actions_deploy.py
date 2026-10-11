"""Deployment safety tests using synthetic files/DB/config under a temp directory."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('actions_gateway', Path(__file__).resolve().parents[1] / 'deploy/actions_gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class ActionsDeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app, self.state = self.root / 'app', self.root / 'state'
        (self.app / 'static').mkdir(parents=True)
        (self.state / 'backups').mkdir(parents=True)
        for name in (*gateway.FILES, 'app.py', 'backup.py'):
            (self.app / name).write_bytes(('old synthetic ' + name).encode())
        (self.app / 'data').mkdir()
        self.protected = [self.app / 'data/novel.sqlite3', self.app / 'admin_config.json', self.app / '.env']
        for path in self.protected:
            path.write_bytes(b'synthetic protected content')
        self.baseline = gateway.inventory(self.app, (*gateway.FILES, 'app.py', 'backup.py'))
        (self.state / 'baseline.json').write_text(json.dumps({'files': self.baseline}))
        self.events = []
        self.instance = gateway.Gateway(self.app, self.state, lambda current: self.events.append(current))
        self.expected = gateway.fingerprint(self.baseline)

    def release(self, extra=None):
        bodies = {n: ('new synthetic ' + n).encode() for n in gateway.FILES}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, body in bodies.items():
                archive.writestr(name, body)
            archive.writestr('release.json', json.dumps({'commit': 'a' * 40, 'files': {n: gateway.sha(b) for n, b in bodies.items()}}))
            if extra:
                archive.writestr(*extra)
        return stream.getvalue()

    def assert_protected(self):
        for path in self.protected:
            self.assertEqual(path.read_bytes(), b'synthetic protected content')
        for name in ('app.py', 'backup.py'):
            self.assertEqual(gateway.sha((self.app / name).read_bytes()), self.baseline[name])

    def test_backup_deploy_and_explicit_rollback(self):
        mode = (self.app / 'static/app.js').stat().st_mode
        result = self.instance.deploy(self.expected, self.release())
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual((self.app / 'static/app.js').stat().st_mode, mode)
        backup = self.state / 'backups' / result['backup']
        self.assertEqual(set(p.relative_to(backup).as_posix() for p in backup.rglob('*') if p.is_file()), {*gateway.FILES, 'record.json'})
        self.assertEqual(len(self.events), 2)
        self.instance.rollback(result['fingerprint'])
        self.assertEqual(self.instance.current(), self.baseline)
        self.assert_protected()

    def test_health_failure_restores_and_returns_failure(self):
        def health(current):
            self.events.append(current)
            if current != self.baseline:
                raise RuntimeError('synthetic bad served file')
        self.instance.check = health
        with self.assertRaisesRegex(RuntimeError, 'original files restored and health verified'):
            self.instance.deploy(self.expected, self.release())
        self.assertEqual(self.instance.current(), self.baseline)
        self.assertFalse((self.state / 'pending.json').exists())
        self.assertEqual(len(self.events), 3)
        self.assert_protected()

    def test_stale_inspect_and_backend_drift_refuse_writes(self):
        (self.app / 'static/app.js').write_bytes(b'manual edit')
        with self.assertRaisesRegex(ValueError, 'changed since inspect'):
            self.instance.deploy(self.expected, self.release())
        self.assertEqual((self.app / 'static/app.js').read_bytes(), b'manual edit')
        (self.app / 'backup.py').write_bytes(b'manual backup change')
        expected = self.instance.inspect()['fingerprint']
        with self.assertRaisesRegex(ValueError, 'Protected backend/backup code drift'):
            self.instance.deploy(expected, self.release())
        self.assertFalse(list((self.state / 'backups').iterdir()))

    def test_zip_extra_db_traversal_and_duplicate_refused(self):
        for name in ('data/novel.sqlite3', '../app.py', 'static/app.js'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.instance.deploy(self.expected, self.release((name, b'bad')))
        self.assertEqual(self.instance.current(), self.baseline)
        self.assert_protected()

    def test_static_directory_symlink_refused_before_read(self):
        static = self.app / 'static'
        static.rename(self.app / 'elsewhere')
        static.symlink_to(self.app / 'elsewhere', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink refused'):
            self.instance.inspect()

    def test_interrupted_transaction_recoverable(self):
        record = self.instance.backup(self.baseline)
        gateway.write_json(self.state / 'pending.json', record)
        (self.app / 'static/app.js').write_bytes(b'partial replacement')
        self.assertTrue(self.instance.inspect()['pending_recovery'])
        expected = self.instance.inspect()['fingerprint']
        with self.assertRaisesRegex(ValueError, 'Interrupted transaction'):
            self.instance.deploy(expected, self.release())
        self.instance.rollback(expected)
        self.assertEqual(self.instance.current(), self.baseline)
        self.assertFalse((self.state / 'pending.json').exists())

    def test_corrupt_backup_and_stale_rollback_preserve_current_files(self):
        result = self.instance.deploy(self.expected, self.release())
        with self.assertRaisesRegex(ValueError, 'changed since inspect'):
            self.instance.rollback(self.expected)
        before = self.instance.current()
        backup = self.state / 'backups' / result['backup'] / 'static/style.css'
        backup.write_bytes(b'corrupt synthetic backup')
        with self.assertRaisesRegex(ValueError, 'Backup digest mismatch'):
            self.instance.rollback(result['fingerprint'])
        self.assertEqual(self.instance.current(), before)

    def test_mid_copy_failure_restores_already_replaced_files(self):
        original = gateway.atomic
        failed = False
        def fail_once(path, body, metadata=None):
            nonlocal failed
            if path == self.app / 'static/style.css' and not failed:
                failed = True
                raise OSError('synthetic disk failure during replacement')
            return original(path, body, metadata)
        with patch.object(gateway, 'atomic', fail_once):
            with self.assertRaisesRegex(RuntimeError, 'original files restored'):
                self.instance.deploy(self.expected, self.release())
        self.assertEqual(self.instance.current(), self.baseline)
        self.assert_protected()

    def test_missing_file_restored_as_missing(self):
        (self.app / 'static/edit-history.js').unlink()
        self.baseline['static/edit-history.js'] = None
        (self.state / 'baseline.json').write_text(json.dumps({'files': self.baseline}))
        self.instance = gateway.Gateway(self.app, self.state, lambda current: None)
        result = self.instance.deploy(gateway.fingerprint(self.baseline), self.release())
        self.assertTrue((self.app / 'static/edit-history.js').exists())
        self.instance.rollback(result['fingerprint'])
        self.assertFalse((self.app / 'static/edit-history.js').exists())
        self.assert_protected()
