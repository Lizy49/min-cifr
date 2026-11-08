"""Extract auditable requirements from PDF, DOCX and TXT specifications.

Only explicit numeric thresholds are structured automatically. Other statements remain
manual-review requirements; extraction never turns a vague sentence into a violation.
"""
from __future__ import annotations

import re
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".txt"}

PATTERNS = (
    ("news_frequency", re.compile(r"(?:не реже|не менее|каждые|интервал.{0,30}(?:не более|до)).{0,45}?(\d+)\s*(?:дн|дней|дня)", re.I), "max_interval_days"),
    ("event_publication_delay", re.compile(r"(?:в течение|не позднее|не более).{0,45}?(\d+)\s*(?:час|часа|часов)", re.I), "max_delay_hours"),
    ("event_horizon", re.compile(r"(?:текущего и следующего|текущий и следующий)\s+квартал", re.I), "quarters_ahead"),
)

CATEGORY_KEYWORDS = {
    "news": ("новост", "публикац", "информац"),
    "events": ("мероприят", "событи", "календар", "квартал"),
    "documents": ("документ", "устав", "лицензи", "положени", "приказ"),
    "schedule": ("расписан", "режим работ", "график"),
    "staff": ("педагог", "сотрудник", "коллектив", "руководств", "работник"),
    "contacts": ("контакт", "телефон", "почт", "адрес"),
    "programs": ("образовательн", "программ"),
    "visual": ("изображен", "фотограф", "баннер", "логотип", "дизайн", "оформлен"),
    "comparison": ("эталон", "сравнен", "сопостав"),
}


def _extract(path: Path) -> list[tuple[int | None, str]]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return [(None, line) for line in path.read_text(encoding="utf-8-sig").splitlines()]
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    if suffix == ".docx":
        from docx import Document
        document = Document(str(path))
        blocks = [(None, paragraph.text) for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                blocks.append((None, " | ".join(cell.text for cell in row.cells)))
        return blocks
    raise ValueError("Поддерживаются документы PDF, DOCX и TXT.")


def _category(text: str) -> str:
    lowered = text.casefold()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            return category
    return "general"


def _structure(text: str) -> dict:
    for code, pattern, field in PATTERNS:
        match = pattern.search(text)
        if match:
            value = int(match.group(1)) if match.lastindex else 2
            return {"kind": code, "threshold": {field: value}, "review": True}
    if re.search(r"обязательн|должен|должна|необходимо|требуется|должны", text, re.I):
        return {"kind": "presence_or_content", "threshold": {}, "review": True}
    return {"kind": "manual", "threshold": {}, "review": True}


def parse_text(text: str, source_name: str = "Техническое задание") -> dict:
    requirements = []
    seen = set()
    for line in text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip(" \t•▪◦-*–—\r")
        if len(normalized) < 18:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        structured = _structure(normalized)
        requirements.append({
            "id": f"REQ-{len(requirements) + 1:03d}",
            "text": normalized[:1200],
            "category": _category(normalized),
            "verification": structured["kind"],
            "threshold": structured["threshold"],
            "review_required": True,
            "source": source_name,
        })
    return {
        "source_name": source_name,
        "requirements": requirements,
        "total": len(requirements),
        "structured": sum(item["verification"] not in ("manual",) for item in requirements),
        "manual": sum(item["verification"] == "manual" for item in requirements),
        "note": "Автоматическое извлечение — черновик. Подтвердите каждое требование перед использованием как критерия аудита.",
    }


def parse_specification(file_path: str | Path) -> dict:
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Поддерживаются документы PDF, DOCX и TXT.")
    blocks = _extract(path)
    text_parts = []
    for page, content in blocks:
        if content.strip():
            text_parts.append(content)
    result = parse_text("\n".join(text_parts), path.name)
    result["pages_or_blocks"] = len(blocks)
    return result
