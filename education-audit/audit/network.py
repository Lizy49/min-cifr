"""Bounded public HTTP reads; credentials, private networks and redirects are checked."""
import ipaddress
import socket
import time
import re
from urllib.parse import urlsplit, urlunsplit
import requests

class FetchError(Exception):
    pass

def normalize_url(value):
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Нужен публичный адрес http(s) без логина и пароля.')
    if parts.port not in (None, 80, 443):
        raise ValueError('Разрешены только стандартные порты HTTP и HTTPS.')
    host = parts.hostname.encode('idna').decode('ascii').lower()
    return urlunsplit((parts.scheme.lower(), host, parts.path or '/', parts.query, ''))

def validate_public(url):
    url = normalize_url(url)
    try:
        addresses = socket.getaddrinfo(urlsplit(url).hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError('Не удалось определить IP-адрес сайта.') from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise FetchError('Доступ к локальным и служебным адресам запрещён.')
    return url

class PublicClient:
    def __init__(self, timeout=12, delay=.3, max_bytes=3_000_000):
        self.timeout, self.delay, self.max_bytes = timeout, delay, max_bytes
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['User-Agent'] = 'EducationAudit/1.0 (educational content audit; robots respected)'
        self.last_request = 0.0

    def get(self, url):
        from urllib.parse import urljoin
        for _ in range(6):
            url = validate_public(url)
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                with self.session.get(url, timeout=(self.timeout, self.timeout),
                        stream=True, allow_redirects=False) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = response.headers.get('Location')
                        if not target:
                            raise FetchError('Перенаправление без адреса.')
                        url = urljoin(url, target)
                        continue
                    chunks, size = [], 0
                    deadline = time.monotonic() + self.timeout * 2
                    for chunk in response.iter_content(32768):
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise FetchError('Ответ превышает лимит 3 МБ.')
                        if time.monotonic() > deadline:
                            raise FetchError('Превышено время загрузки ответа.')
                        chunks.append(chunk)
                    declared = re.search(r'charset\s*=\s*["\']?([^;\s"\']+)', response.headers.get('Content-Type',''), re.I)
                    return {'url': url, 'status': response.status_code,
                            'content_type': response.headers.get('Content-Type', ''),
                            'body': b''.join(chunks), 'encoding': declared[1] if declared else None}
            except requests.RequestException as exc:
                raise FetchError(f'Ошибка соединения: {type(exc).__name__}.') from exc
        raise FetchError('Слишком много перенаправлений.')

    def close(self):
        self.session.close()
