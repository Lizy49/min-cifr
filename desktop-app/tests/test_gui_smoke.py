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
    assert set(window.metric_values) == {"organizations", "checked", "runs", "ai"}
    assert window.ai_settings_button.isEnabled()
    window.close()
    app.processEvents()



def test_ai_settings_dialog_saves_deepseek_key_only_to_local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = QApplication.instance() or QApplication([])
    from edu_audit.gui import AISettingsDialog
    from edu_audit.ai import public_state

    dialog = AISettingsDialog()
    dialog.env_path = tmp_path / ".env"
    dialog.provider.setCurrentText("DeepSeek")
    dialog.key.setText("test-secret-key")
    dialog.model.setText("deepseek-flash")
    dialog.save_settings()

    assert dialog.env_path.exists()
    contents = dialog.env_path.read_text(encoding="utf-8")
    assert "AI_PROVIDER='deepseek'" in contents
    assert "DEEPSEEK_API_KEY='test-secret-key'" in contents
    assert public_state()["provider"] == "deepseek"
    assert public_state()["enabled"] is True
    assert dialog.env_path.stat().st_mode & 0o777 == 0o600
    dialog.close()
    app.processEvents()
