"""Create a shareable source archive, excluding credentials and local runtime files."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

def package():
    root=Path(__file__).resolve().parent.parent
    target=root.parent/'education-audit.zip'
    blocked={'.venv','__pycache__','.pytest_cache','.git'}
    with ZipFile(target,'w',ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            relative=path.relative_to(root)
            if not path.is_file() or any(part in blocked for part in relative.parts):
                continue
            if path.name=='.env' or path.suffix in ('.log','.pyc','.zip'):
                continue
            archive.write(path,Path(root.name)/relative)
    print(f'Created {target.name}: {target.stat().st_size} bytes. .env excluded.')

if __name__=='__main__':
    package()
