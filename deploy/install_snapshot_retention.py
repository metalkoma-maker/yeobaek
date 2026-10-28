"""Install and run 30-day retention for deployment-time DB snapshots only.

Installation is a one-time root operation. The hourly job runs as the restricted
deploy account and never opens or modifies the live database or code backups.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile


ACCOUNT = 'yeobaek-deploy'
CONFIG = Path('/etc/yeobaek-actions.json')
TARGET = Path('/usr/local/libexec/yeobaek-snapshot-retention')
SERVICE = Path('/etc/systemd/system/yeobaek-snapshot-retention.service')
TIMER = Path('/etc/systemd/system/yeobaek-snapshot-retention.timer')
RETENTION = timedelta(days=30)
SNAPSHOT = re.compile(r'^(\d{8}T\d{6}Z)-[0-9a-f]{32}$')


def regular(path, owner):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner:
        raise ValueError('Unexpected file type, owner, or link count: ' + str(path))
    return info


def directory(path, owner):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError('Unexpected directory type, owner, or write access: ' + str(path))


def state_path(account_uid):
    info = regular(CONFIG, 0)
    if info.st_mode & 0o022:
        raise ValueError('Deployment configuration is writable by others')
    state = Path(json.loads(CONFIG.read_text())['state'])
    if not state.is_absolute() or state == Path('/'):
        raise ValueError('Invalid deployment state path')
    for path in (state, *state.parents):
        if path.is_symlink():
            raise ValueError('Deployment state path crosses a symlink')
    directory(state, account_uid)
    directory(state / 'backups', account_uid)
    return state


@contextmanager
def deployment_lock(state):
    lock = state / 'lock'
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(lock, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise ValueError('Unexpected deployment lock file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


def snapshot_candidates(state, now):
    """Validate all candidates before removing any; code backups are excluded."""
    cutoff = now - RETENTION
    candidates = []
    for folder in (state / 'backups').iterdir():
        match = SNAPSHOT.fullmatch(folder.name)
        if not match:
            continue
        created = datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        if created > cutoff:
            continue
        directory(folder, os.geteuid())
        db = folder / 'database.sqlite3'
        if not db.exists() and not db.is_symlink():
            continue
        regular(db, os.geteuid())
        record = folder / 'record.json'
        regular(record, os.geteuid())
        if json.loads(record.read_text()).get('backup') != folder.name:
            raise ValueError('Snapshot metadata does not match its directory')
        candidates.append(db)
    return candidates


def retention_run(state, now, delete=False):
    if now.tzinfo is None:
        raise ValueError('Current time must be timezone-aware')
    with deployment_lock(state) as acquired:
        if not acquired:
            return {'status': 'busy', 'eligible': 0, 'removed': 0}
        # A partially completed deploy must keep all recovery material.
        if (state / 'pending.json').exists() or (state / 'pending.json').is_symlink():
            return {'status': 'pending_recovery', 'eligible': 0, 'removed': 0}
        candidates = snapshot_candidates(state, now)
        if delete:
            for path in candidates:
                path.unlink()
                fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        return {'status': 'pruned' if delete else 'inspect',
                'eligible': len(candidates), 'removed': len(candidates) if delete else 0}


def atomic_root_file(path, body, mode):
    fd, temporary = tempfile.mkstemp(prefix='.yeobaek-retention-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), mode)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def service_text(state):
    return ("[Unit]\nDescription=Remove deployment DB snapshots older than 30 days\n"
            "[Service]\nType=oneshot\nUser=yeobaek-deploy\nGroup=yeobaek-deploy\n"
            "UMask=0077\nNoNewPrivileges=yes\nPrivateTmp=yes\nPrivateDevices=yes\n"
            "ProtectHome=yes\nProtectSystem=strict\n"
            f"ReadWritePaths={state}\n"
            f"ExecStart=/usr/bin/python3 -I {TARGET} --prune\n").encode()


def timer_text():
    return ("[Unit]\nDescription=Hourly cleanup of 30-day deployment DB snapshots\n"
            "[Timer]\nOnCalendar=hourly\nPersistent=true\nAccuracySec=1min\n"
            "Unit=yeobaek-snapshot-retention.service\n"
            "[Install]\nWantedBy=timers.target\n").encode()


def command(*args):
    return subprocess.run(args, check=True, timeout=30, capture_output=True, text=True)


def install():
    if os.geteuid() != 0:
        raise ValueError('One-time installation requires root')
    account = pwd.getpwnam(ACCOUNT)
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise ValueError('Deploy account cannot be root')
    state = state_path(account.pw_uid)
    if any(character.isspace() for character in str(state)):
        raise ValueError('Deployment state path is not safe for a systemd unit')
    if state.is_relative_to(Path('/home')) or state.is_relative_to(Path('/root')):
        raise ValueError('Deployment state is hidden by ProtectHome; review service sandbox')
    source = Path(sys.argv[0])
    regular(source, 0)
    source_bytes = source.read_bytes()
    expected = {TARGET: (source_bytes, 0o755), SERVICE: (service_text(state), 0o644),
                TIMER: (timer_text(), 0o644)}
    existing = [path for path in expected if path.exists() or path.is_symlink()]
    if existing:
        if len(existing) != len(expected) or any(path.is_symlink() or not path.is_file() or
                path.stat().st_uid != 0 or path.stat().st_nlink != 1 or
                stat.S_IMODE(path.stat().st_mode) != mode or path.read_bytes() != body
                for path, (body, mode) in expected.items()):
            raise ValueError('A different or partial retention installation exists; review it before upgrading')
        command('/usr/bin/systemctl', 'is-active', '--quiet', TIMER.name)
        return {'status': 'already_installed'}
    created = []
    try:
        for path, (body, mode) in expected.items():
            atomic_root_file(path, body, mode)
            created.append(path)
        command('/usr/bin/systemctl', 'daemon-reload')
        inspect = command(shutil.which('runuser') or '/usr/sbin/runuser', '-u', ACCOUNT,
                          '--', '/usr/bin/python3', '-I', str(TARGET), '--inspect')
        report = json.loads(inspect.stdout)
        if report.get('status') != 'inspect':
            raise ValueError('The snapshot cleaner is not ready')
        command('/usr/bin/systemctl', 'enable', '--now', TIMER.name)
        command('/usr/bin/systemctl', 'is-active', '--quiet', TIMER.name)
        return {'status': 'installed', 'eligible_before_first_run': report['eligible']}
    except BaseException:
        try:
            subprocess.run(['/usr/bin/systemctl', 'disable', '--now', TIMER.name],
                           timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            subprocess.run(['/usr/bin/systemctl', 'daemon-reload'],
                           timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install', action='store_true')
    group.add_argument('--inspect', action='store_true')
    group.add_argument('--prune', action='store_true')
    args = parser.parse_args()
    if args.install:
        report = install()
    else:
        account = pwd.getpwnam(ACCOUNT)
        if os.geteuid() != account.pw_uid:
            raise ValueError('The hourly job must run as the restricted deploy account')
        state = state_path(account.pw_uid)
        report = retention_run(state, datetime.now(timezone.utc), delete=args.prune)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
