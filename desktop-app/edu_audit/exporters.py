"""Evidence-preserving HTML and CSV exports."""
from __future__ import annotations

import csv
import html
from pathlib import Path
from datetime import datetime


def report_score(report):
    """Return a transparent index of automated checks that passed (0–100)."""
    findings = report.get("findings", [])
    if not findings:
        return None
    return round(100 * sum(item.get("status") == "pass" for item in findings) / len(findings))


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
    priority_order = {"high": 0, "medium": 1, "low": 2}
    status_order = {"error": 0, "warning": 1, "unknown": 2, "pass": 3}
    sorted_findings = sorted(report.get("findings", []), key=lambda item: (
        status_order.get(item.get("status"), 4),
        priority_order.get(item.get("priority"), 3),
    ))
    for item in sorted_findings:
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
    findings = report.get("findings", [])
    problems = sum(item.get("status") in ("warning", "error") for item in findings)
    unknown = sum(item.get("status") == "unknown" for item in findings)
    passed = sum(item.get("status") == "pass" for item in findings)
    score = report_score(report)
    score_label = f"{score} из 100" if score is not None else "недостаточно данных"
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>Отчёт — {esc(org["name"])}</title>
    <style>body{{font:15px/1.55 Arial,sans-serif;color:#202939;max-width:1000px;margin:32px auto;padding:0 22px}}
    h1{{font-size:26px}}h2{{font-size:19px}}article{{border-top:1px solid #d9e0e8;padding:20px 0;break-inside:avoid}}
    .meta,small{{color:#657184}}.evidence{{background:#f3f6f9;padding:12px;margin:10px 0;overflow-wrap:anywhere}}
    .summary{{background:#f2f6fb;border:1px solid #d8e2ef;border-radius:10px;padding:14px 18px;margin:18px 0}}
    .badge{{display:inline-block;background:#e6eef9;border-radius:999px;padding:4px 10px;font-weight:bold}}
    a{{color:#1756a9}}@media print{{body{{margin:12mm auto}}a{{color:#202939;text-decoration:none}}}}</style></head><body>
    <h1>Gosweb Audit — отчёт о проверке сайта</h1><p><b>Учреждение:</b> {esc(org["name"])}</p>
    <p><b>Сайт:</b> <a href="{esc(org["url"])}">{esc(org["url"])}</a></p>
    <p><b>Дата:</b> {esc(report.get("created_at"))}</p>
    <p><b>Проверено страниц:</b> {len(report.get("pages", []))}</p>
    <section class="summary"><p><b>Индекс пройденных автоматических проверок:</b> <span class="badge">{score_label}</span></p>
    <p>Расчёт: доля проверок со статусом «Пройдено» от всех проверок, включая требующие ручной сверки. Это показатель отчёта, а не экспертная оценка точности или качества сайта.</p>
    <p><b>Сначала проверьте:</b> {problems} замечаний/проблем; неопределённо — {unknown}; пройдено — {passed}.</p></section>
    <p><b>Ограниченный обход:</b> {"Да" if report.get("meta", {}).get("limited") else "Нет"}</p>
    <p>{esc(report.get("meta", {}).get("note"))}</p>{"".join(rows)}
    </body></html>"""
    destination.write_text(page, encoding="utf-8")
    return destination


def export_summary_csv(reports, destination):
    """Export a ministry-wide ranking by latest completed audit."""
    destination = Path(destination)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["Место", "Учреждение", "Тип", "Сайт", "Индекс пройденных проверок, %",
                         "Проблемы и замечания", "Нужна ручная проверка", "Пройдено", "Дата", "Проверено страниц"])
        ranked = sorted(reports, key=lambda report: (
            -(report_score(report) if report_score(report) is not None else -1),
            report["organization"]["name"].casefold(),
        ))
        for place, report in enumerate(ranked, start=1):
            findings = report.get("findings", [])
            values = [place, report["organization"]["name"],
                      "Школа" if report["organization"]["kind"] == "school" else "Детский сад",
                      report["organization"]["url"], report_score(report),
                      sum(item.get("status") in ("warning", "error") for item in findings),
                      sum(item.get("status") == "unknown" for item in findings),
                      sum(item.get("status") == "pass" for item in findings),
                      report.get("created_at", ""), len(report.get("pages", []))]
            writer.writerow(values)
    return destination


def export_summary_html(reports, destination):
    """Create a printable cross-organization ranking with transparent scoring."""
    destination = Path(destination)
    esc = lambda value: html.escape(str(value or ""), quote=True)
    ranked = sorted(reports, key=lambda report: (
        -(report_score(report) if report_score(report) is not None else -1),
        report["organization"]["name"].casefold(),
    ))
    rows = []
    for place, report in enumerate(ranked, start=1):
        findings = report.get("findings", [])
        org = report["organization"]
        rows.append(
            f'<tr><td>{place}</td><td>{esc(org["name"])}</td>'
            f'<td>{"Школа" if org["kind"] == "school" else "Детский сад"}</td>'
            f'<td><a href="{esc(org["url"])}">Открыть сайт</a></td>'
            f'<td><b>{report_score(report) if report_score(report) is not None else "—"}</b></td>'
            f'<td>{sum(item.get("status") in ("warning", "error") for item in findings)}</td>'
            f'<td>{sum(item.get("status") == "unknown" for item in findings)}</td>'
            f'<td>{esc(report.get("created_at", ""))}</td></tr>'
        )
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Сводный рейтинг — Gosweb Audit</title><style>body{{font:15px/1.5 Arial,sans-serif;color:#202939;max-width:1200px;margin:32px auto;padding:0 22px}}h1{{font-size:26px}}.note{{background:#f2f6fb;padding:14px;border-radius:9px}}table{{width:100%;border-collapse:collapse;margin-top:20px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #d9e0e8}}th{{background:#edf2f8}}tr{{break-inside:avoid}}a{{color:#1756a9}}@media print{{body{{margin:12mm auto}}}}</style></head><body>
    <h1>Gosweb Audit — сводный рейтинг учреждений</h1><p>Сформирован: {esc(datetime.now().astimezone().strftime("%d.%m.%Y %H:%M"))}. Включены последние завершённые проверки.</p>
    <p class="note"><b>Как читать индекс:</b> доля автоматических проверок со статусом «Пройдено» от общего числа сформированных проверок. Он помогает расставить порядок просмотра отчётов, но не подтверждает точность краулера и не является официальной оценкой качества сайта. Статус «Нужна ручная проверка» не означает нарушение; учитывайте дату, охват и ограничения обхода.</p>
    <table><thead><tr><th>Место</th><th>Учреждение</th><th>Тип</th><th>Сайт</th><th>Индекс, %</th><th>Замечания/проблемы</th><th>Ручная сверка</th><th>Последняя проверка</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
    </body></html>"""
    destination.write_text(page, encoding="utf-8")
    return destination
