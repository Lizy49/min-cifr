"""PyQt6 interface for Gosweb Audit."""
from __future__ import annotations

import html
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import storage
from .exporters import export_csv, export_html
from .service import AuditService

STATUS_LABELS = {
    "completed": "Завершена", "failed": "Не удалось проверить",
    "pass": "Пройдено", "warning": "Замечание", "error": "Проблема",
    "unknown": "Нужна ручная проверка",
}


class AuditWorker(QThread):
    progress = pyqtSignal(str)
    report_ready = pyqtSignal(dict)
    failed = pyqtSignal(str)
    all_done = pyqtSignal()

    def __init__(self, organizations, db_path):
        super().__init__()
        self.organizations = organizations
        self.db_path = db_path

    def run(self):
        service = AuditService(self.db_path)
        try:
            for organization in self.organizations:
                self.progress.emit("Проверяется: " + organization["name"])
                try:
                    report = service.audit(
                        organization,
                        progress=lambda message: self.progress.emit(organization["name"] + " — " + message),
                    )
                    self.report_ready.emit(report)
                except Exception as exc:
                    self.failed.emit(organization["name"] + ": " + str(exc))
        finally:
            self.all_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = AuditService()
        self.service.initialize()
        self.db_path = self.service.db_path
        self.worker = None
        self.current_report = None
        self.setWindowTitle("Gosweb Audit — аудит сайтов образования")
        self.resize(1420, 900)
        self.setMinimumSize(1100, 720)
        self._build_ui()
        self.refresh_registry()
        self.refresh_history()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("GOSWEB AUDIT")
        title.setObjectName("Title")
        subtitle = QLabel("Проверка актуальности и полноты сайтов образовательных организаций Магаданской области")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box, 1)
        self.counter = QLabel("")
        self.counter.setObjectName("Counter")
        heading.addWidget(self.counter)
        layout.addLayout(heading)

        filters = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("Все учреждения", "")
        self.kind_filter.addItem("Школы", "school")
        self.kind_filter.addItem("Детские сады", "garden")
        self.kind_filter.currentIndexChanged.connect(self.refresh_registry)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию учреждения")
        self.search.textChanged.connect(self.refresh_registry)
        filters.addWidget(self.kind_filter)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        self.set_reference_button = QPushButton("Назначить эталоном")
        self.set_reference_button.clicked.connect(self.set_reference)
        actions.addWidget(self.set_reference_button)
        self.check_selected_button = QPushButton("Проверить выбранное")
        self.check_all_button = QPushButton("Проверить весь список")
        self.export_html_button = QPushButton("Экспорт отчёта HTML")
        self.export_csv_button = QPushButton("Экспорт отчёта CSV")
        self.check_selected_button.clicked.connect(self.check_selected)
        self.check_all_button.clicked.connect(self.check_all)
        self.export_html_button.clicked.connect(lambda: self.export_report("html"))
        self.export_csv_button.clicked.connect(lambda: self.export_report("csv"))
        self.export_html_button.setEnabled(False)
        self.export_csv_button.setEnabled(False)
        for button in (self.check_selected_button, self.check_all_button, self.export_html_button, self.export_csv_button):
            actions.addWidget(button)
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status = QLabel("Готово к проверке.")
        self.status.setObjectName("Status")
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        registry_tab = QWidget()
        registry_layout = QVBoxLayout(registry_tab)
        self.registry = QTableWidget(0, 5)
        self.registry.setHorizontalHeaderLabels(["Учреждение", "Тип", "Сайт", "Эталон", "Последняя проверка"])
        self.registry.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.registry.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.registry.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.registry.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.registry.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.registry.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.registry.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.registry.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        registry_layout.addWidget(self.registry)
        self.tabs.addTab(registry_tab, "Реестр учреждений")

        report_tab = QWidget()
        report_layout = QVBoxLayout(report_tab)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.findings = QTableWidget(0, 5)
        self.findings.setHorizontalHeaderLabels(["Статус", "Приоритет", "Раздел", "Проблема", "Доказательств"])
        self.findings.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.findings.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.findings.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.findings.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.findings.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.findings.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.findings.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        splitter.addWidget(self.findings)
        splitter.addWidget(self.details)
        splitter.setSizes([480, 260])
        report_layout.addWidget(splitter)
        self.tabs.addTab(report_tab, "Результаты проверки")

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        self.history = QTableWidget(0, 6)
        self.history.setHorizontalHeaderLabels(["ID", "Учреждение", "Тип", "Статус", "Дата", "Страниц"])
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.itemSelectionChanged.connect(self.load_selected_history)
        history_layout.addWidget(self.history)
        self.tabs.addTab(history_tab, "История")

        self.findings.itemSelectionChanged.connect(self.show_finding_details)
        self.setStyleSheet("""
            QMainWindow,QWidget { background:#f4f6fa; color:#1f2937; font-family:Arial; font-size:13px; }
            QLabel#Title { font-size:27px; font-weight:800; color:#122f52; letter-spacing:1px; }
            QLabel#Subtitle { color:#617187; font-size:13px; }
            QLabel#Counter { font-size:16px; font-weight:700; color:#176a62; }
            QLabel#Status { color:#44546a; padding:5px; }
            QComboBox,QLineEdit { background:white; border:1px solid #cbd5e1; padding:9px; border-radius:7px; }
            QPushButton { background:#e6edf5; border:1px solid #cad5e2; padding:10px 14px; border-radius:7px; font-weight:600; }
            QPushButton:hover { background:#d9e6f3; }
            QPushButton:disabled { color:#98a2b3; }
            QPushButton:default { background:#145b87; color:white; }
            QTabWidget::pane { border:1px solid #d8e0e9; background:white; border-radius:8px; }
            QTabBar::tab { padding:10px 17px; background:#e8edf3; }
            QTabBar::tab:selected { background:white; color:#145b87; font-weight:700; }
            QTableWidget { background:white; border:0; gridline-color:#e8edf2; selection-background-color:#d9eaf6; }
            QHeaderView::section { background:#eaf0f6; padding:9px; border:0; font-weight:700; color:#34465d; }
            QTextBrowser { background:white; border:1px solid #e2e8f0; padding:10px; }
        """)

    def refresh_registry(self, *_):
        kind = self.kind_filter.currentData()
        organizations = storage.list_organizations(self.db_path, kind, self.search.text())
        history = storage.list_history(self.db_path, limit=500)
        latest = {}
        for item in history:
            latest.setdefault(item["url"], item)
        self.registry.setRowCount(len(organizations))
        for row, org in enumerate(organizations):
            values = [
                org["name"], "Школа" if org["kind"] == "school" else "Детский сад",
                org["url"], "Да" if org.get("is_reference") else "—",
                STATUS_LABELS.get(latest.get(org["url"], {}).get("status", ""), "Ещё не проверялся"),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, org)
                self.registry.setItem(row, col, cell)
        self.counter.setText(f"{len(organizations)} учреждений")

    def refresh_history(self):
        rows = storage.list_history(self.db_path)
        self.history.setRowCount(len(rows))
        for row, item in enumerate(rows):
            values = [item["id"], item["name"], "Школа" if item["kind"] == "school" else "Детский сад",
                      STATUS_LABELS.get(item["status"], item["status"]), item["created_at"], item["pages_count"]]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.history.setItem(row, col, cell)

    def _selected_organizations(self):
        rows = sorted({item.row() for item in self.registry.selectedItems()})
        return [self.registry.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in rows]

    def set_reference(self):
        selected = self._selected_organizations()
        if len(selected) != 1:
            QMessageBox.information(self, "Gosweb Audit", "Выберите ровно одно учреждение, которое станет эталоном своего типа.")
            return
        try:
            storage.set_reference(selected[0]["id"], self.db_path)
            self.refresh_registry()
            QMessageBox.information(self, "Gosweb Audit",
                "Эталон назначен. Сравнение использует только названия найденных файлов и не заменяет нормативный перечень документов.")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))

    def check_selected(self):
        selected = self._selected_organizations()
        if not selected:
            QMessageBox.information(self, "Gosweb Audit", "Выберите одно или несколько учреждений в реестре.")
            return
        self._start_checks(selected)

    def check_all(self):
        kind = self.kind_filter.currentData()
        organizations = storage.list_organizations(self.db_path, kind, self.search.text())
        if not organizations:
            return
        answer = QMessageBox.question(
            self, "Проверить список",
            f"Добавить в последовательную проверку {len(organizations)} учреждений? Это может занять продолжительное время.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_checks(organizations)

    def _start_checks(self, organizations):
        if self.worker and self.worker.isRunning():
            return
        self.check_selected_button.setEnabled(False)
        self.check_all_button.setEnabled(False)
        self.progress.show()
        self.status.setText(f"В очереди учреждений: {len(organizations)}")
        self.worker = AuditWorker(organizations, self.db_path)
        self.worker.progress.connect(self.status.setText)
        self.worker.report_ready.connect(self.display_report)
        self.worker.failed.connect(lambda message: self.status.setText("Ошибка: " + message))
        self.worker.all_done.connect(self._checks_finished)
        self.worker.start()

    def _checks_finished(self):
        self.progress.hide()
        self.check_selected_button.setEnabled(True)
        self.check_all_button.setEnabled(True)
        self.status.setText("Проверка очереди завершена.")
        self.refresh_registry()
        self.refresh_history()

    def display_report(self, report):
        self.current_report = report
        findings = report.get("findings", [])
        self.findings.setRowCount(len(findings))
        for row, item in enumerate(findings):
            values = [
                STATUS_LABELS.get(item["status"], item["status"]),
                {"high": "Высокий", "medium": "Средний", "low": "Низкий"}.get(item["priority"], item["priority"]),
                item["section"], item["title"], len(item.get("evidence", [])),
            ]
            for col, value in enumerate(values):
                self.findings.setItem(row, col, QTableWidgetItem(str(value)))
        self.details.setHtml(
            f"<h2>{html.escape(report['organization']['name'])}</h2>"
            f"<p><b>Сайт:</b> {html.escape(report['organization']['url'])}</p>"
            f"<p>Страниц загружено: {len(report.get('pages', []))}. "
            f"Ограниченный обход: {'да' if report.get('meta', {}).get('limited') else 'нет'}.</p>"
            "<p>Выберите строку замечания, чтобы увидеть основание и доказательства.</p>"
        )
        self.export_html_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def show_finding_details(self):
        if not self.current_report:
            return
        rows = sorted({item.row() for item in self.findings.selectedItems()})
        if not rows:
            return
        item = self.current_report["findings"][rows[0]]
        proof = []
        for evidence in item.get("evidence", []):
            proof.append(
                f'<div style="padding:10px;background:#f1f5f9;margin:8px 0">'
                f'<a href="{html.escape(evidence.get("url",""), quote=True)}">{html.escape(evidence.get("title") or evidence.get("url",""))}</a>'
                f'<p>{html.escape(evidence.get("snippet",""))}</p>'
                f'<small>HTTP {html.escape(str(evidence.get("status_code","—")))}</small></div>'
            )
        self.details.setHtml(
            f"<h2>{html.escape(item['title'])}</h2>"
            f"<p><b>Статус:</b> {html.escape(STATUS_LABELS.get(item['status'], item['status']))}</p>"
            f"<p><b>Почему:</b> {html.escape(item['explanation'])}</p>"
            f"<p><b>Рекомендация:</b> {html.escape(item['recommendation'])}</p>"
            + "".join(proof)
        )

    def load_selected_history(self):
        rows = sorted({item.row() for item in self.history.selectedItems()})
        if not rows:
            return
        run_id = self.history.item(rows[0], 0).data(Qt.ItemDataRole.UserRole)
        report = storage.load_run(run_id, self.db_path)
        if report:
            self.display_report(report)

    def export_report(self, kind):
        if not self.current_report:
            return
        extension = "html" if kind == "html" else "csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", f"gosweb-report-{self.current_report.get('id','')}.{extension}",
            "HTML (*.html)" if kind == "html" else "CSV (*.csv)",
        )
        if not path:
            return
        try:
            if kind == "html":
                export_html(self.current_report, path)
            else:
                export_csv(self.current_report, path)
            QMessageBox.information(self, "Gosweb Audit", f"Отчёт сохранён:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))


def run_gui():
    app = QApplication([])
    app.setApplicationName("Gosweb Audit")
    window = MainWindow()
    window.show()
    app.exec()
