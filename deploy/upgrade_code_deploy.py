"""One-time root setup for the restricted GitHub Actions code deployer.

Run only from a reviewed release on the server. It does not deploy application
code or alter the database; subsequent deploys use the forced SSH command.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid

from actions_gateway import CONFIG, FILES, inventory

ACCOUNT = 'yeobaek-deploy'
GATEWAY = Path('/usr/local/libexec/yeobaek-actions-gateway')
SUDOERS = Path('/etc/sudoers.d/yeobaek-actions-code')


def command(*args):
    subprocess.run(args, check=True, timeout=30)


def one_public_key(contents):
    keys = re.findall(r'(?<![A-Za-z0-9_-])ssh-ed25519\s+[A-Za-z0-9+/]+={0,2}', contents)
    if len(keys) != 1:
        raise ValueError('Exactly one existing or supplied Ed25519 deployment public key is required')
    return keys[0]


def write_owned(path, contents, mode, uid=0, gid=0):
    fd, temporary = tempfile.mkstemp(prefix='.yeobaek-setup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_paths(config, database, account):
    app, state = Path(config['app']), Path(config['state'])
    if not all(path.is_absolute() and path != Path('/') for path in (app, state, database)):
        raise ValueError('App, state and database must be non-root absolute paths')
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+', config['service']):
        raise ValueError('Invalid systemd service name')
    if not app.is_dir() or not state.is_dir() or not database.is_file() or database.is_symlink():
        raise ValueError('Existing app, state and regular database are required')
    for path in (app, state, database):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('Deployment paths cannot traverse symlinks')
    if database.stat().st_nlink != 1 or state == app or state.is_relative_to(app) or app.is_relative_to(state):
        raise ValueError('Unsafe deployment path overlap or linked database')
    for root, dirs, files in os.walk(state, followlinks=False):
        if any((Path(root) / name).is_symlink() for name in [*dirs, *files]):
            raise ValueError('Deployment state contains a symlink')
    baseline = json.loads((state / 'baseline.json').read_text())['files']
    if any(name not in baseline for name in FILES):
        raise ValueError('Existing approved-code baseline is missing an allowed release file')
    current = inventory(app, baseline)
    for name in baseline:
        if name not in FILES and current[name] != baseline[name]:
            raise ValueError('Protected server code differs from its approved baseline: ' + name)
    for name in FILES:
        path = app / name
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError('Expected a single regular release file: ' + name)
        if not path.stat().st_mode & stat.S_IROTH:
            raise ValueError('Service-readable code file required before ownership change: ' + name)
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise ValueError('Deployment account cannot have root user or group privileges')
    if account.pw_shell.endswith(('nologin', 'false')):
        raise ValueError('Forced SSH command needs the existing deploy account shell')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as source:
        if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed')
    return app, state


def grant_traverse(path, username):
    for directory in reversed(path.parents):
        if directory != Path('/'):
            command('/usr/bin/setfacl', '-m', f'u:{username}:--x', str(directory))


def database_of_running_service(service):
    result = subprocess.run(['/usr/bin/systemctl', 'show', '-p', 'MainPID', '--value', service],
                            check=True, timeout=10, capture_output=True, text=True)
    pid = result.stdout.strip()
    if not pid.isdecimal() or int(pid) <= 1:
        raise ValueError('The configured application service is not running')
    proc = Path('/proc') / pid
    entries = (proc / 'environ').read_bytes().split(b'\0')
    paths = [entry.split(b'=', 1)[1] for entry in entries if entry.startswith(b'DATABASE_PATH=')]
    if len(paths) > 1:
        raise ValueError('Conflicting DATABASE_PATH values in the service')
    raw = os.fsdecode(paths[0]) if paths else 'data/novel.sqlite3'
    return Path(os.path.abspath(Path(os.readlink(proc / 'cwd')) / raw))


def install(database=None, public_key_file=None):
    if os.geteuid() != 0:
        raise ValueError('One-time setup requires administrator privileges')
    for executable in ('setfacl', 'visudo', 'runuser', 'sudo', 'systemctl', 'passwd'):
        if not shutil.which(executable):
            raise ValueError('Required server tool is missing: ' + executable)
    info = pwd.getpwnam(ACCOUNT)
    if CONFIG.is_symlink() or CONFIG.stat().st_uid != 0 or CONFIG.stat().st_mode & 0o022:
        raise ValueError('Existing deployment configuration must be protected and root-owned')
    config = json.loads(CONFIG.read_text())
    detected_database = database_of_running_service(config['service'])
    if database is not None and database.resolve() != detected_database:
        raise ValueError('Supplied database does not match the running service database')
    database = detected_database
    app, state = validate_paths(config, database, info)
    authorized = Path(info.pw_dir) / '.ssh' / 'authorized_keys'
    if authorized.is_symlink() or authorized.parent.is_symlink() or SUDOERS.is_symlink() or GATEWAY.parent.is_symlink():
        raise ValueError('Deployment key or installer target cannot be a symlink')
    if public_key_file:
        key = one_public_key(public_key_file.read_text())
    else:
        key = one_public_key(authorized.read_text())
    source_gateway = Path(__file__).with_name('actions_gateway.py')
    if not source_gateway.is_file() or source_gateway.is_symlink():
        raise ValueError('Reviewed gateway source is missing')
    command('/usr/bin/systemctl', 'is-active', '--quiet', config['service'])
    # Keep the prior config and key for a separate administrator recovery.
    suffix = '.before-code-deploy-' + uuid.uuid4().hex
    prior_config = CONFIG.with_name(CONFIG.name + suffix)
    prior_key = authorized.with_name(authorized.name + suffix)
    shutil.copy2(CONFIG, prior_config)
    if authorized.exists():
        shutil.copy2(authorized, prior_key)
    config['database'] = str(database)
    write_owned(CONFIG, (json.dumps(config, indent=2, sort_keys=True) + '\n').encode(), 0o640, 0, info.pw_gid)
    # Existing state holds code snapshots only; never chown the manuscript DB.
    for root, dirs, files in os.walk(state, followlinks=False):
        for name in [*dirs, *files]:
            target = Path(root) / name
            if target.is_symlink():
                raise ValueError('Symlink in deploy state: ' + str(target))
            os.chown(target, info.pw_uid, info.pw_gid)
        os.chown(root, info.pw_uid, info.pw_gid)
    for path in (app, app / 'static', state, database):
        grant_traverse(path, ACCOUNT)
    for directory in (app, app / 'static'):
        command('/usr/bin/setfacl', '-m', f'u:{ACCOUNT}:rwx', str(directory))
    for name in FILES:
        os.chown(app / name, info.pw_uid, info.pw_gid)
    command('/usr/bin/setfacl', '-m', f'u:{ACCOUNT}:r--', str(database))
    command('/usr/bin/setfacl', '-d', '-m', f'u:{ACCOUNT}:r--', str(database.parent))
    for suffix in ('-wal', '-shm'):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            command('/usr/bin/setfacl', '-m', f'u:{ACCOUNT}:r--', str(sidecar))
    GATEWAY.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    write_owned(GATEWAY, source_gateway.read_bytes(), 0o755)
    sudoers = (f'{ACCOUNT} ALL=(root) NOPASSWD: /usr/bin/systemctl stop {config["service"]}, '
               f'/usr/bin/systemctl start {config["service"]}\n')
    fd, trial = tempfile.mkstemp(prefix='.yeobaek-sudoers-', dir=SUDOERS.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(sudoers)
        command(shutil.which('visudo'), '-cf', trial)
        write_owned(SUDOERS, sudoers.encode(), 0o440)
    finally:
        Path(trial).unlink(missing_ok=True)
    authorized.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(authorized.parent, info.pw_uid, info.pw_gid)
    os.chmod(authorized.parent, 0o700)
    line = f'restrict,command="{GATEWAY}" {key}\n'
    write_owned(authorized, line.encode(), 0o600, info.pw_uid, info.pw_gid)
    command(shutil.which('passwd'), '-l', ACCOUNT)
    read_check = ('import sqlite3,sys; c=sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro",uri=True); '
                  'assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"')
    command(shutil.which('runuser'), '-u', ACCOUNT, '--', '/usr/bin/python3', '-c',
            'from pathlib import Path; ' + read_check, str(database))
    for action in ('stop', 'start'):
        command(shutil.which('runuser'), '-u', ACCOUNT, '--', '/usr/bin/sudo', '-n', '-l',
                '/usr/bin/systemctl', action, config['service'])
    command(shutil.which('runuser'), '-u', ACCOUNT, '--', '/usr/bin/env',
            'SSH_ORIGINAL_COMMAND=inspect', '/usr/bin/python3', '-I', str(GATEWAY))
    print('Restricted code deployer installed; app, database and service were not changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, help='Optional cross-check against the running service')
    parser.add_argument('--public-key-file', type=Path)
    args = parser.parse_args()
    try:
        install(args.database, args.public_key_file)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('One-time deploy setup failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
