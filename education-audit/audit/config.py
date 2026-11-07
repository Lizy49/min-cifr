import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

def database_url():
    return URL.create('mysql+pymysql', username=os.getenv('DB_USER', 'education_audit'),
        password=os.getenv('DB_PASSWORD', ''), host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')), database=os.getenv('DB_NAME', 'education_audit'),
        query={'charset': 'utf8mb4'})

def settings():
    return {'max_pages': max(1, min(300, int(os.getenv('MAX_PAGES', '60')))),
            'max_documents': max(0, min(50, int(os.getenv('MAX_DOCUMENTS', '12')))),
            'seconds': max(10, int(os.getenv('CRAWL_SECONDS', '180'))),
            'timeout': max(1, int(os.getenv('REQUEST_TIMEOUT', '12'))),
            'delay': max(0, float(os.getenv('REQUEST_DELAY', '.3')))}
