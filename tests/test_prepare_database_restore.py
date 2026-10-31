"""A past backup may contain a withdrawn synthetic account and manuscript."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


source = Path(__file__).resolve().parents[1] / 'deploy/prepare_database_restore.py'
spec = importlib.util.spec_from_file_location('prepare_database_restore', source)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class PrepareDatabaseRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.current, self.backup, self.output = (root / name for name in
                                                   ('current.sqlite3', 'backup.sqlite3', 'staged.sqlite3'))
        with sqlite3.connect(self.current) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript('''
                CREATE TABLE users(id TEXT PRIMARY KEY, email TEXT);
                CREATE TABLE manuscripts(id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE, body TEXT);
                CREATE TABLE manuscript_history(manuscript_id TEXT REFERENCES manuscripts(id) ON DELETE CASCADE, body TEXT);
                CREATE TABLE sessions(token TEXT, user_id TEXT REFERENCES users(id) ON DELETE CASCADE);
                CREATE TABLE password_resets(token_hash TEXT, user_id TEXT REFERENCES users(id) ON DELETE CASCADE);
                CREATE TABLE attempts(key TEXT);
                INSERT INTO users VALUES('withdrawn', 'withdrawn@example.test'), ('active', 'active@example.test');
                INSERT INTO manuscripts VALUES('old', 'withdrawn', 'withdrawn text'), ('kept', 'active', 'kept text');
                INSERT INTO manuscript_history VALUES('old', 'old text');
                INSERT INTO sessions VALUES('old token', 'withdrawn');
                INSERT INTO password_resets VALUES('old reset', 'active');
                INSERT INTO attempts VALUES('old rate limit');
            ''')
            with sqlite3.connect(self.backup) as snapshot:
                db.backup(snapshot)
            db.execute("DELETE FROM users WHERE id='withdrawn'")

    def test_withdrawn_account_and_related_text_do_not_reappear(self):
        result = restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(result, {'status': 'prepared', 'backup_accounts': 2,
                                  'removed_accounts': 1, 'retained_accounts': 1})
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute('SELECT id FROM users').fetchall(), [('active',)])
            self.assertEqual(db.execute('SELECT body FROM manuscripts').fetchall(), [('kept text',)])
            for table in ('manuscript_history', 'sessions', 'password_resets', 'attempts'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        with sqlite3.connect(self.backup) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 2)
        with sqlite3.connect(self.current) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 1)

    def test_without_current_database_preparation_fails_closed(self):
        self.current.unlink()
        with self.assertRaises(FileNotFoundError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertFalse(self.output.exists())

    def test_current_database_with_uncheckpointed_wal_is_used(self):
        with sqlite3.connect(self.current) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("DELETE FROM users WHERE id='active'")
        result = restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(result['removed_accounts'], 2)
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)
        self.assertFalse(Path(str(self.output) + '-wal').exists())

    def test_existing_output_and_bad_backup_are_never_overwritten(self):
        self.output.write_text('existing result')
        with self.assertRaises(FileExistsError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(self.output.read_text(), 'existing result')
        self.output.unlink()
        self.backup.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
