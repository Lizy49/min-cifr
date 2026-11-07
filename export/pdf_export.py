"""Экспорт отчёта в PDF (reportlab)."""

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.report_builder import sorted_issues

# reportlab по умолчанию не умеет отображать кириллицу встроенными шрифтами (Helvetica),
# поэтому пытаемся найти и зарегистрировать шрифт с поддержкой кириллицы в системе.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    os.path.join(os.path.dirname(__file__), "..", "fonts", "DejaVuSans.ttf"),
]


def _register_cyrillic_font():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("EduMonitorFont", path))
                return "EduMonitorFont"
            except Exception:
                continue
    # Шрифт с кириллицей не найден: текст в PDF может отображаться некорректно.
    # Поместите файл DejaVuSans.ttf в папку fonts/ рядом с проектом, чтобы исправить это.
    return "Helvetica"


FONT_NAME = _register_cyrillic_font()


def export_pdf(report, file_path):
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleRu", parent=styles["Title"], fontName=FONT_NAME, fontSize=18)
    normal_style = ParagraphStyle("NormalRu", parent=styles["Normal"], fontName=FONT_NAME, fontSize=10)
    heading_style = ParagraphStyle("HeadingRu", parent=styles["Heading2"], fontName=FONT_NAME, fontSize=13, spaceBefore=10)

    doc = SimpleDocTemplate(file_path, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    elements = []

    elements.append(Paragraph("EduMonitor AI — отчёт о проверке сайта", title_style))
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph(f"Сайт: {report.url}", normal_style))
    elements.append(Paragraph(f"Тип организации: {report.org_type}", normal_style))
    elements.append(Paragraph(f"Дата проверки: {report.checked_at}", normal_style))
    elements.append(Paragraph(f"<b>Оценка актуальности: {report.score}%</b>", normal_style))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(
        f"Проверено страниц: {report.pages_checked} · "
        f"проверено ссылок: {report.links_checked} (неработающих: {report.broken_links}) · "
        f"разделов найдено: {report.sections_present} из {report.sections_total}",
        normal_style,
    ))

    elements.append(Paragraph("Найденные проблемы", heading_style))

    if not report.issues:
        elements.append(Paragraph("Проблем не обнаружено.", normal_style))
    else:
        cell_style = ParagraphStyle("CellRu", parent=normal_style, fontSize=8, leading=10)
        table_data = [["Критичность", "Тип вывода", "Проблема", "Рекомендация"]]
        for issue in sorted_issues(report):
            table_data.append([
                Paragraph(issue.severity, cell_style),
                Paragraph(issue.kind, cell_style),
                Paragraph(issue.title, cell_style),
                Paragraph(issue.recommendation, cell_style),
            ])
        table = Table(table_data, colWidths=[25 * mm, 25 * mm, 55 * mm, 60 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        elements.append(table)

    doc.build(elements)
    return file_path
