"""Copy all four tables from old MySQL to a NEW SQLite file; source is read-only."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from dotenv import dotenv_values
from sqlalchemy import create_engine,select
from sqlalchemy.engine import URL
from audit.models import Base,connect,init_database,utcnow
from audit.config import ROOT

def migrate(source_env,destination):
    values=dotenv_values(source_env)
    if not all(values.get(key) for key in ('DB_HOST','DB_NAME','DB_USER','DB_PASSWORD')):
        raise ValueError('Source .env lacks MySQL connection settings.')
    source=create_engine(URL.create('mysql+pymysql',username=values['DB_USER'],password=values['DB_PASSWORD'],
        host=values['DB_HOST'],port=int(values.get('DB_PORT') or '3306'),database=values['DB_NAME'],
        query={'charset':'utf8mb4'}),connect_args={'connect_timeout':5,'read_timeout':15})
    destination=Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('Destination exists. Use a new filename; existing SQLite data is never replaced.')
    snapshot={}
    try:
        with source.connect() as read:
            with read.begin():
                for table in Base.metadata.sorted_tables:
                    snapshot[table.name]=[dict(row) for row in read.execute(select(table).order_by(table.c.id)).mappings()]
    finally:source.dispose()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb'):pass
    engine,_=connect(URL.create('sqlite+pysqlite',database=str(destination)))
    try:
        init_database(engine)
        with engine.begin() as write:
            for table in Base.metadata.sorted_tables:
                if snapshot[table.name]:write.execute(table.insert(),snapshot[table.name])
        with engine.connect() as verify:
            assert verify.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
            assert not verify.exec_driver_sql('PRAGMA foreign_key_check').all()
            counts={}
            for table in Base.metadata.sorted_tables:
                stored=[dict(row) for row in verify.execute(select(table).order_by(table.c.id)).mappings()]
                if stored!=snapshot[table.name]:raise ValueError('Verification mismatch: '+table.name)
                counts[table.name]=len(stored)
            verify.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:engine.dispose()
    manifest={'copied_at_utc':utcnow().isoformat(),'source':'existing MySQL installation',
              'counts':counts,'all_columns_verified':True,'foreign_keys':'ok','integrity':'ok'}
    destination.with_suffix('.migration.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-env',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=ROOT/'data/education_audit.sqlite3')
    args=parser.parse_args()
    try:print(json.dumps(migrate(args.source_env,args.destination),ensure_ascii=False,indent=2))
    except Exception as error:
        print('Transfer failed: '+type(error).__name__+'. Source MySQL unchanged. Check connectivity and an empty destination.')
        raise SystemExit(1) from None
