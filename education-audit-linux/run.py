import argparse
import logging
import os

def main():
    parser = argparse.ArgumentParser(description='Educational website audit — SQLite, no MySQL server')
    parser.add_argument('--init-db', action='store_true', help='Create missing tables and import institution list')
    parser.add_argument('--setup-only', action='store_true', help='Initialize database and exit')
    parser.add_argument('--no-worker', action='store_true', help='Run UI only (for a separately started worker)')
    parser.add_argument('--open-browser',action='store_true',help='Open local web interface after startup')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    from configure import ensure_config
    ensure_config()
    from audit.config import database_path
    from audit.models import connect, init_database
    from audit.worker import seed, start_worker
    engine, factory = connect()
    try:
        init_database(engine)
        count=seed(factory)
        print(f'SQLite database: {database_path()}',flush=True)
        print(f'New organizations imported: {count}',flush=True)
    except Exception as exc:
        print(f'SQLite unavailable ({type(exc).__name__}): {exc}. Check write access to the data folder.')
        raise SystemExit(1) from None
    if args.setup_only:
        return
    from audit.lock import InstanceLock
    lock=InstanceLock(database_path().with_suffix('.lock'))
    try:
        lock.acquire()
    except OSError:
        print('This database is already used by another application instance. Open its browser window instead.')
        return
    from audit.web import create_app
    from waitress import serve
    app = create_app(factory, engine)
    stop = None if args.no_worker else start_worker(factory)
    host, port = os.getenv('HOST', '127.0.0.1'), int(os.getenv('PORT', '8000'))
    address=f'http://127.0.0.1:{port}'
    print(f'Open {address} (Ctrl+C to stop)',flush=True)
    if args.open_browser:
        import threading,webbrowser
        threading.Timer(1.5,lambda:webbrowser.open(address)).start()
    try:
        serve(app, host=host, port=port, threads=6, max_request_body_size=1_000_000)
    finally:
        if stop:
            stop.set()
        lock.release()

if __name__ == '__main__':
    main()
