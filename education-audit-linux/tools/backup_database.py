"""Create a consistent SQLite backup while the app is running."""
import argparse
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from audit.config import database_path

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    source=database_path()
    if not source.exists():raise SystemExit('Start the app once to create the database.')
    target=args.destination.resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb'):pass
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as read,sqlite3.connect(target) as write:
        read.backup(write)
        assert write.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    print('Backup saved:',target)
