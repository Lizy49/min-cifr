"""Extract institution tables from the hackathon DOCX using only the standard library."""
import argparse
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

def extract(path):
    ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    def text(node):
        return ' '.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in node.findall('.//w:p',ns)).strip()
    kind, items, known = None, [], set()
    body = root.find('w:body',ns)
    for element in body:
        if element.tag.endswith('}p'):
            value = ''.join(t.text or '' for t in element.findall('.//w:t',ns)).strip().lower()
            if value == 'школы:': kind='school'
            if value == 'детские сады:': kind='garden'
        elif element.tag.endswith('}tbl') and kind:
            for row in element.findall('w:tr',ns):
                cells = [text(cell) for cell in row.findall('w:tc',ns)]
                if len(cells)<2: continue
                match = re.search(r'(?:https?://)?[a-zа-я0-9.-]+\.gosweb\.gosuslugi\.ru', ' '.join(cells), re.I)
                if not match: continue
                url = 'https://' + re.sub(r'^https?://','',match[0]).lower() + '/'
                if url in known: continue
                known.add(url)
                items.append({'name':cells[0], 'kind':kind, 'url':url, 'source':'Описание проблемы.docx — перечень организаторов хакатона'})
    return items

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('output')
    args=parser.parse_args()
    records=extract(args.source)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Extracted {len(records)} organizations')
