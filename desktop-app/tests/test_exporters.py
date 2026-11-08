from edu_audit.exporters import export_html, export_summary_csv, export_summary_html, report_score


def sample_report(name="Школа", status="completed"):
    return {
        "organization": {"id": 1, "name": name, "kind": "school", "url": "https://school.example/"},
        "status": status,
        "created_at": "2026-11-08T01:00:00+11:00",
        "findings": [
            {"status": "pass", "priority": "low", "section": "Новости", "title": "Лента найдена",
             "explanation": "Даты распознаны.", "recommendation": "", "evidence": []},
            {"status": "unknown", "priority": "medium", "section": "Контакты", "title": "Сверить часы",
             "explanation": "Не удалось подтвердить.", "recommendation": "Проверьте часы приёма.", "evidence": []},
        ],
        "pages": [{"url": "https://school.example/"}],
        "meta": {"limited": True, "note": "Проверена выборка страниц."},
    }


def test_individual_report_explains_index_and_retains_manual_review_warning(tmp_path):
    path = tmp_path / "report.html"
    report = sample_report()
    assert report_score(report) == 50
    export_html(report, path)
    result = path.read_text(encoding="utf-8")
    assert "Индекс пройденных автоматических проверок" in result
    assert "а не экспертная оценка точности" in result
    assert result.index("unknown") < result.index("pass")


def test_summary_exports_rank_latest_reports_and_disclose_formula(tmp_path):
    reports = [sample_report("Школа А"), sample_report("Школа Б")]
    reports[1]["findings"] = [dict(reports[1]["findings"][0], status="pass")]

    html_path = tmp_path / "summary.html"
    csv_path = tmp_path / "summary.csv"
    export_summary_html(reports, html_path)
    export_summary_csv(reports, csv_path)

    html_text = html_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert html_text.index("Школа Б") < html_text.index("Школа А")
    assert "не является официальной оценкой" in html_text
    assert "Индекс пройденных проверок" in csv_text
