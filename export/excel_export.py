"""Экспорт отчёта в Excel (openpyxl)."""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from core.report_builder import sorted_issues

SEVERITY_FILLS = {
    "критично": PatternFill(start_color="F4CCCC", end_color="F4CCCC", fill_type="solid"),
    "важно": PatternFill(start_color="FCE5CD", end_color="FCE5CD", fill_type="solid"),
    "незначительно": PatternFill(start_color="EFEFEF", end_color="EFEFEF", fill_type="solid"),
}


def export_excel(report, file_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Отчёт"

    ws["A1"] = "EduMonitor AI — отчёт о проверке сайта"
    ws["A1"].font = Font(bold=True, size=14)

    meta_rows = [
        ("Сайт", report.url),
        ("Тип организации", report.org_type),
        ("Дата проверки", report.checked_at),
        ("Оценка актуальности, %", report.score),
        ("Страниц проверено", report.pages_checked),
        ("Ссылок проверено", report.links_checked),
        ("Неработающих ссылок", report.broken_links),
        ("Разделов найдено", f"{report.sections_present} из {report.sections_total}"),
    ]
    for i, (label, value) in enumerate(meta_rows, start=3):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws.cell(row=i, column=2, value=value)

    headers = ["Критичность", "Тип вывода", "Проблема", "Описание", "Рекомендация"]
    start_row = 3 + len(meta_rows) + 2
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")

    for i, issue in enumerate(sorted_issues(report), start=1):
        row = start_row + i
        severity_cell = ws.cell(row=row, column=1, value=issue.severity)
        severity_cell.fill = SEVERITY_FILLS.get(issue.severity, PatternFill())
        ws.cell(row=row, column=2, value=issue.kind)
        ws.cell(row=row, column=3, value=issue.title)
        desc_cell = ws.cell(row=row, column=4, value=issue.description)
        desc_cell.alignment = Alignment(wrap_text=True, vertical="top")
        rec_cell = ws.cell(row=row, column=5, value=issue.recommendation)
        rec_cell.alignment = Alignment(wrap_text=True, vertical="top")

    widths = {"A": 16, "B": 14, "C": 35, "D": 55, "E": 45}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(file_path)
    return file_path
