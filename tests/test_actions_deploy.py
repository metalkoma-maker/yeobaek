"""Deployment safety tests using synthetic files/DB/config under a temp directory."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
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
        for name in (*gateway.FILES, 'backup.py'):
            (self.app / name).write_bytes(('old synthetic ' + name).encode())
        (self.app / 'data').mkdir()
        self.database = self.app / 'data/novel.sqlite3'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE manuscripts(id TEXT, body TEXT)')
            db.execute('INSERT INTO manuscripts VALUES (?,?)',('synthetic-id','synthetic manuscript'))
        self.protected = [self.app / 'admin_config.json', self.app / '.env']
        for path in self.protected:
            path.write_bytes(b'synthetic protected content')
        self.baseline = gateway.inventory(self.app, (*gateway.FILES, 'app.py', 'backup.py'))
        (self.state / 'baseline.json').write_text(json.dumps({'files': self.baseline}))
        self.events = []
        self.service_actions = []
        self.instance = gateway.Gateway(self.app, self.state, self.database,
                                        lambda current: self.events.append(current),
                                        self.control, lambda: gateway.schema_ready(self.database))
        self.expected = gateway.fingerprint(self.baseline)

    def control(self, action):
        self.service_actions.append(action)
        if action == 'start' and (self.app / 'app.py').read_bytes().startswith(b'new synthetic'):
            with sqlite3.connect(self.database) as db:
                db.execute('CREATE TABLE IF NOT EXISTS manuscript_order(user_id TEXT PRIMARY KEY, ids TEXT NOT NULL, version INTEGER NOT NULL)')

    def release(self, extra=None):
        bodies = {n: ('new synthetic ' + n).encode() for n in gateway.FILES}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, body in bodies.items():
                archive.writestr(name, body)
            archive.writestr('release.json', json.dumps({'commit': 'a' * 40, 'schema_change': gateway.SCHEMA_CHANGE,
                                                         'files': {n: gateway.sha(b) for n, b in bodies.items()}}))
            if extra:
                archive.writestr(*extra)
        return stream.getvalue()

    def assert_protected(self):
        for path in self.protected:
            self.assertEqual(path.read_bytes(), b'synthetic protected content')
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT body FROM manuscripts WHERE id=?',('synthetic-id',)).fetchone()[0],
                             'synthetic manuscript')
        self.assertEqual(gateway.sha((self.app / 'backup.py').read_bytes()), self.baseline['backup.py'])

    def test_backup_deploy_and_explicit_rollback(self):
        mode = (self.app / 'static/app.js').stat().st_mode
        result = self.instance.deploy(self.expected, self.release())
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual((self.app / 'static/app.js').stat().st_mode, mode)
        backup = self.state / 'backups' / result['backup']
        self.assertEqual(set(p.relative_to(backup).as_posix() for p in backup.rglob('*') if p.is_file()),
                         {*gateway.FILES, 'record.json', 'database.sqlite3'})
        self.assertEqual(gateway.sha((backup / 'database.sqlite3').read_bytes()), result['database_snapshot_sha256'])
        self.assertEqual(self.service_actions,['stop','start'])
        self.assertEqual(len(self.events), 2)
        self.instance.rollback(result['fingerprint'])
        self.assertEqual(self.instance.current(), self.baseline)
        self.assertEqual(self.service_actions,['stop','start','stop','start'])
        gateway.schema_ready(self.database)  # Additive table is kept on code rollback.
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

    def test_database_snapshot_failure_restores_service_without_changing_code(self):
        with patch.object(gateway, 'snapshot_database', side_effect=OSError('synthetic snapshot failure')):
            with self.assertRaisesRegex(RuntimeError, 'original files restored and health verified'):
                self.instance.deploy(self.expected, self.release())
        self.assertEqual(self.instance.current(), self.baseline)
        self.assertEqual(self.service_actions, ['stop', 'start'])
        self.assertFalse((self.state / 'pending.json').exists())
        self.assert_protected()

    def test_wal_snapshot_with_read_only_database_directory(self):
        conn = sqlite3.connect(self.database)
        try:
            self.assertEqual(conn.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            conn.execute('CREATE TABLE manuscript_order(user_id TEXT PRIMARY KEY, ids TEXT NOT NULL, version INTEGER NOT NULL)')
            conn.execute('INSERT INTO manuscripts VALUES (?,?)', ('second-id', 'new data'))
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(Path(str(self.database) + '-wal').exists())
        original_mode = self.database.parent.stat().st_mode & 0o777
        self.database.parent.chmod(0o500)
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly database'):
                with sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True) as conn:
                    conn.execute('PRAGMA quick_check').fetchone()
            target = self.state / 'backups' / 'wal-snapshot.sqlite3'
            gateway.snapshot_database(self.database, target)
            with sqlite3.connect(target) as copy:
                self.assertEqual(copy.execute('SELECT body FROM manuscripts WHERE id=?', ('second-id',)).fetchone()[0], 'new data')
            gateway.schema_ready(self.database)
        finally:
            self.database.parent.chmod(original_mode)

    def test_snapshot_includes_uncheckpointed_wal(self):
        conn = sqlite3.connect(self.database)
        original_mode = self.database.parent.stat().st_mode & 0o777
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('INSERT INTO manuscripts VALUES (?,?)', ('wal-id', 'in the WAL'))
            conn.commit()
            self.assertTrue(Path(str(self.database) + '-wal').exists())
            self.database.parent.chmod(0o500)
            target = self.state / 'backups' / 'pending-wal.sqlite3'
            gateway.snapshot_database(self.database, target)
            with sqlite3.connect(target) as copy:
                self.assertEqual(copy.execute('SELECT body FROM manuscripts WHERE id=?', ('wal-id',)).fetchone()[0], 'in the WAL')
        finally:
            self.database.parent.chmod(original_mode)
            conn.close()

    def test_missing_additive_schema_restores_code_but_preserves_database(self):
        self.instance.verify_schema = lambda: (_ for _ in ()).throw(ValueError('synthetic schema check failure'))
        with self.assertRaisesRegex(RuntimeError, 'original files restored and health verified'):
            self.instance.deploy(self.expected, self.release())
        self.assertEqual(self.instance.current(), self.baseline)
        self.assertEqual(self.service_actions, ['stop', 'start', 'start'])
        self.assertFalse((self.state / 'pending.json').exists())
        gateway.schema_ready(self.database)
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
        self.instance = gateway.Gateway(self.app, self.state, self.database, lambda current: None,
                                        self.control, lambda: gateway.schema_ready(self.database))
        result = self.instance.deploy(gateway.fingerprint(self.baseline), self.release())
        self.assertTrue((self.app / 'static/edit-history.js').exists())
        self.instance.rollback(result['fingerprint'])
        self.assertFalse((self.app / 'static/edit-history.js').exists())
        self.assert_protected()
