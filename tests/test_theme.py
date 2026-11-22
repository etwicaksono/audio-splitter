import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox, QPushButton

from app import LIGHT_THEME
from src.services.export_service import ExportResult
from src.ui.main_window import MainWindow


@pytest.fixture(params=["#ffffff", "#202124"], ids=["light-system", "dark-system"])
def themed_app(qapp, request):
    previous_style = qapp.style().objectName()
    previous_stylesheet = qapp.styleSheet()
    previous_palette = QPalette(qapp.palette())
    qapp.setStyle("Fusion")
    palette = QPalette(qapp.palette())
    palette.setColor(QPalette.Window, QColor(request.param))
    palette.setColor(QPalette.Button, QColor(request.param))
    qapp.setPalette(palette)
    qapp.setStyleSheet(LIGHT_THEME)
    yield qapp
    qapp.setStyleSheet("")
    qapp.setStyle(previous_style)
    qapp.setPalette(previous_palette)
    qapp.setStyleSheet(previous_stylesheet)


def contrast_ratio(foreground, background):
    def luminance(color):
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [value / 12.92 if value <= 0.04045 else
                  ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))

    darker, lighter = sorted((luminance(foreground), luminance(background)))
    return (lighter + 0.05) / (darker + 0.05)


def assert_readable_dialog(dialog):
    background = dialog.grab().toImage().pixelColor(8, 8)
    assert background == QColor("#f7f9fc")
    for label in dialog.findChildren(QLabel):
        if label.text():
            foreground = label.palette().color(QPalette.WindowText)
            assert contrast_ratio(foreground, background) >= 4.5
    for button in dialog.findChildren(QPushButton):
        foreground = button.palette().color(QPalette.ButtonText)
        background = button.palette().color(QPalette.Button)
        assert contrast_ratio(foreground, background) >= 4.5


@pytest.mark.parametrize("icon", [
    QMessageBox.Information, QMessageBox.Warning, QMessageBox.Critical, QMessageBox.Question,
])
def test_message_dialog_contrast(themed_app, qtbot, icon):
    dialog = QMessageBox(icon, "Message", "Exported 2 MP3 clips and both transcripts.",
                        QMessageBox.Ok)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert_readable_dialog(dialog)
    dialog.close()


def test_input_dialog_contrast(themed_app, qtbot):
    dialog = QInputDialog()
    qtbot.addWidget(dialog)
    dialog.setLabelText("Create a new folder named:")
    dialog.setTextValue("recording_split")
    dialog.show()
    qtbot.waitExposed(dialog)
    assert_readable_dialog(dialog)
    dialog.close()


def test_export_complete_message_contrast(themed_app, qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    result = ExportResult(tmp_path / "recording_split", 2, tmp_path / "recording_split.zip")
    messages = []

    def inspect_message():
        dialog = window.findChild(QMessageBox)
        try:
            assert dialog is not None
            assert dialog.windowTitle() == "Export complete"
            assert_readable_dialog(dialog)
            messages.append(dialog.text())
        finally:
            if dialog is not None:
                dialog.accept()

    QTimer.singleShot(0, inspect_message)
    window.exported(result)
    assert messages == [window.status_label.text()]
    assert "Exported 2 MP3" in messages[0]
    assert str(result.folder) in messages[0] and str(result.archive) in messages[0]
    window.close()
