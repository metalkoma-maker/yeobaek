#!/usr/bin/env python3
"""Prepare a full DB restore without reviving accounts absent from the live DB.

This tool never replaces the live database. The current database must still be
readable and must not itself have been replaced by an older backup.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile


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


def prepare(current_path, backup_path, output_path):
    current_path, backup_path, output_path = map(Path, (current_path, backup_path, output_path))
    if current_path.resolve() == backup_path.resolve():
        raise ValueError('Current database and backup must be different files')
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError('Output already exists')
    if output_path.resolve() in (current_path.resolve(), backup_path.resolve()):
        raise ValueError('Output must not replace an input database')

    with closing(open_source(current_path)) as current:
        live_ids = {row[0] for row in current.execute('SELECT id FROM users')}
        with closing(open_source(backup_path)) as source:
            fd, temporary_name = tempfile.mkstemp(prefix='.yeobaek-restore-',
                                                   suffix='.sqlite3', dir=output_path.parent)
            os.close(fd)
            temporary = Path(temporary_name)
            try:
                with closing(sqlite3.connect(temporary)) as staged:
                    source.backup(staged)
                    staged.execute('PRAGMA foreign_keys=ON')
                    backup_ids = {row[0] for row in staged.execute('SELECT id FROM users')}
                    removed = backup_ids - live_ids
                    staged.execute('BEGIN IMMEDIATE')
                    staged.executemany('DELETE FROM users WHERE id=?', ((uid,) for uid in removed))
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
            'removed_accounts': len(removed), 'retained_accounts': len(backup_ids - removed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.current, args.backup, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
