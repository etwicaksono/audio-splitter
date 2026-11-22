import logging
from pathlib import Path
import sys
import traceback

from platformdirs import user_log_dir
from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.main_window import MainWindow


LIGHT_THEME = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #20324d; }
QMainWindow, QWidget#central { background: #f7f9fc; }
QGroupBox { border: 1px solid #dbe3ef; border-radius: 8px; margin-top: 10px;
            padding: 10px; background: white; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLabel#title { font-size: 22pt; font-weight: 700; color: #183c73; }
QLabel#muted { color: #65758c; }
QPushButton { background: #edf2fa; border: 1px solid #c8d5e7;
              border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #e0eafb; }
QPushButton:disabled { color: #99a5b7; background: #f0f2f5; }
QPushButton#primary { background: #2f6bd1; color: white; border-color: #2f6bd1; }
QPushButton#primary:hover { background: #2458b1; }
QPushButton#primary:disabled { background: #a9bedf; }
QComboBox, QSpinBox, QLineEdit { background: white; border: 1px solid #ccd8e7;
                               border-radius: 4px; padding: 5px; }
QPlainTextEdit, QTableWidget { background: white; border: 1px solid #dbe3ef;
                            border-radius: 5px; selection-background-color: #dce9ff;
                            selection-color: #20324d; alternate-background-color: #f7faff; }
QHeaderView::section { background: #edf2fa; padding: 7px; border: 0;
                      border-bottom: 1px solid #dbe3ef; font-weight: 600; }
QProgressBar { border: 1px solid #dbe3ef; border-radius: 5px; text-align: center;
               background: white; min-height: 18px; }
QProgressBar::chunk { background: #3977db; border-radius: 4px; }
"""


def main() -> int:
    log_directory = Path(user_log_dir("AI Audio Sentence Splitter", "AudioSplitter"))
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_directory / "app.log", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    app = QApplication(sys.argv)
    app.setApplicationName("AI Audio Sentence Splitter")
    app.setStyle("Fusion")
    app.setStyleSheet(LIGHT_THEME)

    def exception_hook(kind, value, tb):
        logging.error("Unhandled error:\n%s", "".join(traceback.format_exception(kind, value, tb)))
        QMessageBox.critical(
            None, "Unexpected error",
            "Something went wrong. Your original audio is unchanged. Restart the app and try again.\n"
            f"Technical log: {log_directory / 'app.log'}")

    sys.excepthook = exception_hook
    window = MainWindow()
    window.show()
    if "--self-test" in sys.argv:
        from src.services.diagnostics import run_self_test
        return run_self_test(app, window, sys.argv[1:])
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        window.import_audio(Path(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
