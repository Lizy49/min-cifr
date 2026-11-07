"""QObject-воркер для выполнения проверки сайта в отдельном потоке (QThread)."""

from PyQt6.QtCore import QObject, pyqtSignal

from core.analyzer import run_check


class CheckWorker(QObject):
    progress = pyqtSignal(str, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, url, org_type):
        super().__init__()
        self.url = url
        self.org_type = org_type

    def run(self):
        try:
            report = run_check(
                self.url,
                self.org_type,
                progress_callback=lambda stage, detail="": self.progress.emit(stage, detail),
            )
            self.finished.emit(report)
        except Exception as exc:  # показываем пользователю понятную ошибку вместо падения приложения
            self.error.emit(str(exc))
