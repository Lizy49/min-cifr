"""Вспомогательные функции для представления отчёта (сортировка, текстовое summary)."""

SEVERITY_ORDER = {"критично": 0, "важно": 1, "незначительно": 2}


def sorted_issues(report):
    """Возвращает проблемы, отсортированные по критичности (сначала самые критичные)."""
    return sorted(report.issues, key=lambda i: SEVERITY_ORDER.get(i.severity, 3))


def summary_text(report):
    lines = [
        f"Сайт: {report.url}",
        f"Тип организации: {report.org_type}",
        f"Оценка актуальности: {report.score}%",
        f"Проверено страниц: {report.pages_checked}",
        f"Проверено ссылок: {report.links_checked} (неработающих: {report.broken_links})",
        f"Разделов найдено: {report.sections_present} из {report.sections_total}",
        f"Дата проверки: {report.checked_at}",
    ]
    return "\n".join(lines)
