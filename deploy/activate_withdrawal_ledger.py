#!/usr/bin/env python3
"""One-time activation of encrypted offsite withdrawal receipts.

Run on the production server before deploying the guarded app code. This does
not delete or replace any user or backup. The old app's deletion is blocked by
the new trigger until the guarded app code is deployed.
"""
import configparser
from contextlib import closing
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess


DATABASE = Path('/opt/yeobaek/data/novel.sqlite3')
CONFIG = Path('/root/.config/rclone/rclone.conf')
REMOTE = 'yeobaek_crypt:withdrawals'


def run(*args, input_data=None):
    command = ['rclone', '--config', str(CONFIG), '--retries', '1', '--low-level-retries', '1']
    return subprocess.run(command + list(args), input=input_data, check=True, timeout=30,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def verify_remote_config():
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
        raise ValueError('Expected root-only rclone configuration')
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(CONFIG) or 'yeobaek_crypt' not in parser:
        raise ValueError('Encrypted backup remote is not configured')
    crypt = parser['yeobaek_crypt']
    base = crypt.get('remote', '').split(':')[0]
    if crypt.get('type') != 'crypt' or not crypt.get('password') or parser.get(base, 'type', fallback='') != 'drive':
        raise ValueError('Expected encrypted Google Drive backup remote')


def verify_record(path, payload):
    if run('cat', path) != payload:
        raise ValueError('Withdrawal ledger readback mismatch')


def activate(database=DATABASE):
    if os.geteuid() != 0:
        raise PermissionError('Root is required to activate the withdrawal ledger')
    verify_remote_config()
    info = database.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Expected one production database file')
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=15)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'users' not in tables or conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Expected a healthy production account database')
        rows = conn.execute('SELECT epoch FROM withdrawal_state').fetchall() if 'withdrawal_state' in tables else []
        if len(rows) > 1:
            raise ValueError('Multiple withdrawal epochs are not supported')
        epoch = rows[0][0] if rows else secrets.token_hex(16)
        if not re.fullmatch(r'[0-9a-f]{32}', epoch):
            raise ValueError('Invalid withdrawal epoch')
        payload = json.dumps({'epoch': epoch, 'version': 1}, sort_keys=True, separators=(',', ':')).encode()
        root = REMOTE + '/' + epoch
        if rows:
            trigger = conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='users_delete_requires_withdrawal_receipt'").fetchone()
            if 'withdrawal_requests' not in tables or not trigger:
                raise ValueError('Withdrawal ledger database guard is incomplete')
            verify_record(root + '/anchor.json', payload)
            verify_record(root + '/users/_initialized.json', payload)
            return {'status': 'already_active'}
        run('rcat', root + '/anchor.json', input_data=payload)
        verify_record(root + '/anchor.json', payload)
        run('rcat', root + '/users/_initialized.json', input_data=payload)
        verify_record(root + '/users/_initialized.json', payload)
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE IF NOT EXISTS withdrawal_state(epoch TEXT PRIMARY KEY)')
        conn.execute('''CREATE TABLE IF NOT EXISTS withdrawal_requests(
            user_id TEXT PRIMARY KEY,requested INTEGER NOT NULL,
            remote_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(remote_confirmed IN (0,1)))''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS users_delete_requires_withdrawal_receipt BEFORE DELETE ON users
            WHEN NOT EXISTS(SELECT 1 FROM withdrawal_requests WHERE user_id=OLD.id AND remote_confirmed=1)
            BEGIN SELECT RAISE(ABORT, 'withdrawal receipt required'); END''')
        if conn.execute('SELECT 1 FROM withdrawal_state').fetchone():
            raise ValueError('Withdrawal ledger was activated concurrently')
        conn.execute('INSERT INTO withdrawal_state(epoch) VALUES(?)', (epoch,))
        conn.commit()
    return {'status': 'activated'}


if __name__ == '__main__':
    print(json.dumps(activate(), sort_keys=True))
