"""Create a shareable source archive, excluding credentials and local runtime files."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import sqlite3
import uuid
from contextlib import closing

def package(source_only=False):
    root=Path(__file__).resolve().parent.parent
    target=root.parent/('education-audit-linux-source.zip' if source_only else 'education-audit-linux.zip')
    blocked={'.venv','__pycache__','.pytest_cache','.git','.runtime'}
    with ZipFile(target,'w',ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            relative=path.relative_to(root)
            if not path.is_file() or any(part in blocked for part in relative.parts):
                continue
            if path.name=='.env' or path.suffix in ('.log','.pyc','.zip','.sqlite3','.db','.lock') or path.name.endswith(('-wal','-shm')):
                continue
            if source_only and path.name.endswith('.migration.json'):continue
            archive.write(path,Path(root.name)/relative)
        database=root/'data/education_audit.sqlite3'
        if not source_only and database.exists():
            scratch=root/'.runtime'
            scratch.mkdir(exist_ok=True)
            temporary=scratch/('package-'+uuid.uuid4().hex+'.sqlite3')
            with temporary.open('xb'):pass
            try:
                with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as read,closing(sqlite3.connect(temporary)) as snapshot:
                    read.backup(snapshot)
                    # Portable snapshot is a single closed file, with no WAL sidecars.
                    snapshot.execute('PRAGMA journal_mode=DELETE')
                    assert snapshot.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                archive.writestr(root.name+'/data/education_audit.sqlite3',temporary.read_bytes())
            finally:
                temporary.unlink(missing_ok=True)
        # Unix execution bits and LF scripts are preserved in the distributable.
        for item in archive.filelist:
            if item.filename.endswith('.sh'):
                item.create_system=3
                item.external_attr=0o100755<<16
    print(f'Created {target.name}: {target.stat().st_size} bytes. .env excluded.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-only',action='store_true')
    package(parser.parse_args().source_only)
