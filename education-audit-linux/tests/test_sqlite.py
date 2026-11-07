import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,func
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from audit.models import connect,init_database,Organization,Run,Page
from audit.worker import enqueue
from audit.lock import InstanceLock

ROOT=Path(__file__).resolve().parent.parent

def test_persistent_unicode_database_and_foreign_keys(tmp_path):
    path=tmp_path/'Проверки сайтов.sqlite3'
    engine,factory=connect(URL.create('sqlite+pysqlite',database=str(path)))
    init_database(engine)
    with factory() as db:
        org=Organization(name='Колледж искусств',kind='college',url='https://x.example/')
        db.add(org);db.flush()
        run=Run(org_id=org.id,status='completed');db.add(run);db.flush()
        db.add(Page(run_id=run.id,url='https://x.example/news',title='Новости',text='Русский текст '*15000,
                    details={'дата':'2026-11-07','ссылки':['https://x.example/']}))
        db.commit()
    engine.dispose()
    engine,factory=connect(URL.create('sqlite+pysqlite',database=str(path)))
    with factory() as db:
        assert db.get(Organization,1).name=='Колледж искусств'
        assert db.get(Page,1).text=='Русский текст '*15000
        assert db.get(Page,1).details['дата']=='2026-11-07'
        db.add(Run(org_id=999,status='queued'))
        with pytest.raises(IntegrityError):db.commit()
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA journal_mode').scalar()=='wal'
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar()==1
    engine.dispose()

def test_concurrent_queue_is_deduplicated(tmp_path):
    engine,factory=connect(URL.create('sqlite+pysqlite',database=str(tmp_path/'queue.sqlite3')))
    init_database(engine)
    with factory() as db:
        db.add(Organization(name='Школа',kind='school',url='https://x.example/'));db.commit()
    def add():
        with factory() as db:return enqueue(db,[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts=list(pool.map(lambda _:add(),range(2)))
    assert sorted(counts)==[0,1]
    with factory() as db:assert db.scalar(select(func.count()).select_from(Run))==1
    engine.dispose()

def test_instance_lock_blocks_duplicate_workers(tmp_path):
    path=tmp_path/'app.lock';first,second=InstanceLock(path),InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(OSError):second.acquire()
    finally:first.release()
    second.acquire();second.release()

def test_startup_creates_settings_without_hidden_templates(tmp_path):
    project=tmp_path/'fresh-copy';project.mkdir()
    for name in ('run.py','configure.py'):
        shutil.copy2(ROOT/name,project/name)
    shutil.copytree(ROOT/'audit',project/'audit',ignore=shutil.ignore_patterns('__pycache__'))
    (project/'data').mkdir()
    shutil.copy2(ROOT/'data/organizations.json',project/'data/organizations.json')
    code="import runpy,sys; sys.path.insert(0,"+repr(str(project))+"); sys.modules['pymysql']=None; sys.argv=["+repr(str(project/'run.py'))+",'--setup-only']; runpy.run_path(sys.argv[0],run_name='__main__')"
    result=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,
        text=True,capture_output=True,timeout=30,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0,result.stdout+result.stderr
    assert (project/'.env').is_file()
    with sqlite3.connect(project/'data/education_audit.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM organizations').fetchone()[0]==87
    result=subprocess.run([sys.executable,str(project/'run.py'),'--setup-only'],cwd=tmp_path,
        text=True,capture_output=True,timeout=30,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0
    with sqlite3.connect(project/'data/education_audit.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM organizations').fetchone()[0]==87

def test_database_backup_is_consistent(tmp_path):
    source=tmp_path/'source.sqlite3';target=tmp_path/'backup.sqlite3'
    engine,factory=connect(URL.create('sqlite+pysqlite',database=str(source)))
    init_database(engine)
    with factory() as db:
        db.add(Organization(name='Техникум',kind='technical',url='https://x.example/'));db.commit()
    result=subprocess.run([sys.executable,str(ROOT/'tools/backup_database.py'),str(target)],
        env={**os.environ,'DATABASE_PATH':str(source),'PYTHONIOENCODING':'utf-8'},capture_output=True,text=True,timeout=30,encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT name FROM organizations').fetchone()[0]=='Техникум'
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    engine.dispose()

def test_database_path_is_relative_to_project(tmp_path,monkeypatch):
    from audit import config
    monkeypatch.setattr(config,'ROOT',tmp_path/'my-project')
    monkeypatch.setenv('DATABASE_PATH','data/site-audit.sqlite3')
    monkeypatch.chdir(tmp_path)
    assert config.database_path()==(tmp_path/'my-project/data/site-audit.sqlite3').resolve()
