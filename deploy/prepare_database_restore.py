#!/usr/bin/env python3
"""Prepare a full DB restore after filtering recorded withdrawals.

This tool never replaces the live database. Use a trustworthy current database,
or the verified independent withdrawal receipts for post-activation backups.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile


REMOTE = 'yeobaek_crypt:withdrawals'
RCLONE_CONFIG = '/root/.config/rclone/rclone.conf'
HEX_ID = re.compile(r'[0-9a-f]{32}')


def remote_withdrawals(epoch, remote=REMOTE, config=RCLONE_CONFIG):
    if not HEX_ID.fullmatch(epoch):
        raise ValueError('Backup has no valid withdrawal epoch')
    command = ['rclone', '--config', config, '--retries', '1', '--low-level-retries', '1']

    def run(*args):
        return subprocess.run(command + list(args), check=True, timeout=60,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    root = remote.rstrip('/') + '/' + epoch
    anchor = json.loads(run('cat', root + '/anchor.json'))
    if anchor != {'epoch': epoch, 'version': 1}:
        raise ValueError('Withdrawal ledger anchor does not match the backup')
    marker = json.loads(run('cat', root + '/users/_initialized.json'))
    if marker != anchor:
        raise ValueError('Withdrawal ledger directory is incomplete')
    rows = json.loads(run('lsjson', root + '/users', '--files-only'))
    if not isinstance(rows, list):
        raise ValueError('Withdrawal ledger listing is invalid')
    withdrawn = set()
    for item in rows:
        name = item.get('Path')
        if name == '_initialized.json':
            continue
        if not isinstance(name, str) or not re.fullmatch(r'[0-9a-f]{32}\.json', name):
            raise ValueError('Unexpected withdrawal ledger entry')
        user_id = name[:-5]
        event = json.loads(run('cat', root + '/users/' + name))
        if event.get('epoch') != epoch or event.get('user_id') != user_id or type(event.get('requested')) is not int:
            raise ValueError('Withdrawal ledger entry does not match its name')
        withdrawn.add(user_id)
    return withdrawn


def regular_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Expected one regular database file')


def open_source(path):
    regular_file(path)
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)
    try:
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Database has broken references')
        if not {'users', 'manuscripts', 'sessions', 'password_resets', 'attempts'} <= {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            raise ValueError('Expected account tables are missing')
    except BaseException:
        connection.close()
        raise
    return connection


def prepare(current_path, backup_path, output_path, use_remote=False,
            remote=REMOTE, config=RCLONE_CONFIG):
    backup_path, output_path = map(Path, (backup_path, output_path))
    current_path = Path(current_path) if current_path is not None else None
    if current_path is None and not use_remote:
        raise ValueError('A current database or independent withdrawal ledger is required')
    if current_path is not None and current_path.resolve() == backup_path.resolve():
        raise ValueError('Current database and backup must be different files')
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError('Output already exists')
    if output_path.resolve() in ({backup_path.resolve()} | ({current_path.resolve()} if current_path else set())):
        raise ValueError('Output must not replace an input database')

    live_ids = None
    if current_path is not None:
        with closing(open_source(current_path)) as current:
            live_ids = {row[0] for row in current.execute('SELECT id FROM users')}
    with closing(open_source(backup_path)) as source:
        protected = source.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='users_delete_requires_withdrawal_receipt'").fetchone() is not None
        if protected and not use_remote:
            raise ValueError('This backup requires the independent withdrawal ledger')
        withdrawn = set()
        if use_remote:
            state = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='withdrawal_state'").fetchone()
            epoch_rows = source.execute('SELECT epoch FROM withdrawal_state').fetchall() if state else []
            if len(epoch_rows) != 1:
                raise ValueError('Backup predates withdrawal ledger activation')
            withdrawn = remote_withdrawals(epoch_rows[0][0], remote, config)
        fd, temporary_name = tempfile.mkstemp(prefix='.yeobaek-restore-',
                                               suffix='.sqlite3', dir=output_path.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with closing(sqlite3.connect(temporary)) as staged:
                source.backup(staged)
                staged.execute('PRAGMA foreign_keys=ON')
                backup_ids = {row[0] for row in staged.execute('SELECT id FROM users')}
                removed = (backup_ids - live_ids if live_ids is not None else set()) | (backup_ids & withdrawn)
                if protected and not removed <= withdrawn:
                    raise ValueError('A removed account has no verified withdrawal receipt')
                staged.execute('BEGIN IMMEDIATE')
                if protected:
                    staged.executemany('''INSERT INTO withdrawal_requests(user_id,requested,remote_confirmed)
                        VALUES(?,?,1) ON CONFLICT(user_id) DO UPDATE SET remote_confirmed=1''',
                                       ((uid,0) for uid in removed))
                staged.executemany('DELETE FROM users WHERE id=?', ((uid,) for uid in removed))
                if protected:
                    staged.executemany('DELETE FROM withdrawal_requests WHERE user_id=?',
                                       ((uid,) for uid in removed))
                # A restore never carries login sessions, reset links, or
                # rate-limit records from a different point in time.
                for table in ('sessions', 'password_resets', 'attempts'):
                    staged.execute('DELETE FROM ' + table)
                if staged.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise ValueError('Staged database has broken references')
                if staged.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Staged database integrity check failed')
                staged.commit()
            with temporary.open('rb') as file:
                os.fsync(file.fileno())
            # Link rather than rename so an output created concurrently is
            # never overwritten. The temporary file has mode 0600.
            os.link(temporary, output_path)
            parent = os.open(output_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            temporary.unlink(missing_ok=True)
    return {'status': 'prepared', 'backup_accounts': len(backup_ids),
            'removed_accounts': len(removed), 'retained_accounts': len(backup_ids - removed),
            'withdrawal_receipts': len(withdrawn) if use_remote else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=Path)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--use-withdrawal-ledger', action='store_true')
    parser.add_argument('--rclone-config', default=RCLONE_CONFIG)
    args = parser.parse_args()
    print(json.dumps(prepare(args.current, args.backup, args.output,
                             use_remote=args.use_withdrawal_ledger, config=args.rclone_config), sort_keys=True))


if __name__ == '__main__':
    main()
