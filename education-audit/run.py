import argparse
import logging
import os
from audit.config import database_url
from audit.models import connect, init_database
from audit.worker import seed, start_worker

def main():
    parser = argparse.ArgumentParser(description='Educational website audit — Windows / Linux')
    parser.add_argument('--init-db', action='store_true', help='Create missing tables and import institution list')
    parser.add_argument('--setup-only', action='store_true', help='Initialize database and exit')
    parser.add_argument('--no-worker', action='store_true', help='Run UI only (for a separately started worker)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    engine, factory = connect()
    try:
        if args.init_db or args.setup_only:
            init_database(engine)
            print(f'Imported organizations: {seed(factory)}')
        else:
            from sqlalchemy import text
            with engine.connect() as connection:
                connection.execute(text('SELECT 1 FROM organizations LIMIT 1'))
    except Exception as exc:
        print(f'Database unavailable ({type(exc).__name__}). Check .env, start MySQL, then run python run.py --init-db.')
        raise SystemExit(1) from None
    if args.setup_only:
        return
    from audit.web import create_app
    from waitress import serve
    app = create_app(factory, engine)
    stop = None if args.no_worker else start_worker(factory)
    host, port = os.getenv('HOST', '127.0.0.1'), int(os.getenv('PORT', '8000'))
    print(f'Open http://{host}:{port} (Ctrl+C to stop)')
    try:
        serve(app, host=host, port=port, threads=6, max_request_body_size=1_000_000)
    finally:
        if stop:
            stop.set()

if __name__ == '__main__':
    main()
