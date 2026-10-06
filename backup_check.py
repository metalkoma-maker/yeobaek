#!/usr/bin/env python3
"""Read-only backup restore check; never writes to the live database."""
import argparse,sqlite3,tempfile
from pathlib import Path
from contextlib import closing
p=argparse.ArgumentParser();p.add_argument('backup',help='Path to a plaintext SQLite backup file');args=p.parse_args()
source=Path(args.backup).resolve()
if not source.is_file():raise SystemExit('BACKUP CHECK FAILED: file not found')
try:
 with tempfile.TemporaryDirectory(prefix='yeobaek-restore-test-') as folder:
  restored=Path(folder)/'restored.sqlite3'
  with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(restored)) as dst:
   src.backup(dst)
   if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('integrity check failed')
   if dst.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('foreign key check failed')
   users=dst.execute('SELECT count(*) FROM users').fetchone()[0]
   docs=dst.execute('SELECT count(*) FROM manuscripts').fetchone()[0]
   print('BACKUP CHECK OK - restored to temporary database')
   print('Users:',users,'Manuscripts:',docs)
except Exception as e:raise SystemExit('BACKUP CHECK FAILED: '+str(e))
