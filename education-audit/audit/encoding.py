"""Decode legacy Russian HTML and conservatively repair known mojibake."""
import re
from bs4 import BeautifulSoup

def russian_score(value):
    letters = len(re.findall('[А-Яа-яЁё]', value))
    words = sum(len(re.findall(word, value.lower())) for word in
        ('магадан', 'колледж', 'сведения', 'образован', 'документ', 'учебн', 'структур', 'новост', 'прием'))
    noise = len(re.findall('[\u2500-\u257f\u0080-\u009f]', value))
    return letters + words * 12 - noise * 8

def html_soup(body, encoding=None):
    try:
        # UTF-8 is authoritative when bytes are valid, even if HTTP declares Latin-1.
        return BeautifulSoup(body.decode('utf-8-sig'), 'html.parser'), 'utf-8'
    except UnicodeDecodeError:
        pass
    soup = BeautifulSoup(body, 'html.parser', from_encoding=encoding)
    chosen = soup.original_encoding or encoding or 'detected'
    try:
        candidate = body.decode('cp1251')
        if russian_score(candidate) > russian_score(str(soup)) + 3:
            return BeautifulSoup(candidate, 'html.parser'), 'windows-1251'
    except UnicodeDecodeError:
        pass
    return soup, chosen

def repair_legacy(value):
    if isinstance(value, dict):
        return {key:repair_legacy(item) for key,item in value.items()}
    if isinstance(value, list):
        return [repair_legacy(item) for item in value]
    if not isinstance(value, str):
        return value
    best = value
    if re.search('[À-ÿ]{3}', value):
        # HTML entities may introduce Unicode punctuation into an otherwise Latin-1 string.
        def repair_chunk(match):
            text=match[0]
            try:
                candidate=text.encode('latin1').decode('cp1251')
                return candidate if russian_score(candidate)>russian_score(text)+3 else text
            except UnicodeError:
                return text
        candidate=re.sub('[\x00-\xff]+',repair_chunk,value)
        if russian_score(candidate)>russian_score(best):
            best=candidate
    if re.search('[\u2500-\u257f]',value):
        for mistaken_encoding in ('cp866','cp1125'):
            # HTML entities can already be correct Unicode punctuation (e.g. »).
            # Preserve those characters while recovering the wrongly decoded spans.
            chunks,buffer=[],[]
            def flush():
                text=''.join(buffer)
                try:
                    chunks.append(text.encode(mistaken_encoding).decode('cp1251'))
                except UnicodeError:
                    chunks.append(text)
                buffer.clear()
            for character in value:
                try:
                    character.encode(mistaken_encoding)
                    buffer.append(character)
                except UnicodeError:
                    flush()
                    chunks.append(character)
            flush()
            candidate=''.join(chunks)
            if russian_score(candidate)>russian_score(best)+3:
                best=candidate
    return best
