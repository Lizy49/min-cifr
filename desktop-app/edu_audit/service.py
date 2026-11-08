"""Orchestration service for a single complete site audit."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os

from .crawler import Crawler
from .rules import check
from .ai import analyze as analyze_with_ai
from . import storage


class AuditService:
    def __init__(self, db_path=None, crawler_options=None):
        self.db_path = Path(db_path or storage.DEFAULT_DB)
        self.crawler_options = crawler_options or {
            "max_pages": int(os.getenv("CRAWL_MAX_PAGES", "40")),
            "max_documents": int(os.getenv("CRAWL_MAX_DOCUMENTS", "8")),
            "seconds": int(os.getenv("CRAWL_SECONDS", "90")),
            "timeout": int(os.getenv("CRAWL_TIMEOUT", "6")),
            "delay": float(os.getenv("CRAWL_DELAY", "0.15")),
        }

    def initialize(self):
        storage.initialize(self.db_path)
        storage.seed_organizations(self.db_path)

    def audit(self, organization, progress=None):
        started = datetime.now(timezone.utc).isoformat()
        crawler = Crawler(**self.crawler_options)
        try:
            crawl = crawler.crawl(organization["url"], progress=progress)
        except Exception:
            crawler.close()
            raise
        findings = check(organization["kind"], crawl)
        external_sources, external_errors = [], []
        for source_url in organization.get("fact_sources", [])[:5]:
            try:
                external_sources.append(crawler.fetch_external_source(source_url))
            except Exception as exc:
                external_errors.append(f"{source_url}: {str(exc)[:250]}")
        crawler.close()
        reference = storage.get_reference(organization["kind"], self.db_path)
        reference_run = None
        if reference and reference["id"] != organization["id"]:
            reference_run = storage.latest_completed_run(reference["id"], self.db_path)
        reference_context = None
        if reference and reference["id"] != organization["id"] and reference_run:
            reference_context = {
                "name": reference["name"], "url": reference["url"],
                "pages": reference_run.get("pages", []),
                "findings": reference_run.get("findings", []),
            }
        if progress:
            progress("Выполняется ИИ-анализ и сравнение с эталоном…")
        ai_result = analyze_with_ai(
            crawl["pages"], findings, external_sources,
            reference=reference_context, organization_kind=organization["kind"],
        )
        if reference and reference["id"] != organization["id"]:
            if reference_run is None:
                findings.append({
                    "rule": "reference.documents", "section": "Сравнение с эталоном",
                    "status": "unknown", "priority": "low",
                    "title": "Эталонный сайт ещё не проверялся",
                    "explanation": f"Выбрано учреждение «{reference['name']}» как эталон, но завершённого отчёта для него нет.",
                    "recommendation": "Сначала выполните проверку эталонного учреждения.", "evidence": [],
                })
            else:
                ref_files = {p.get("title", "").strip().casefold(): p for p in reference_run.get("pages", [])
                             if p.get("category") == "file" and p.get("status_code") == 200 and p.get("title")}
                current_files = {p.get("title", "").strip().casefold(): p for p in crawl.get("pages", [])
                                 if p.get("category") == "file" and p.get("status_code") == 200 and p.get("title")}
                candidates = [p for name, p in ref_files.items() if name not in current_files]
                if ref_files:
                    findings.append({
                        "rule": "reference.documents", "section": "Сравнение с эталоном",
                        "status": "unknown", "priority": "low",
                        "title": f"Кандидатов на сверку документов: {len(candidates)}",
                        "explanation": f"В эталоне «{reference['name']}» найдено файлов: {len(ref_files)}; на проверяемом сайте: {len(current_files)}. Сравнение основано на именах файлов и ограниченном обходе; это не перечень обязательных документов и не доказательство отсутствия документа.",
                        "recommendation": "Сверьте документы вручную: файлы могут иметь разные названия или находиться за пределами выборки.",
                        "evidence": [{"url": p.get("url", ""), "title": p.get("title", ""),
                                     "snippet": "Файл найден на эталонном сайте; сопоставьте его с документами проверяемого учреждения.",
                                     "status_code": p.get("status_code", 200)} for p in candidates[:10]],
                    })
        report = {
            "organization": {
                "id": organization["id"], "name": organization["name"],
                "kind": organization["kind"], "url": organization["url"],
            },
            "status": "completed" if any(p.get("status_code") == 200 and p.get("category") != "file"
                                        for p in crawl["pages"]) else "failed",
            "created_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "findings": findings,
            "pages": crawl["pages"],
            "meta": {
                "limited": crawl["limited"], "remaining": crawl["remaining"],
                "issues": crawl["issues"], "complete": crawl["complete"],
                "rules_version": "0.1.0",
                "ai": ai_result,
                "external_sources": [p.get("url", "") for p in external_sources],
                "external_errors": external_errors,
                "note": "Результат относится к загруженной выборке. Статус «Нужна ручная проверка» не является установленным нарушением.",
            },
        }
        storage.save_run(report, self.db_path)
        return report
