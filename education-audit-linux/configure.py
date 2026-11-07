"""Create local settings automatically; no database credentials are required."""
from pathlib import Path
import secrets

DEFAULTS='''DATABASE_PATH=data/education_audit.sqlite3
HOST=127.0.0.1
PORT=8000
SECRET_KEY=CHANGE_ME_RANDOM_SECRET
MAX_PAGES=60
MAX_DOCUMENTS=12
CRAWL_SECONDS=180
REQUEST_TIMEOUT=12
REQUEST_DELAY=0.3
AI_PROVIDER=gigachat
GIGACHAT_CREDENTIALS=
GIGACHAT_MODEL=GigaChat
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_BASE_URL=https://api.giga.chat/v1
GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
GIGACHAT_CA_BUNDLE=
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=
'''

def ensure_config():
    root = Path(__file__).resolve().parent
    target = root / '.env'
    if target.exists():
        return target
    else:
        # Visible template supports browser uploads that omit dotfiles.
        example=root/'settings.example'
        value=example.read_text(encoding='utf-8') if example.exists() else DEFAULTS
        value = value.replace('CHANGE_ME_RANDOM_SECRET', secrets.token_hex(32))
        try:
            with target.open('x',encoding='utf-8') as file:file.write(value)
        except FileExistsError:
            return target
        try:
            target.chmod(0o600)
        except OSError:
            pass
        print('Created local settings. SQLite needs no username or password.')
        return target

if __name__=='__main__':
    ensure_config()
