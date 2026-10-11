"""Build a six-file release only; never include DB, config, mobile or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from actions_gateway import FILES, MAX_FILE, safe_path


def build(root, output, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A Git commit SHA is required')
    bodies = {name: safe_path(root, name).read_bytes() for name in FILES}
    if any(len(body) > MAX_FILE for body in bodies.values()):
        raise ValueError('Release file too large')
    manifest = {'commit': commit, 'files': {n: hashlib.sha256(b).hexdigest() for n, b in bodies.items()}}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in bodies.items():
            archive.writestr(name, body)
        archive.writestr('release.json', json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output, args.commit)
