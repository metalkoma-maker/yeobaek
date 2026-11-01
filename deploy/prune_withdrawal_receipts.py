#!/usr/bin/env python3
"""Remove aged withdrawal receipts only after checking every managed DB backup.

Dry run by default. An apply run requires the web and backup services stopped
and an operator's review of copies outside the managed backup locations.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time

from prepare_database_restore import regular_file

REMOTE = 'yeobaek_crypt:withdrawals'
BACKUP_REMOTE = 'yeobaek_crypt:'
CONFIG = '/root/.config/rclone/rclone.conf'
CURRENT = Path('/opt/yeobaek/data/novel.sqlite3')
LOCAL = Path('/var/backups/yeobaek')
STATE_CONFIG = Path('/etc/yeobaek-actions.json')
MIN_AGE = 30 * 24 * 60 * 60
ID = re.compile(r'[0-9a-f]{32}')
DAILY = re.compile(r'yeobaek-daily-\d{8}-\d{6}-\d{6}\.sqlite3')


def run_rclone(config, *args):
    return subprocess.run(['rclone', '--config', str(config), '--retries', '1',
                           '--low-level-retries', '1', *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=600).stdout


def json_remote(config, *args):
    return json.loads(run_rclone(config, *args))


def receipts(epoch, config, remote):
    root = remote.rstrip('/') + '/' + epoch
    expected = {'epoch': epoch, 'version': 1}
    if json_remote(config, 'cat', root + '/anchor.json') != expected:
        raise ValueError('Withdrawal anchor differs from the current database')
    if json_remote(config, 'cat', root + '/users/_initialized.json') != expected:
        raise ValueError('Withdrawal directory marker is missing')
    rows = json_remote(config, 'lsjson', root + '/users', '--files-only')
    if not isinstance(rows, list):
        raise ValueError('Withdrawal listing is invalid')
    events = {}
    marker = False
    for row in rows:
        name = row.get('Path')
        if name == '_initialized.json':
            marker = True
            continue
        if not isinstance(name, str) or not re.fullmatch(r'[0-9a-f]{32}\.json', name):
            raise ValueError('Unexpected withdrawal entry')
        user_id = name[:-5]
        event = json_remote(config, 'cat', root + '/users/' + name)
        if (not isinstance(event, dict) or event.get('epoch') != epoch or
                event.get('user_id') != user_id or type(event.get('requested')) is not int or
                event['requested'] <= 0):
            raise ValueError('Withdrawal entry failed verification')
        events[user_id] = event['requested']
    if not marker:
        raise ValueError('Withdrawal directory marker was not listed')
    return events


def database_ids(path, expected_epoch=None):
    regular_file(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('A database failed integrity check')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'users' not in tables:
            raise ValueError('A database lacks the users table')
        epochs = [row[0] for row in db.execute('SELECT epoch FROM withdrawal_state')] if 'withdrawal_state' in tables else []
        if len(epochs) > 1 or (expected_epoch is not None and epochs and epochs[0] != expected_epoch):
            raise ValueError('A database has an unexpected withdrawal epoch')
        users = {row[0] for row in db.execute('SELECT id FROM users')}
        pending = ({row[0] for row in db.execute('SELECT user_id FROM withdrawal_requests')}
                   if 'withdrawal_requests' in tables else set())
        return users | pending, epochs


def backup_paths(local, state_config):
    if not local.is_dir():
        raise FileNotFoundError('Local backup directory is missing')
    state = Path(json.loads(state_config.read_text())['state']) / 'backups'
    if not state.is_dir():
        raise FileNotFoundError('Deployment backup directory is missing')
    return sorted(local.glob('yeobaek-*.sqlite3')) + sorted(state.glob('*/database.sqlite3'))


def daily_names(config, remote):
    rows = json_remote(config, 'lsjson', remote, '--files-only')
    if not isinstance(rows, list):
        raise ValueError('Drive backup listing is invalid')
    names = []
    for row in rows:
        name = row.get('Path')
        if not isinstance(name, str):
            raise ValueError('Drive backup has an invalid name')
        if name.startswith('yeobaek-daily-'):
            if not DAILY.fullmatch(name):
                raise ValueError('Unexpected Drive backup name')
            names.append(name)
    return sorted(names)


def require_stopped():
    for service in ('yeobaek.service', 'yeobaek-backup.service',
                    'yeobaek-drive-backup.service', 'yeobaek-snapshot-retention.service'):
        result = subprocess.run(['systemctl', 'is-active', '--quiet', service],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=10)
        if result.returncode == 0:
            raise RuntimeError('Stop the web and backup services before applying receipt cleanup')
        if result.returncode not in (3, 4):
            raise RuntimeError('Could not verify service state')


def prune(current=CURRENT, local=LOCAL, state_config=STATE_CONFIG,
          config=CONFIG, remote=REMOTE, backup_remote=BACKUP_REMOTE,
          apply=False, other_copies_reviewed=False):
    current, local, state_config = map(Path, (current, local, state_config))
    if apply and not other_copies_reviewed:
        raise ValueError('Review unmanaged DB copies before applying cleanup')
    if apply:
        require_stopped()
    current_ids, epochs = database_ids(current)
    if len(epochs) != 1 or not ID.fullmatch(epochs[0]):
        raise ValueError('Current database has no valid withdrawal epoch')
    epoch = epochs[0]
    events = receipts(epoch, config, remote)
    paths = backup_paths(local, state_config)
    names = daily_names(config, backup_remote)
    held_ids = set(current_ids)
    for path in paths:
        ids, _ = database_ids(path, epoch)
        held_ids.update(ids)
    with tempfile.TemporaryDirectory(prefix='yeobaek-receipt-audit-') as folder:
        temporary = Path(folder) / 'backup.sqlite3'
        for name in names:
            run_rclone(config, 'copyto', backup_remote + name, str(temporary))
            ids, _ = database_ids(temporary, epoch)
            held_ids.update(ids)
            temporary.unlink()
    cutoff = int(time.time()) - MIN_AGE
    eligible = {uid for uid, requested in events.items()
                if requested <= cutoff and uid not in held_ids}
    if apply:
        # A new backup or account appearing while scanning invalidates the audit.
        require_stopped()
        if backup_paths(local, state_config) != paths or daily_names(config, backup_remote) != names:
            raise RuntimeError('Backup inventory changed during audit')
        if database_ids(current, epoch)[0] != current_ids or receipts(epoch, config, remote) != events:
            raise RuntimeError('Account or receipt inventory changed during audit')
        root = remote.rstrip('/') + '/' + epoch + '/users/'
        for uid in sorted(eligible):
            run_rclone(config, 'deletefile', root + uid + '.json')
        remaining = receipts(epoch, config, remote)
        if any(uid in remaining for uid in eligible):
            raise RuntimeError('Receipt deletion could not be verified')
    return {'status': 'applied' if apply else 'dry_run',
            'receipts': len(events), 'eligible': len(eligible),
            'managed_backups_checked': len(paths) + len(names),
            'deleted': len(eligible) if apply else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--other-copies-reviewed', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prune(apply=args.apply,
                           other_copies_reviewed=args.other_copies_reviewed), sort_keys=True))


if __name__ == '__main__':
    main()
