"""Generate a private .env without overwriting existing settings."""
from pathlib import Path
import secrets

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    target = root / '.env'
    if target.exists():
        print('.env already exists; left unchanged.')
    else:
        value = (root / '.env.example').read_text(encoding='utf-8')
        value = value.replace('CHANGE_ME_TOO', secrets.token_urlsafe(30))
        value = value.replace('CHANGE_ME_RANDOM_SECRET', secrets.token_hex(32))
        value = value.replace('CHANGE_ME', secrets.token_urlsafe(30))
        target.write_text(value, encoding='utf-8')
        try:
            target.chmod(0o600)
        except OSError:
            pass
        print('Created .env with random local passwords. Do not share it.')
