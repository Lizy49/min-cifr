"""PyQt6 interface for Gosweb Audit."""
from __future__ import annotations

import html
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QInputDialog, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import storage
from .exporters import export_csv, export_html
from .service import AuditService
from .ai import public_state, test_connection

STATUS_LABELS = {
    "completed": "Завершена", "failed": "Не удалось проверить",
    "pass": "Пройдено", "warning": "Замечание", "error": "Проблема",
    "unknown": "Нужна ручная проверка",
}


class AIConnectionWorker(QThread):
    result_ready = pyqtSignal(dict)

    def run(self):
        self.result_ready.emit(test_connection())


class AuditWorker(QThread):
    progress = pyqtSignal(str)
    report_ready = pyqtSignal(dict)
    failed = pyqtSignal(str)
    all_done = pyqtSignal()

    def __init__(self, organizations, db_path, crawler_options=None):
        super().__init__()
        self.organizations = organizations
        self.db_path = db_path
        self.crawler_options = crawler_options or {}

    def run(self):
        service = AuditService(self.db_path, crawler_options=self.crawler_options)
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
        self.speed_preset = QComboBox()
        self.speed_preset.addItem("Быстро · 30 страниц", "fast")
        self.speed_preset.addItem("Баланс · 60 страниц", "balanced")
        self.speed_preset.addItem("Глубоко · 120 страниц", "deep")
        self.search.textChanged.connect(self.refresh_registry)
        filters.addWidget(self.kind_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(QLabel("Режим:"))
        filters.addWidget(self.speed_preset)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        self.set_reference_button = QPushButton("Назначить эталоном")
        self.set_reference_button.clicked.connect(self.set_reference)
        self.fact_sources_button = QPushButton("Источники фактчекинга")
        self.fact_sources_button.clicked.connect(self.edit_fact_sources)
        actions.addWidget(self.set_reference_button)
        actions.addWidget(self.fact_sources_button)
        self.check_selected_button = QPushButton("Проверить выбранное")
        self.check_all_button = QPushButton("Проверить весь список")
        self.check_selected_button.setObjectName("PrimaryButton")
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

        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        self.ai_state_label = QLabel(public_state()["label"])
        self.ai_check_button = QPushButton("Проверить подключение ИИ")
        self.ai_check_button.clicked.connect(self.check_ai_connection)
        self.ai_details = QTextBrowser()
        self.ai_details.setOpenExternalLinks(True)
        ai_layout.addWidget(self.ai_state_label)
        ai_layout.addWidget(self.ai_check_button)
        ai_layout.addWidget(self.ai_details, 1)
        self.tabs.addTab(ai_tab, "ИИ-анализ")

        self.findings.itemSelectionChanged.connect(self.show_finding_details)
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #0b1020; color: #e8edf7;
                font-family: "Inter", "Segoe UI", "Arial"; font-size: 13px;
            }
            QWidget#qt_scrollarea_viewport { background: #11182a; }
            QLabel#Title { color: #f7f9ff; font-size: 29px; font-weight: 800; letter-spacing: 2px; }
            QLabel#Subtitle { color: #8c9ab5; font-size: 13px; }
            QLabel#Counter {
                color: #8ce6d0; background: #102b32; border: 1px solid #1c5b59;
                border-radius: 12px; padding: 10px 16px; font-size: 14px; font-weight: 700;
            }
            QLabel#Status { color: #a9b7d0; padding: 8px 4px; }
            QLineEdit, QComboBox {
                background: #151e32; color: #edf2ff; border: 1px solid #2a3853;
                border-radius: 10px; padding: 11px 13px; min-height: 20px;
                selection-background-color: #526ee8;
            }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #7188ff; }
            QComboBox::drop-down { border: 0; width: 26px; }
            QComboBox QAbstractItemView {
                background: #151e32; color: #edf2ff; border: 1px solid #34425e;
                selection-background-color: #293b68; padding: 6px;
            }
            QPushButton {
                background: #1a2540; color: #dce6fb; border: 1px solid #344463;
                border-radius: 10px; padding: 11px 15px; font-weight: 650;
            }
            QPushButton:hover { background: #263656; border-color: #647ba9; }
            QPushButton:pressed { background: #17233c; }
            QPushButton:disabled { color: #64718a; background: #151c2c; border-color: #242f45; }
            QPushButton#PrimaryButton {
                color: #07131c; border: 0; font-weight: 800;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #73e5cb, stop:1 #6aa9ff);
            }
            QPushButton#PrimaryButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #9af4df, stop:1 #8bbcff);
            }
            QTabWidget::pane {
                background: #11182a; border: 1px solid #26344d; border-radius: 14px; top: -1px;
            }
            QTabBar::tab {
                background: #11182a; color: #8d9bb6; padding: 13px 19px;
                margin-right: 5px; border-top-left-radius: 10px; border-top-right-radius: 10px;
                font-weight: 650;
            }
            QTabBar::tab:hover { color: #dce8ff; background: #1a2740; }
            QTabBar::tab:selected {
                color: #a5f0df; background: #192740; border-bottom: 2px solid #72ddc5;
            }
            QTableWidget {
                background: #11182a; alternate-background-color: #151f33;
                color: #dce5f5; border: 0; gridline-color: #202c43;
                selection-background-color: #293d66; selection-color: #ffffff;
                outline: 0; padding: 8px;
            }
            QTableWidget::item { padding: 9px 7px; border-bottom: 1px solid #202b41; }
            QHeaderView::section {
                background: #19253b; color: #9fb0cc; padding: 12px 9px;
                border: 0; border-bottom: 1px solid #2a3a56; font-weight: 750;
            }
            QTableCornerButton::section { background: #19253b; border: 0; }
            QSplitter::handle { background: #26344d; height: 3px; }
            QTextBrowser {
                background: #10182a; color: #dce5f5; border: 1px solid #26344d;
                border-radius: 10px; padding: 14px; selection-background-color: #344d7c;
            }
            QTextBrowser a { color: #7edfcf; }
            QProgressBar {
                background: #18233a; border: 0; border-radius: 5px;
                min-height: 7px; max-height: 7px; text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6ee7c8, stop:1 #6d9fff);
            }
            QScrollBar:vertical { background: #10182a; width: 11px; margin: 2px; }
            QScrollBar::handle:vertical { background: #34435f; min-height: 28px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #536789; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
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

    def edit_fact_sources(self):
        selected = self._selected_organizations()
        if len(selected) != 1:
            QMessageBox.information(self, "Gosweb Audit", "Выберите ровно одно учреждение.")
            return
        current = "\n".join(selected[0].get("fact_sources", []))
        value, accepted = QInputDialog.getMultiLineText(
            self, "Источники фактчекинга",
            "Введите до пяти публичных URL независимых источников, по одному на строку. "
            "Эти страницы будут переданы ИИ для смысловой сверки.",
            current,
        )
        if not accepted:
            return
        try:
            storage.set_fact_sources(selected[0]["id"], value.splitlines(), self.db_path)
            self.refresh_registry()
            QMessageBox.information(self, "Gosweb Audit", "Внешние источники сохранены.")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка настройки источников", str(exc))

    def check_ai_connection(self):
        if getattr(self, "ai_worker", None) and self.ai_worker.isRunning():
            return
        self.ai_check_button.setEnabled(False)
        self.ai_check_button.setText("Проверяем соединение…")
        self.ai_worker = AIConnectionWorker()
        self.ai_worker.result_ready.connect(self._ai_connection_finished)
        self.ai_worker.start()

    def _ai_connection_finished(self, result):
        self.ai_state_label.setText(public_state()["label"])
        details = [
            f"<h3>{html.escape(result.get('message', ''))}</h3>",
            f"<p>Статус: {html.escape(result.get('status', 'unknown'))}</p>",
        ]
        for model in result.get("models", []):
            details.append(f"<p>{html.escape(str(model))}</p>")
        self.ai_details.setHtml("".join(details))
        self.ai_check_button.setEnabled(True)
        self.ai_check_button.setText("Проверить подключение ИИ")

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
        preset = self.speed_preset.currentData()
        options = {
            "fast": {"max_pages": 30, "max_documents": 6, "seconds": 75, "timeout": 6, "delay": 0.12},
            "balanced": {"max_pages": 60, "max_documents": 12, "seconds": 180, "timeout": 10, "delay": 0.25},
            "deep": {"max_pages": 120, "max_documents": 20, "seconds": 300, "timeout": 12, "delay": 0.35},
        }[preset]
        self.worker = AuditWorker(organizations, self.db_path, options)
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
        problems = sum(item.get("status") in ("warning", "error") for item in findings)
        unknown = sum(item.get("status") == "unknown" for item in findings)
        passed = sum(item.get("status") == "pass" for item in findings)
        self.details.setHtml(
            f"<h2>{html.escape(report['organization']['name'])}</h2>"
            f"<p><b>Сайт:</b> {html.escape(report['organization']['url'])}</p>"
            f"<p>Страниц загружено: {len(report.get('pages', []))}. "
            f"Ограниченный обход: {'да' if report.get('meta', {}).get('limited') else 'нет'}.</p>"
            f"<p><b>Итог:</b> найдено замечаний/проблем: {problems}; требуют ручной проверки: {unknown}; пройдено проверок: {passed}.</p>"
            "<p>Выберите строку замечания, чтобы увидеть основание и доказательства.</p>"
        )
        self.export_html_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)
        ai = report.get("meta", {}).get("ai", {})
        cards = [f"<h3>{html.escape(ai.get('message', 'ИИ-анализ не выполнялся.'))}</h3>"]
        cards.append(
            f"<p>Провайдер: {html.escape(str(ai.get('provider', '—')))} · "
            f"модель: {html.escape(str(ai.get('model', '—')))} · "
            f"статус: {html.escape(str(ai.get('status', '—')))}</p>"
        )
        for suggestion in ai.get("suggestions", []):
            cards.append(
                f"<section><h3>{html.escape(suggestion.get('title', ''))}</h3>"
                f"<p>{html.escape(suggestion.get('reason', ''))}</p>"
                f"<p><b>Рекомендация:</b> {html.escape(suggestion.get('recommendation', ''))}</p>"
            )
            for url in suggestion.get("urls", []):
                safe = html.escape(url, quote=True)
                cards.append(f'<p><a href="{safe}">{safe}</a></p>')
            cards.append("<p><i>Подсказка ИИ — гипотеза для ручной проверки.</i></p></section>")
        for error in report.get("meta", {}).get("external_errors", []):
            cards.append(f"<p>Ошибка внешнего источника: {html.escape(error)}</p>")
        self.ai_details.setHtml("".join(cards))
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
