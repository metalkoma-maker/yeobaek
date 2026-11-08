"""Isolated cleanup tests using fake deployment records and database files."""
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    'snapshot_retention', Path(__file__).resolve().parents[1] / 'deploy/install_snapshot_retention.py')
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


class SnapshotRetentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        (self.state / 'backups').mkdir(parents=True)
        (self.state / 'lock').write_text('')
        self.live_db = self.root / 'live.sqlite3'
        self.live_db.write_bytes(b'LIVE')

    def snapshot(self, age, suffix='a' * 32):
        timestamp = (NOW - age).strftime('%Y%m%dT%H%M%SZ')
        folder = self.state / 'backups' / f'{timestamp}-{suffix}'
        folder.mkdir()
        db = folder / 'database.sqlite3'
        db.write_bytes(b'SYNTHETIC DB')
        (folder / 'record.json').write_text(json.dumps({'backup': folder.name}))
        (folder / 'static').mkdir()
        (folder / 'static' / 'app.js').write_bytes(b'SYNTHETIC CODE')
        return folder, db

    def test_only_expired_database_snapshots_are_removed(self):
        old_folder, old_db = self.snapshot(timedelta(days=30, minutes=1))
        new_folder, new_db = self.snapshot(timedelta(days=29), 'b' * 32)
        (self.state / 'latest.json').write_text(json.dumps({'backup': old_folder.name}))
        preview = retention.retention_run(self.state, NOW)
        self.assertEqual(preview, {'status': 'inspect', 'eligible': 1, 'removed': 0})
        self.assertTrue(old_db.exists())
        self.assertEqual(retention.retention_run(self.state, NOW, delete=True)['removed'], 1)
        self.assertFalse(old_db.exists())
        self.assertTrue(new_db.exists())
        self.assertEqual((old_folder / 'static/app.js').read_bytes(), b'SYNTHETIC CODE')
        self.assertTrue((old_folder / 'record.json').exists())
        self.assertTrue((self.state / 'latest.json').exists())
        self.assertEqual(self.live_db.read_bytes(), b'LIVE')
        self.assertEqual(retention.retention_run(self.state, NOW, delete=True)['removed'], 0)

    def test_exact_30_day_boundary_is_eligible(self):
        _, db = self.snapshot(timedelta(days=30))
        self.assertEqual(retention.retention_run(self.state, NOW)['eligible'], 1)
        self.assertTrue(db.exists())

    def test_pending_recovery_and_busy_deploy_preserve_snapshots(self):
        _, db = self.snapshot(timedelta(days=31))
        pending = self.state / 'pending.json'
        pending.write_text('{}')
        self.assertEqual(retention.retention_run(self.state, NOW, delete=True)['status'],
                         'pending_recovery')
        pending.unlink()
        with (self.state / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(retention.retention_run(self.state, NOW, delete=True)['status'],
                             'busy')
        self.assertTrue(db.exists())

    def test_invalid_metadata_aborts_before_any_deletion(self):
        _, good_db = self.snapshot(timedelta(days=31))
        bad_folder, _ = self.snapshot(timedelta(days=32), 'b' * 32)
        (bad_folder / 'record.json').write_text(json.dumps({'backup': 'wrong'}))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            retention.retention_run(self.state, NOW, delete=True)
        self.assertTrue(good_db.exists())

    def test_symlink_and_hardlink_are_rejected(self):
        _, good_db = self.snapshot(timedelta(days=31))
        _, bad_db = self.snapshot(timedelta(days=32), 'b' * 32)
        bad_db.unlink()
        bad_db.symlink_to(self.live_db)
        with self.assertRaises(ValueError):
            retention.retention_run(self.state, NOW, delete=True)
        self.assertTrue(good_db.exists())
        bad_db.unlink()
        os.link(self.live_db, bad_db)
        with self.assertRaises(ValueError):
            retention.retention_run(self.state, NOW, delete=True)
        self.assertEqual(self.live_db.read_bytes(), b'LIVE')

    def test_missing_lock_does_not_create_state_file(self):
        _, db = self.snapshot(timedelta(days=31))
        (self.state / 'lock').unlink()
        with self.assertRaises(FileNotFoundError):
            retention.retention_run(self.state, NOW, delete=True)
        self.assertTrue(db.exists())
        self.assertFalse((self.state / 'lock').exists())


if __name__ == '__main__':
    unittest.main()
