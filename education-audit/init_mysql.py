"""Create the local database and app user using an explicitly entered admin password."""
import getpass
import os
import re
import pymysql
from audit.config import ROOT
from dotenv import load_dotenv

def main():
    load_dotenv(ROOT / '.env')
    name,user,password = os.getenv('DB_NAME','education_audit'),os.getenv('DB_USER','education_audit'),os.getenv('DB_PASSWORD','')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}',name) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',user):
        raise SystemExit('Use simple ASCII database and user names in .env.')
    if not password or password.startswith('CHANGE_ME'):
        raise SystemExit('Run python configure.py first.')
    admin=input('MySQL administrator [root]: ').strip() or 'root'
    admin_password=getpass.getpass('Administrator password (not stored): ')
    host=os.getenv('DB_HOST','127.0.0.1')
    if host not in ('127.0.0.1','localhost'):
        raise SystemExit('This helper initializes only local MySQL. For Docker use docker compose up --build.')
    with pymysql.connect(host=host,port=int(os.getenv('DB_PORT','3306')),user=admin,password=admin_password,charset='utf8mb4') as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            # Do not overwrite credentials for an existing account.
            cursor.execute('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s',(user,'localhost',password))
            cursor.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, REFERENCES ON `{name}`.* TO %s@%s',(user,'localhost'))
        connection.commit()
    print('Database and local app account prepared. Existing account passwords were not changed.')
    print('Next: python run.py --init-db')

if __name__=='__main__':
    main()
