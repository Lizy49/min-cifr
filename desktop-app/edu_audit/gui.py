"""PyQt6 interface for Gosweb Audit."""
from __future__ import annotations

import html
import os
from pathlib import Path

from dotenv import load_dotenv, set_key, unset_key

from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QInputDialog, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import storage
from .exporters import export_csv, export_html, export_summary_csv, export_summary_html
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

    def __init__(self, organizations, db_path, crawler_options=None, specification=None):
        super().__init__()
        self.organizations = organizations
        self.db_path = db_path
        self.crawler_options = crawler_options or {}
        self.specification = specification

    def run(self):
        service = AuditService(
            self.db_path, crawler_options=self.crawler_options,
            specification=self.specification,
        )
        try:
            total = len(self.organizations)
            for index, organization in enumerate(self.organizations, start=1):
                if self.isInterruptionRequested():
                    break
                self.progress.emit(f"[{index}/{total}] Проверяется: {organization['name']}")
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


class AISettingsDialog(QDialog):
    """Local-only provider settings; API secrets are stored in desktop-app/.env."""

    PROVIDERS = {
        "DeepSeek": ("deepseek", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-flash"),
        "Gemini": ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-3.5-flash-lite"),
        "GigaChat": ("gigachat", "GIGACHAT_CREDENTIALS", "GIGACHAT_MODEL", "GigaChat"),
        "Ollama (локально)": ("ollama", "", "OLLAMA_MODEL", ""),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки ИИ")
        self.setMinimumWidth(440)
        self.env_path = Path(__file__).resolve().parents[1] / ".env"
        form = QFormLayout(self)
        self.provider = QComboBox()
        self.provider.addItems(self.PROVIDERS.keys())
        current = os.getenv("AI_PROVIDER", "ollama").strip().lower()
        for index, name in enumerate(self.PROVIDERS):
            if self.PROVIDERS[name][0] == current:
                self.provider.setCurrentIndex(index)
                break
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit()
        self.clear_key = QCheckBox("Удалить сохранённый ключ этого провайдера")
        self.hint = QLabel("Ключ хранится локально в desktop-app/.env и не отправляется в Git.")
        self.hint.setWordWrap(True)
        form.addRow("Провайдер", self.provider)
        form.addRow("API-ключ / credentials", self.key)
        form.addRow("Модель", self.model)
        form.addRow("", self.clear_key)
        form.addRow("", self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.provider.currentIndexChanged.connect(self._sync_fields)
        self._sync_fields()

    def _sync_fields(self):
        _, key_name, model_name, default_model = self.PROVIDERS[self.provider.currentText()]
        self.key.setEnabled(bool(key_name))
        self.key.clear()
        self.clear_key.setChecked(False)
        self.clear_key.setEnabled(bool(key_name))
        self.key.setPlaceholderText(
            "Введите новый ключ; сохранённый ключ не отображается" if key_name else "Для локальной Ollama ключ не нужен"
        )
        self.model.setText(os.getenv(model_name, default_model) if model_name else "")

    def save_settings(self):
        provider, key_name, model_name, default_model = self.PROVIDERS[self.provider.currentText()]
        set_key(str(self.env_path), "AI_PROVIDER", provider, quote_mode="always")
        if model_name:
            model = self.model.text().strip() or default_model
            set_key(str(self.env_path), model_name, model, quote_mode="always")
        if key_name and self.clear_key.isChecked():
            unset_key(str(self.env_path), key_name)
        elif key_name and self.key.text().strip():
            set_key(str(self.env_path), key_name, self.key.text().strip(), quote_mode="always")
        load_dotenv(self.env_path, override=True)
        os.environ["AI_PROVIDER"] = provider
        if model_name:
            os.environ[model_name] = self.model.text().strip() or default_model
        if key_name and self.clear_key.isChecked():
            os.environ.pop(key_name, None)
        elif key_name and self.key.text().strip():
            os.environ[key_name] = self.key.text().strip()
        try:
            self.env_path.chmod(0o600)
        except OSError:
            pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = AuditService()
        self.service.initialize()
        self.db_path = self.service.db_path
        self.worker = None
        self.current_report = None
        self.specification = None
        self.setWindowTitle("Gosweb Audit — аудит сайтов образования")
        self.resize(1180, 780)
        self.setMinimumSize(800, 600)
        self._build_ui()
        self.refresh_registry()
        self.refresh_history()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 20)
        sidebar_layout.setSpacing(10)

        brand = QLabel("◈  GOSWEB")
        brand.setObjectName("Brand")
        brand_subtitle = QLabel("AUDIT PLATFORM")
        brand_subtitle.setObjectName("BrandSubtitle")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(brand_subtitle)
        sidebar_layout.addSpacing(28)
        nav_caption = QLabel("РАБОЧЕЕ ПРОСТРАНСТВО")
        nav_caption.setObjectName("NavCaption")
        sidebar_layout.addWidget(nav_caption)

        content = QWidget()
        content.setObjectName("MainContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        sidebar.setParent(root)
        sidebar.hide()
        shell.addWidget(content, 1)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Аудит сайтов образования")
        title.setObjectName("Title")
        subtitle = QLabel("Школы и детские сады · Магаданская область")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box, 1)
        self.counter = QLabel("")
        self.counter.setObjectName("Counter")
        heading.addWidget(self.counter)
        layout.addLayout(heading)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_values = {}
        for key, caption in (
            ("organizations", "Учреждения"),
            ("checked", "Проверены"),
            ("runs", "Запуски"),
            ("ai", "Помощник ИИ"),
        ):
            card = QFrame()
            card.setObjectName("MetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 13, 16, 13)
            card_layout.setSpacing(5)
            value = QLabel("—")
            value.setObjectName("MetricValue")
            value.setWordWrap(True)
            label = QLabel(caption)
            label.setObjectName("MetricCaption")
            label.setWordWrap(True)
            card_layout.addWidget(value)
            card_layout.addWidget(label)
            metrics.addWidget(card, 1)
            self.metric_values[key] = value
        layout.addLayout(metrics)

        filters = QGridLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("Все учреждения", "")
        self.kind_filter.addItem("Школы", "school")
        self.kind_filter.addItem("Детские сады", "garden")
        self.kind_filter.currentIndexChanged.connect(self.refresh_registry)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти учреждение…")
        self.search.setClearButtonEnabled(True)
        self.speed_preset = QComboBox()
        self.speed_preset.addItem("Быстро · 30 страниц", "fast")
        self.speed_preset.addItem("Баланс · 60 страниц", "balanced")
        self.speed_preset.addItem("Глубоко · 120 страниц", "deep")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_registry)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        filters.addWidget(self.search, 0, 0, 1, 2)
        filters.addWidget(self.kind_filter, 0, 2)
        filters.addWidget(QLabel("Глубина проверки"), 1, 0)
        filters.addWidget(self.speed_preset, 1, 1, 1, 2)
        filters.setColumnStretch(1, 1)

        actions = QHBoxLayout()
        self.set_reference_button = QPushButton("Назначить эталоном")
        self.set_reference_button.clicked.connect(self.set_reference)
        self.fact_sources_button = QPushButton("Источники новостей")
        self.fact_sources_button.clicked.connect(self.edit_fact_sources)
        self.check_selected_button = QPushButton("Проверить выбранные")
        self.check_all_button = QPushButton("Проверить список")
        self.cancel_button = QPushButton("Остановить")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setToolTip("Остановить очередь после завершения текущего сайта")
        self.cancel_button.clicked.connect(self.cancel_checks)
        self.check_selected_button.setObjectName("PrimaryButton")
        self.export_html_button = QPushButton("Сохранить HTML")
        self.export_csv_button = QPushButton("Сохранить CSV")
        self.export_summary_button = QPushButton("Сводка по учреждениям")
        self.export_summary_button.setToolTip("Сохранить таблицу результатов последних завершённых проверок")
        self.export_summary_button.clicked.connect(self.export_summary)
        self.check_selected_button.clicked.connect(self.check_selected)
        self.check_all_button.clicked.connect(self.check_all)
        self.export_html_button.clicked.connect(lambda: self.export_report("html"))
        self.export_csv_button.clicked.connect(lambda: self.export_report("csv"))
        self.export_html_button.setEnabled(False)
        self.export_csv_button.setEnabled(False)
        for button in (self.check_selected_button, self.check_all_button, self.cancel_button):
            actions.addWidget(button)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status = QLabel("Готово к проверке.")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        registry_tab = QWidget()
        registry_layout = QVBoxLayout(registry_tab)
        registry_layout.addLayout(filters)
        registry_layout.addLayout(actions)
        registry_hint = QLabel("1. Найдите и выделите учреждения.  2. Запустите проверку.  3. Откройте результаты и сохраните отчёт.")
        registry_hint.setWordWrap(True)
        registry_layout.addWidget(registry_hint)
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
        self.registry.setAlternatingRowColors(True)
        self.registry.verticalHeader().setVisible(False)
        self.registry.verticalHeader().setDefaultSectionSize(42)
        registry_layout.addWidget(self.registry)
        reference_actions = QHBoxLayout()
        reference_actions.addWidget(self.set_reference_button)
        reference_actions.addWidget(self.fact_sources_button)
        reference_actions.addStretch()
        registry_layout.addLayout(reference_actions)
        self.tabs.addTab(registry_tab, "Реестр учреждений")

        report_tab = QWidget()
        report_layout = QVBoxLayout(report_tab)
        report_actions = QHBoxLayout()
        report_actions.addWidget(self.export_html_button)
        report_actions.addWidget(self.export_csv_button)
        report_actions.addStretch()
        report_layout.addLayout(report_actions)
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
        self.findings.setAlternatingRowColors(True)
        self.findings.verticalHeader().setVisible(False)
        self.findings.verticalHeader().setDefaultSectionSize(42)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        splitter.addWidget(self.findings)
        splitter.addWidget(self.details)
        splitter.setSizes([480, 260])
        report_layout.addWidget(splitter)
        self.tabs.addTab(report_tab, "Результаты проверки")

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_actions = QHBoxLayout()
        history_actions.addWidget(self.export_summary_button)
        history_actions.addStretch()
        history_layout.addLayout(history_actions)
        self.history = QTableWidget(0, 6)
        self.history.setHorizontalHeaderLabels(["ID", "Учреждение", "Тип", "Статус", "Дата", "Страниц"])
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.setAlternatingRowColors(True)
        self.history.verticalHeader().setVisible(False)
        self.history.verticalHeader().setDefaultSectionSize(42)
        self.history.itemSelectionChanged.connect(self.load_selected_history)
        history_layout.addWidget(self.history)
        self.tabs.addTab(history_tab, "История")

        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        self.ai_state_label = QLabel(public_state()["label"])
        self.ai_settings_button = QPushButton("Настроить ИИ")
        self.ai_settings_button.clicked.connect(self.configure_ai)
        self.ai_check_button = QPushButton("Проверить подключение")
        self.ai_check_button.setObjectName("PrimaryButton")
        self.ai_check_button.clicked.connect(self.check_ai_connection)
        self.ai_details = QTextBrowser()
        self.ai_details.setOpenExternalLinks(True)
        ai_layout.addWidget(self.ai_state_label)
        ai_actions = QHBoxLayout()
        ai_actions.addWidget(self.ai_settings_button)
        ai_actions.addWidget(self.ai_check_button)
        ai_layout.addLayout(ai_actions)
        ai_layout.addWidget(self.ai_details, 1)
        self.tabs.addTab(ai_tab, "ИИ-анализ")

        checklist_tab = QWidget()
        checklist_layout = QVBoxLayout(checklist_tab)
        checklist = QTextBrowser()
        checklist.setHtml(
            "<h2>Что проверяет программа</h2>"
            "<p>Требования кейса уже встроены. Загружать техническое задание не нужно.</p>"
            "<h3>Новости</h3><p>Интервалы до 14 дней; публикация в течение 24 часов после события "
            "при наличии точных дат. Если данных не хватает — нужна ручная проверка.</p>"
            "<h3>Школы</h3><p>Мероприятия текущего и следующего квартала, документы, расписание, "
            "сведения о школе, руководство, педагоги и контакты.</p>"
            "<h3>Детские сады</h3><p>Главная страница, новости, коллектив, образовательные программы, "
            "документы, раздел для педагогов и сотрудников, контакты и режим работы.</p>"
            "<h3>Эталон и внешние источники</h3><p>Выберите эталон для каждого типа учреждения и "
            "сначала проверьте его. Внешние ссылки для сверки новостей задаются в реестре. "
            "Подсказки ИИ требуют подтверждения человеком.</p>"
            "<h3>Отчёт</h3><p>Откройте замечание: показаны основание, ссылка, приоритет и рекомендация. "
            "HTML можно распечатать в PDF через браузер. Сводка в истории объединяет результаты учреждений.</p>"
            "<p><b>Ограничения:</b> обход выборочный; JavaScript и качество фотографий могут требовать "
            "ручного просмотра. Неопределённый результат не означает нарушение.</p>"
        )
        checklist_layout.addWidget(checklist)
        self.tabs.addTab(checklist_tab, "Правила проверки")
        self.tabs.tabBar().show()
        self.tabs.setTabText(0, "Учреждения")
        self.tabs.setTabText(1, "Результаты")
        self.tabs.setTabText(3, "Помощник ИИ")
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setUsesScrollButtons(True)

        self.nav_buttons = []
        for label, index in (
            ("▦   Реестр учреждений", 0),
            ("◉   Результаты проверки", 1),
            ("◷   История аудитов", 2),
            ("✧   ИИ-анализ", 3),
            ("▤   Правила проверки", 4),
        ):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, tab=index: self.tabs.setCurrentIndex(tab))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        self.tabs.currentChanged.connect(
            lambda index: [button.setChecked(i == index) for i, button in enumerate(self.nav_buttons)]
        )
        sidebar_layout.addStretch(1)
        sidebar_note = QLabel("ЛОКАЛЬНАЯ БАЗА\nSQLite · данные на этом ПК")
        sidebar_note.setObjectName("SidebarNote")
        sidebar_note.setWordWrap(True)
        sidebar_layout.addWidget(sidebar_note)

        self.findings.itemSelectionChanged.connect(self.show_finding_details)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#f4f7fb; color:#213047; font-family:"Segoe UI"; font-size:13px; }
            QLabel { background:transparent; }
            QLabel#Title { color:#152b49; font-size:25px; font-weight:700; }
            QLabel#Subtitle, QLabel#MetricCaption { color:#586b82; }
            QLabel#Counter { color:#146354; background:#e2f3ed; border-radius:8px; padding:8px 12px; }
            QLabel#Status { color:#52657c; padding:2px; }
            QFrame#MetricCard { background:white; border:1px solid #dce5ef; border-radius:10px; }
            QLabel#MetricValue { font-size:20px; font-weight:700; color:#183956; }
            QLineEdit, QComboBox { background:white; color:#213047; border:1px solid #bdcddd;
                border-radius:6px; padding:7px 10px; min-height:22px; selection-background-color:#d1e6fc; }
            QLineEdit:focus, QComboBox:focus { border:1px solid #237bba; }
            QComboBox::drop-down { width:25px; border:0; }
            QComboBox QAbstractItemView { background:white; color:#213047; selection-background-color:#dceefa; }
            QPushButton { background:white; border:1px solid #bacbdc; border-radius:6px;
                color:#254564; padding:8px 12px; min-height:20px; font-weight:600; }
            QPushButton:hover { background:#eaf2fb; border-color:#6693ba; }
            QPushButton:pressed { background:#d8e8f7; }
            QPushButton:disabled { background:#edf1f5; color:#7b8999; border-color:#d7e0e9; }
            QPushButton#PrimaryButton { background:#126b60; color:white; border:1px solid #126b60; }
            QPushButton#PrimaryButton:hover { background:#0c574e; }
            QTabWidget::pane { background:white; border:1px solid #dce5ef; border-radius:8px; }
            QTabBar::tab { background:#e9eff6; color:#465c76; padding:10px 14px;
                border-top-left-radius:7px; border-top-right-radius:7px; margin-right:3px; }
            QTabBar::tab:selected { background:white; color:#126b60; border-bottom:3px solid #126b60; }
            QTableWidget { background:white; alternate-background-color:#f5f8fc; color:#213047;
                border:1px solid #dce5ef; border-radius:5px; gridline-color:#e8eef5;
                selection-background-color:#d6eafa; selection-color:#173c59; }
            QTableWidget::item { padding:5px; }
            QHeaderView::section { background:#eaf0f7; color:#3e536d; padding:8px 6px;
                border:0; border-bottom:1px solid #d5e0ec; font-weight:600; }
            QTableCornerButton::section { background:#eaf0f7; border:0; }
            QTextBrowser { background:white; color:#213047; border:1px solid #dce5ef;
                border-radius:6px; padding:12px; }
            QSplitter::handle { background:#dce5ef; height:5px; }
            QProgressBar { border:0; background:#e0e9f2; min-height:6px; max-height:6px; }
            QProgressBar::chunk { background:#159080; }
            QScrollBar:vertical { background:#eef3f8; width:12px; }
            QScrollBar::handle:vertical { background:#afc1d3; min-height:28px; border-radius:5px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)


    def refresh_registry(self, *_):
        kind = self.kind_filter.currentData()
        organizations = storage.list_organizations(self.db_path, kind, self.search.text())
        history = storage.list_history(self.db_path, limit=500)
        latest = {}
        for item in history:
            latest.setdefault(item["url"], item)
        self.registry.setUpdatesEnabled(False)
        self.registry.setRowCount(len(organizations))
        for row, org in enumerate(organizations):
            values = [
                org["name"], "Школа" if org["kind"] == "school" else "Детский сад",
                org["url"], "Да" if org.get("is_reference") else "—",
                STATUS_LABELS.get(latest.get(org["url"], {}).get("status", ""), "Ещё не проверялся"),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, org)
                self.registry.setItem(row, col, cell)
        self.registry.setUpdatesEnabled(True)
        self.counter.setText(f"{len(organizations)} учреждений")
        all_organizations = storage.list_organizations(self.db_path)
        self.metric_values["organizations"].setText(str(len(all_organizations)))
        self.metric_values["checked"].setText(str(len({item["url"] for item in history})))
        self.metric_values["runs"].setText(str(len(history)))
        ai_state = public_state()
        self.metric_values["ai"].setText(
            ai_state["provider"].replace("gigachat", "GigaChat").upper()
            if ai_state["enabled"] else "НЕ НАСТРОЕН"
        )

    def refresh_history(self):
        rows = storage.list_history(self.db_path)
        self.export_summary_button.setEnabled(bool(storage.list_latest_reports(self.db_path)))
        self.history.setUpdatesEnabled(False)
        self.history.setRowCount(len(rows))
        for row, item in enumerate(rows):
            values = [item["id"], item["name"], "Школа" if item["kind"] == "school" else "Детский сад",
                      STATUS_LABELS.get(item["status"], item["status"]), item["created_at"], item["pages_count"]]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.history.setItem(row, col, cell)
        self.history.setUpdatesEnabled(True)

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
            self, "Источники новостей",
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

    def configure_ai(self):
        dialog = AISettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dialog.save_settings()
            state = public_state()
            self.ai_state_label.setText(state["label"])
            self.ai_details.setHtml(
                "<h3>Настройки сохранены на этом компьютере.</h3>"
                "<p>Ключ хранится в локальном .env. Проверьте соединение, чтобы убедиться, "
                "что выбранная модель доступна.</p>"
            )
            self.refresh_registry()
            self.status.setText("Настройки ИИ обновлены.")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Не удалось сохранить настройки ИИ", str(exc))

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
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self.cancel_requested = False
        self.progress.show()
        self.status.setText(f"В очереди учреждений: {len(organizations)}")
        preset = self.speed_preset.currentData()
        options = {
            "fast": {"max_pages": 30, "max_documents": 6, "seconds": 75, "timeout": 6, "delay": 0.12},
            "balanced": {"max_pages": 60, "max_documents": 12, "seconds": 180, "timeout": 10, "delay": 0.25},
            "deep": {"max_pages": 120, "max_documents": 20, "seconds": 300, "timeout": 12, "delay": 0.35},
        }[preset]
        self.worker = AuditWorker(organizations, self.db_path, options, self.specification)
        self.worker.progress.connect(self.status.setText)
        self.worker.report_ready.connect(self.display_report)
        self.worker.failed.connect(lambda message: self.status.setText("Ошибка: " + message))
        self.worker.all_done.connect(self._checks_finished)
        self.worker.start()

    def cancel_checks(self):
        if self.worker and self.worker.isRunning():
            self.cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.status.setText("Остановка запрошена — завершается текущий сайт…")
            self.worker.requestInterruption()

    def _checks_finished(self):
        self.progress.hide()
        self.check_selected_button.setEnabled(True)
        self.check_all_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.status.setText(
            "Очередь остановлена по запросу." if getattr(self, "cancel_requested", False)
            else "Проверка очереди завершена."
        )
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
                f'<div style="padding:12px;background:#f0f6fb;border:1px solid #ccdce9;border-radius:10px;margin:10px 0">'
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

    def export_summary(self):
        reports = storage.list_latest_reports(self.db_path)
        if not reports:
            QMessageBox.information(self, "Gosweb Audit", "Пока нет завершённых проверок для сводного рейтинга.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить сводку по учреждениям", "gosweb-summary.html",
            "HTML для просмотра и печати (*.html);;Таблица CSV (*.csv)",
        )
        if not path:
            return
        try:
            if "CSV" in selected_filter or path.lower().endswith(".csv"):
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                export_summary_csv(reports, path)
            else:
                if not path.lower().endswith(".html"):
                    path += ".html"
                export_summary_html(reports, path)
            QMessageBox.information(self, "Gosweb Audit", f"Сводка по учреждениям сохранён:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))


def run_gui():
    app = QApplication([])
    app.setApplicationName("Gosweb Audit")
    window = MainWindow()
    window.show()
    app.exec()
