import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from edu_audit import storage


def test_main_window_constructs_with_a_fresh_database(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DEFAULT_DB", tmp_path / "gui.sqlite3")
    app = QApplication.instance() or QApplication([])
    from edu_audit.gui import MainWindow
    window = MainWindow()
    assert window.windowTitle().startswith("Gosweb Audit")
    assert window.registry.columnCount() == 5
    assert window.history.columnCount() == 6
    window.close()
    app.processEvents()
