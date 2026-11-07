"""Главное окно приложения EduMonitor AI."""

from PyQt6.QtCore import QThread
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.report_builder import sorted_issues
from export.excel_export import export_excel
from export.pdf_export import export_pdf
from gui.styles import STYLESHEET
from gui.worker import CheckWorker
from storage import db

SEVERITY_COLORS = {
    "критично": QColor("#f4cccc"),
    "важно": QColor("#fce5cd"),
    "незначительно": QColor("#efefef"),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EduMonitor AI — проверка актуальности сайтов")
        self.resize(1120, 740)
        self.setStyleSheet(STYLESHEET)

        self.current_report = None
        self.thread = None
        self.worker = None

        self._build_ui()
        self._load_history()

    # ---------- построение интерфейса ----------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("EduMonitor AI")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Автоматическая проверка актуальности сайтов школ и детских садов")
        subtitle.setObjectName("AppSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        input_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Введите адрес сайта, например: school1-magadan.ru")
        self.org_combo = QComboBox()
        self.org_combo.addItems(["школа", "детский сад"])
        self.start_button = QPushButton("Начать проверку")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_check)
        input_row.addWidget(self.url_input, 4)
        input_row.addWidget(self.org_combo, 1)
        input_row.addWidget(self.start_button, 1)
        layout.addLayout(input_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        stats_row = QHBoxLayout()
        self.score_label = QLabel("Оценка актуальности: —")
        self.score_label.setObjectName("ScoreLabel")
        self.stats_label = QLabel("")
        stats_row.addWidget(self.score_label)
        stats_row.addWidget(self.stats_label)
        stats_row.addStretch()
        self.export_pdf_button = QPushButton("Сохранить PDF")
        self.export_excel_button = QPushButton("Сохранить Excel")
        self.export_pdf_button.clicked.connect(self._export_pdf)
        self.export_excel_button.clicked.connect(self._export_excel)
        self.export_pdf_button.setEnabled(False)
        self.export_excel_button.setEnabled(False)
        stats_row.addWidget(self.export_pdf_button)
        stats_row.addWidget(self.export_excel_button)
        layout.addLayout(stats_row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.issues_table = QTableWidget(0, 4)
        self.issues_table.setHorizontalHeaderLabels(["Критичность", "Тип вывода", "Проблема", "Рекомендация"])
        self.issues_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.issues_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.issues_table, "Найденные проблемы")

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["ID", "Сайт", "Тип", "Оценка, %", "Дата проверки"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.history_table, "История проверок")

    # ---------- запуск проверки ----------

    def _start_check(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "EduMonitor AI", "Введите адрес сайта.")
            return

        org_type = self.org_combo.currentText()
        self.start_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Запуск проверки…")
        self.issues_table.setRowCount(0)
        self.export_pdf_button.setEnabled(False)
        self.export_excel_button.setEnabled(False)

        self.thread = QThread()
        self.worker = CheckWorker(url, org_type)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.start()

    def _on_progress(self, stage, detail):
        text = stage if not detail else f"{stage} — {detail}"
        self.status_label.setText(text)

    def _on_finished(self, report):
        self.current_report = report
        self.progress_bar.setVisible(False)
        self.start_button.setEnabled(True)
        self.status_label.setText("Проверка завершена.")
        self.score_label.setText(f"Оценка актуальности: {report.score}%")
        self.stats_label.setText(
            f"   Страниц: {report.pages_checked} · Ссылок: {report.links_checked} "
            f"(неработающих: {report.broken_links}) · Разделов: {report.sections_present}/{report.sections_total}"
        )
        self._fill_issues_table(report)
        self.export_pdf_button.setEnabled(True)
        self.export_excel_button.setEnabled(True)

        db.save_report(report)
        self._load_history()

    def _on_error(self, message):
        self.progress_bar.setVisible(False)
        self.start_button.setEnabled(True)
        self.status_label.setText("Ошибка проверки.")
        QMessageBox.critical(self, "EduMonitor AI", f"Не удалось проверить сайт:\n{message}")

    # ---------- отображение данных ----------

    def _fill_issues_table(self, report):
        issues = sorted_issues(report)
        self.issues_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            severity_item = QTableWidgetItem(issue.severity)
            severity_item.setBackground(SEVERITY_COLORS.get(issue.severity, QColor("#ffffff")))
            self.issues_table.setItem(row, 0, severity_item)
            self.issues_table.setItem(row, 1, QTableWidgetItem(issue.kind))
            title_item = QTableWidgetItem(issue.title)
            title_item.setToolTip(issue.description)
            self.issues_table.setItem(row, 2, title_item)
            self.issues_table.setItem(row, 3, QTableWidgetItem(issue.recommendation))

    def _load_history(self):
        rows = db.load_history()
        self.history_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for col, value in enumerate(row):
                self.history_table.setItem(i, col, QTableWidgetItem(str(value)))

    # ---------- экспорт ----------

    def _export_pdf(self):
        if not self.current_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт как PDF", "edumonitor_report.pdf", "PDF (*.pdf)")
        if path:
            export_pdf(self.current_report, path)
            QMessageBox.information(self, "EduMonitor AI", f"Отчёт сохранён: {path}")

    def _export_excel(self):
        if not self.current_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт как Excel", "edumonitor_report.xlsx", "Excel (*.xlsx)")
        if path:
            export_excel(self.current_report, path)
            QMessageBox.information(self, "EduMonitor AI", f"Отчёт сохранён: {path}")
