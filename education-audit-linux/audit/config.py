import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

def database_url():
    return URL.create('sqlite+pysqlite', database=str(database_path()))

def database_path():
    path=Path(os.getenv('DATABASE_PATH','data/education_audit.sqlite3')).expanduser()
    if not path.is_absolute():
        path=ROOT/path
    path=path.resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    return path

def settings():
    return {'max_pages': max(1, min(300, int(os.getenv('MAX_PAGES', '60')))),
            'max_documents': max(0, min(50, int(os.getenv('MAX_DOCUMENTS', '12')))),
            'seconds': max(10, int(os.getenv('CRAWL_SECONDS', '180'))),
            'timeout': max(1, int(os.getenv('REQUEST_TIMEOUT', '12'))),
            'delay': max(0, float(os.getenv('REQUEST_DELAY', '.3')))}
