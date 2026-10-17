#!/usr/bin/python3 -I
"""Restricted forced SSH command for code releases; never import production app code.

Run as yeobaek-deploy, with narrow sudo permission for one service's stop/start.
Production paths come only from a root-owned local configuration file.
"""
import fcntl
import hashlib
import io
import json
import os
from contextlib import closing
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

CONFIG = Path('/etc/yeobaek-actions.json')
FILES = ('app.py', 'static/edit-history.js', 'static/font-size.js', 'static/safety-storage.js',
         'static/app.js', 'static/style.css', 'static/index.html')  # HTML last
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
SCHEMA_CHANGE = 'add-manuscript-order-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(files):
    return sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def safe_path(root, name):
    path = root / name
    for ancestor in (root, *path.parents):
        if ancestor.is_symlink():
            raise ValueError('Symlink refused: ' + str(ancestor))
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe path: ' + name)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('Not a single regular file: ' + name)
    return path


def inventory(app, names):
    return {name: sha(safe_path(app, name).read_bytes())
            if safe_path(app, name).exists() else None for name in names}


def atomic(path, data, metadata=None):
    fd, temp = tempfile.mkstemp(prefix='.yeobaek-actions-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if metadata:
                os.fchown(stream.fileno(), metadata['uid'], metadata['gid'])
                os.fchmod(stream.fileno(), metadata['mode'])
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def payload(data):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Archive too large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != len(FILES) + 1 or set(x.filename for x in entries) != {*FILES, 'release.json'}:
            raise ValueError('Only approved code files and release.json are allowed')
        for entry in entries:
            mode = entry.external_attr >> 16
            if entry.file_size > MAX_FILE or entry.flag_bits & 1 or stat.S_ISLNK(mode) or entry.is_dir():
                raise ValueError('Unsafe archive entry')
        meta = json.loads(archive.read('release.json'))
        if not re.fullmatch('[0-9a-f]{40}', str(meta.get('commit', ''))):
            raise ValueError('Expected immutable Git commit')
        if meta.get('schema_change') != SCHEMA_CHANGE:
            raise ValueError('Unreviewed database schema change')
        contents = {name: archive.read(name) for name in FILES}
        if meta.get('files') != {name: sha(body) for name, body in contents.items()}:
            raise ValueError('Release digest mismatch')
        return meta, contents


def health(expected, config):
    host = config['host']
    subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', config['service']], check=True, timeout=10)
    # Test local Nginx -> Gunicorn using the real Host and valid TLS certificate.
    # No public DNS/outbound route dependency; no authentication or DB-writing API.
    for name in ('/', *(name for name in FILES if name.startswith('static/'))):
        url = 'https://' + host + ('/' + name if name != '/' else '/')
        body = subprocess.run(['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error',
                               '--fail', '--max-time', '10', '--max-filesize', str(MAX_FILE),
                               '--resolve', host + ':443:127.0.0.1',
                               '-H', 'Cache-Control: no-cache', url + '?actions-health=' + uuid.uuid4().hex],
                              check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        wanted = expected['static/index.html'] if name == '/' else expected[name]
        if sha(body) != wanted:
            raise ValueError('Served file mismatch: ' + name)


def wait_health(expected, config):
    for attempt in range(20):
        try:
            return health(expected, config)
        except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 19:
                raise
            time.sleep(0.5)


def schema_ready(database):
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='manuscript_order'").fetchone()
        if not row or 'user_id TEXT PRIMARY KEY' not in row[0] or 'version INTEGER NOT NULL' not in row[0]:
            raise ValueError('Expected additive manuscript_order table is missing')


def api_ready(config):
    host = config['host']
    response = subprocess.run(['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error',
                               '--fail', '--max-time', '10', '--max-filesize', '1024',
                               '--resolve', host + ':443:127.0.0.1',
                               'https://' + host + '/__deployment_health__'],
                              check=True, timeout=15, stdout=subprocess.PIPE).stdout
    if json.loads(response) != {'api': 'manuscript-order-v1'}:
        raise ValueError('New manuscript order API is not served by the restarted application')


def snapshot_database(database, target):
    if database.is_symlink() or not database.is_file() or database.stat().st_nlink != 1:
        raise ValueError('Expected one regular database file')
    if target.exists():
        raise ValueError('Database snapshot already exists')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(target)) as copy:
                source.backup(copy)
                if copy.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Database snapshot integrity check failed')
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    target.chmod(0o600)
    with target.open('rb') as saved:
        os.fsync(saved.fileno())
    digest = hashlib.sha256()
    with target.open('rb') as saved:
        for block in iter(lambda: saved.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class Gateway:
    def __init__(self, app, state, database, check, control, verify_schema):
        self.app, self.state, self.database = app, state, database
        self.check, self.control, self.verify_schema = check, control, verify_schema
        self.baseline = json.loads((state / 'baseline.json').read_text())['files']

    def current(self):
        return inventory(self.app, self.baseline)

    def inspect(self):
        current = self.current()
        latest = self.state / 'latest.json'
        pending = self.state / 'pending.json'
        return {'files': current, 'fingerprint': fingerprint(current),
                'pending_recovery': pending.exists(),
                'last_backup': json.loads(latest.read_text())['backup'] if latest.exists() else None,
                'capability': 'code-and-additive-manuscript-order-v1'}

    def require_expected(self, expected):
        current = self.current()
        if fingerprint(current) != expected:
            raise ValueError('Server changed since inspect; refused before writing')
        return current

    def backup(self, current):
        ident = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex
        directory = self.state / 'backups' / ident
        directory.mkdir(mode=0o700)
        metadata = {}
        for name in FILES:
            src = safe_path(self.app, name)
            info = src.stat() if src.exists() else None
            owner = info if info else src.parent.stat()
            metadata[name] = {'present': info is not None, 'mode': stat.S_IMODE(info.st_mode) if info else 0o644,
                              'uid': owner.st_uid, 'gid': owner.st_gid}
            if info:
                body = src.read_bytes()
                if sha(body) != current[name]:
                    raise ValueError('File changed during backup')
                dst = directory / name
                dst.parent.mkdir(mode=0o700, exist_ok=True)
                atomic(dst, body)
        record = {'backup': ident, 'before': current, 'metadata': metadata}
        write_json(directory / 'record.json', record)
        return record

    def backup_contents(self, record):
        ident = record['backup']
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}', ident):
            raise ValueError('Invalid backup identifier')
        directory = self.state / 'backups' / ident
        # Validate every backup BEFORE restoring any file.
        bodies = {}
        for name in FILES:
            meta = record['metadata'][name]
            if meta['present']:
                bodies[name] = safe_path(directory, name).read_bytes()
                if sha(bodies[name]) != record['before'][name]:
                    raise ValueError('Backup digest mismatch')
        return bodies

    def restore(self, record, bodies=None):
        bodies = self.backup_contents(record) if bodies is None else bodies
        for name in FILES:
            target = safe_path(self.app, name)
            if name in bodies:
                atomic(target, bodies[name], record['metadata'][name])
            else:
                target.unlink(missing_ok=True)
        if self.current() != record['before']:
            raise ValueError('Restored inventory differs; pending recovery retained')

    def deploy(self, expected, data):
        if (self.state / 'pending.json').exists():
            raise ValueError('Interrupted transaction; inspect then rollback first')
        meta, bodies = payload(data)
        current = self.require_expected(expected)
        for name in self.baseline:
            if name not in FILES and current[name] != self.baseline[name]:
                raise ValueError('Protected backend/backup code drift: ' + name)
        self.check(current)  # Refuse if service was already unhealthy.
        record = self.backup(current)
        old_contents = self.backup_contents(record)
        record.update(commit=meta['commit'], after={**current, **meta['files']})
        self.require_expected(expected)
        write_json(self.state / 'pending.json', record)
        try:
            self.control('stop')
            target = self.state / 'backups' / record['backup'] / 'database.sqlite3'
            record['database_snapshot_sha256'] = snapshot_database(self.database, target)
            write_json(self.state / 'pending.json', record)
            write_json(self.state / 'backups' / record['backup'] / 'record.json', record)
            for name in FILES:
                atomic(safe_path(self.app, name), bodies[name], record['metadata'][name])
            if self.current() != record['after']:
                raise ValueError('Post-deploy file mismatch')
            self.control('start')
            self.check(record['after'])
            self.verify_schema()
            write_json(self.state / 'latest.json', record)
            (self.state / 'pending.json').unlink()
        except BaseException as error:
            self.restore(record, old_contents)
            self.control('start')
            try:
                self.check(record['before'])
            except BaseException as health_error:
                raise RuntimeError('Original files restored; service still unhealthy: ' + str(health_error)) from error
            (self.state / 'pending.json').unlink()
            raise RuntimeError('Deployment failed; original files restored and health verified: ' + str(error)) from error
        return {'status': 'deployed', 'backup': record['backup'], 'commit': meta['commit'],
                'fingerprint': fingerprint(record['after']), 'database_snapshot_sha256': record['database_snapshot_sha256'],
                'database_change': 'additive table; automatic rollback restores code only'}

    def rollback(self, expected):
        self.require_expected(expected)
        pending = self.state / 'pending.json'
        source = pending if pending.exists() else self.state / 'latest.json'
        if not source.exists():
            raise ValueError('No deployment backup exists')
        record = json.loads(source.read_text())
        bodies = self.backup_contents(record)  # Validate while the service is still running.
        self.control('stop')
        self.restore(record, bodies)
        self.control('start')
        # Bytes are restored even when the service has an unrelated failure.
        self.check(record['before'])
        pending.unlink(missing_ok=True)
        return {'status': 'rolled_back', 'backup': record['backup'], 'fingerprint': fingerprint(self.current()),
                'database_change': 'database snapshot retained; additive table and user data not reverted'}


def main():
    if os.geteuid() == 0 or len(sys.argv) != 1:
        raise ValueError('Non-root forced command required')
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if not re.fullmatch(r'inspect|(?:deploy|rollback) [0-9a-f]{64}', command):
        raise ValueError('Only inspect, deploy HASH, rollback HASH are supported')
    # Keep interrupted operations recoverable; never accept arbitrary shell commands.
    def interrupted(signum, frame):
        raise RuntimeError('Deployment interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    if CONFIG.is_symlink() or CONFIG.stat().st_uid != 0 or CONFIG.stat().st_mode & 0o022:
        raise ValueError('Configuration must be root-owned and not writable by others')
    config = json.loads(CONFIG.read_text())
    app, state, database = Path(config['app']), Path(config['state']), Path(config['database'])
    if not all(path.is_absolute() for path in (app, state, database)):
        raise ValueError('Absolute local paths required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', config['host']) or not re.fullmatch(r'[A-Za-z0-9_.@-]+', config['service']):
        raise ValueError('Invalid configured service or host')
    with (state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def control(action):
            if action not in ('stop', 'start'):
                raise ValueError('Invalid service action')
            subprocess.run(['/usr/bin/sudo', '-n', '/usr/bin/systemctl', action, config['service']],
                           check=True, timeout=40)
        gateway = Gateway(app, state, database, lambda current: wait_health(current, config),
                          control, lambda: (schema_ready(database), api_ready(config)))
        if command == 'inspect':
            result = gateway.inspect()
        else:
            action, expected = command.split()
            if action == 'deploy':
                signal.alarm(60)  # Bound receiving data from an authenticated client.
                data = sys.stdin.buffer.read(MAX_ARCHIVE + 1)
                signal.alarm(0)
                result = gateway.deploy(expected, data)
            else:
                result = gateway.rollback(expected)
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('Yeobaek deployment failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
