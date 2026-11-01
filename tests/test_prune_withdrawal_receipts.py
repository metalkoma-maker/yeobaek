"""Receipt cleanup uses only synthetic DBs and a fake Drive inventory."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
source = Path(__file__).resolve().parents[1] / 'deploy/prune_withdrawal_receipts.py'
spec = importlib.util.spec_from_file_location('prune_withdrawal_receipts', source)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.current = root / 'current.sqlite3'
        self.local = root / 'local'
        self.local.mkdir()
        self.state = root / 'state'
        (self.state / 'backups').mkdir(parents=True)
        self.state_config = root / 'actions.json'
        self.state_config.write_text(json.dumps({'state': str(self.state)}))
        self.uid = 'b' * 32
        self.epoch = 'a' * 32
        self.events = {self.uid: int(time.time()) - cleanup.MIN_AGE - 60}
        self.daily = {}
        self.deleted = []
        self.make_db(self.current)

    def make_db(self, path, user=False, request=False):
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE users(id TEXT PRIMARY KEY);
                CREATE TABLE withdrawal_state(epoch TEXT PRIMARY KEY);
                CREATE TABLE withdrawal_requests(user_id TEXT PRIMARY KEY);
                INSERT INTO withdrawal_state VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');''')
            if user:
                db.execute('INSERT INTO users VALUES(?)', (self.uid,))
            if request:
                db.execute('INSERT INTO withdrawal_requests VALUES(?)', (self.uid,))

    def fake_rclone(self, config, action, *args):
        if action == 'copyto':
            shutil.copyfile(self.daily[args[0].split(':', 1)[1]], args[1])
        elif action == 'deletefile':
            uid = Path(args[0]).stem
            self.deleted.append(uid)
            self.events.pop(uid)
        else:
            raise AssertionError(action)

    def run_prune(self, **kwargs):
        with patch.object(cleanup, 'receipts', side_effect=lambda *args: dict(self.events)), \
             patch.object(cleanup, 'daily_names', side_effect=lambda *args: sorted(self.daily)), \
             patch.object(cleanup, 'run_rclone', side_effect=self.fake_rclone), \
             patch.object(cleanup, 'require_stopped'):
            return cleanup.prune(self.current, self.local, self.state_config, **kwargs)

    def test_dry_run_and_apply_only_after_backups_no_longer_hold_id(self):
        old = self.local / 'yeobaek-older.sqlite3'
        self.make_db(old, user=True)
        self.assertEqual(self.run_prune()['eligible'], 0)
        self.assertEqual(self.deleted, [])
        old.unlink()
        self.make_db(old)
        self.assertEqual(self.run_prune()['eligible'], 1)
        self.assertEqual(self.deleted, [])
        with self.assertRaisesRegex(ValueError, 'unmanaged DB copies'):
            self.run_prune(apply=True)
        result = self.run_prune(apply=True, other_copies_reviewed=True)
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(self.deleted, [self.uid])

    def test_pending_request_in_any_backup_blocks_cleanup(self):
        saved = self.state / 'backups' / 'snapshot' / 'database.sqlite3'
        saved.parent.mkdir()
        self.make_db(saved, request=True)
        self.assertEqual(self.run_prune()['eligible'], 0)
        saved.unlink()
        self.make_db(saved)
        drive = Path(self.temp.name) / 'drive.sqlite3'
        self.make_db(drive, user=True)
        self.daily['yeobaek-daily-20261101-000000-000000.sqlite3'] = drive
        self.assertEqual(self.run_prune()['eligible'], 0)

    def test_unreadable_backup_and_current_account_fail_closed(self):
        old = self.local / 'yeobaek-bad.sqlite3'
        old.write_bytes(b'invalid')
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_prune(apply=True, other_copies_reviewed=True)
        self.assertEqual(self.deleted, [])
        old.unlink()
        with sqlite3.connect(self.current) as db:
            db.execute('INSERT INTO users VALUES(?)', (self.uid,))
        self.assertEqual(self.run_prune()['eligible'], 0)

    def test_recent_receipt_is_held_even_with_no_backups(self):
        self.events[self.uid] = int(time.time()) - cleanup.MIN_AGE + 60
        self.assertEqual(self.run_prune()['eligible'], 0)


if __name__ == '__main__':
    unittest.main()
