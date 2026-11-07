"""Save GigaChat credentials locally using hidden input; never print them."""
import getpass
from pathlib import Path
from dotenv import set_key

if __name__=='__main__':
    path=Path(__file__).resolve().parent/'.env'
    if not path.is_file():raise SystemExit('Run python configure.py first.')
    print('Paste Authorization key from GigaChat API. Input is hidden; Client Secret alone is not the key.')
    key=getpass.getpass('Authorization key: ').strip()
    if key.lower().startswith('basic '):key=key[6:].strip()
    if not key or any(c.isspace() for c in key):raise SystemExit('Empty key or whitespace; configuration not changed.')
    set_key(path,'AI_PROVIDER','gigachat')
    set_key(path,'GIGACHAT_CREDENTIALS',key)
    set_key(path,'GIGACHAT_MODEL','GigaChat')
    set_key(path,'GIGACHAT_SCOPE','GIGACHAT_API_PERS')
    try:path.chmod(0o600)
    except OSError:pass
    print('Saved locally. Restart the app, open /ai, then test the connection.')
