"""Evidence-preserving HTML and CSV exports."""
from __future__ import annotations

import csv
import html
from pathlib import Path


def export_csv(report, destination):
    destination = Path(destination)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["Учреждение", "Сайт", "Раздел", "Статус", "Приоритет",
                         "Проблема", "Основание", "Рекомендация", "Доказательства"])
        for item in report.get("findings", []):
            sources = "\n".join(e.get("url", "") for e in item.get("evidence", []))
            values = [
                report["organization"]["name"], report["organization"]["url"], item.get("section", ""),
                item.get("status", ""), item.get("priority", ""), item.get("title", ""),
                item.get("explanation", ""), item.get("recommendation", ""), sources,
            ]
            # Mitigate spreadsheet formula injection in text cells.
            writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                             for v in values])
    return destination


def export_html(report, destination):
    destination = Path(destination)
    org = report["organization"]
    esc = lambda value: html.escape(str(value or ""), quote=True)
    rows = []
    for item in report.get("findings", []):
        evidence = []
        for ev in item.get("evidence", []):
            evidence.append(
                f'<div class="evidence"><a href="{esc(ev.get("url"))}">{esc(ev.get("title") or ev.get("url"))}</a>'
                f'<p>{esc(ev.get("snippet"))}</p><small>HTTP {esc(ev.get("status_code"))}</small></div>'
            )
        rows.append(
            f'<article><div class="meta">{esc(item.get("section"))} · {esc(item.get("priority"))} приоритет</div>'
            f'<h2>{esc(item.get("title"))}</h2><p><b>Статус:</b> {esc(item.get("status"))}</p>'
            f'<p>{esc(item.get("explanation"))}</p><p><b>Рекомендация:</b> {esc(item.get("recommendation"))}</p>'
            f'{"".join(evidence)}</article>'
        )
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>Отчёт — {esc(org["name"])}</title>
    <style>body{{font:15px/1.55 Arial,sans-serif;color:#202939;max-width:1000px;margin:32px auto;padding:0 22px}}
    h1{{font-size:26px}}h2{{font-size:19px}}article{{border-top:1px solid #d9e0e8;padding:20px 0;break-inside:avoid}}
    .meta,small{{color:#657184}}.evidence{{background:#f3f6f9;padding:12px;margin:10px 0;overflow-wrap:anywhere}}
    a{{color:#1756a9}}@media print{{body{{margin:12mm auto}}}}</style></head><body>
    <h1>Gosweb Audit — отчёт о проверке сайта</h1><p><b>Учреждение:</b> {esc(org["name"])}</p>
    <p><b>Сайт:</b> <a href="{esc(org["url"])}">{esc(org["url"])}</a></p>
    <p><b>Дата:</b> {esc(report.get("created_at"))}</p>
    <p><b>Проверено страниц:</b> {len(report.get("pages", []))}</p>
    <p><b>Ограниченный обход:</b> {"Да" if report.get("meta", {}).get("limited") else "Нет"}</p>
    <p>{esc(report.get("meta", {}).get("note"))}</p>{"".join(rows)}
    </body></html>"""
    destination.write_text(page, encoding="utf-8")
    return destination
