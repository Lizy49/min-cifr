"""Orchestration service for a single complete site audit."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .crawler import Crawler
from .rules import check
from . import storage


class AuditService:
    def __init__(self, db_path=None, crawler_options=None):
        self.db_path = Path(db_path or storage.DEFAULT_DB)
        self.crawler_options = crawler_options or {}

    def initialize(self):
        storage.initialize(self.db_path)
        storage.seed_organizations(self.db_path)

    def audit(self, organization, progress=None):
        started = datetime.now(timezone.utc).isoformat()
        crawler = Crawler(**self.crawler_options)
        try:
            crawl = crawler.crawl(organization["url"], progress=progress)
        finally:
            crawler.close()
        findings = check(organization["kind"], crawl)
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
                "note": "Результат относится к загруженной выборке. Статус «Нужна ручная проверка» не является установленным нарушением.",
            },
        }
        storage.save_run(report, self.db_path)
        return report
