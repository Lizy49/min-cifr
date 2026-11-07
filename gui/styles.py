"""QSS-стили для современного интерфейса EduMonitor AI."""

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #121826;
    color: #e8ecf4;
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
}

QLabel#AppTitle {
    font-size: 24px;
    font-weight: 700;
    color: #5fd6c4;
}

QLabel#AppSubtitle {
    font-size: 13px;
    color: #9aa5b8;
    margin-bottom: 6px;
}

QLabel#ScoreLabel {
    font-size: 16px;
    font-weight: 600;
    color: #5fd6c4;
}

QLineEdit, QComboBox {
    background-color: #1b2436;
    border: 1px solid #2d3850;
    border-radius: 8px;
    padding: 8px 10px;
    color: #e8ecf4;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #5fd6c4;
}

QPushButton {
    background-color: #2d3850;
    border: none;
    border-radius: 8px;
    padding: 9px 16px;
    color: #e8ecf4;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #394a6b;
}

QPushButton:disabled {
    background-color: #232c40;
    color: #6b7488;
}

QPushButton#PrimaryButton {
    background-color: #5fd6c4;
    color: #0c1420;
}

QPushButton#PrimaryButton:hover {
    background-color: #7fe3d4;
}

QProgressBar {
    border: 1px solid #2d3850;
    border-radius: 8px;
    text-align: center;
    background-color: #1b2436;
    height: 10px;
}

QProgressBar::chunk {
    background-color: #5fd6c4;
    border-radius: 8px;
}

QTabWidget::pane {
    border: 1px solid #2d3850;
    border-radius: 8px;
    background-color: #161e2e;
}

QTabBar::tab {
    background-color: #1b2436;
    color: #9aa5b8;
    padding: 8px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

QTabBar::tab:selected {
    background-color: #5fd6c4;
    color: #0c1420;
    font-weight: 600;
}

QTableWidget {
    background-color: #161e2e;
    gridline-color: #2d3850;
    border: none;
    selection-background-color: #2d3850;
}

QHeaderView::section {
    background-color: #1b2436;
    color: #9aa5b8;
    padding: 6px;
    border: none;
    font-weight: 600;
}
"""
