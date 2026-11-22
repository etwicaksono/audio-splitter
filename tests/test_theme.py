import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QStyle, QStyleOptionViewItem,
)

from app import LIGHT_THEME
from src.models.sentence import Sentence
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


@pytest.mark.parametrize("make_zip", [False, True], ids=["folder", "zip-only"])
def test_export_complete_message_contrast(themed_app, qtbot, tmp_path, make_zip):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    result = ExportResult(None, 2, tmp_path / "recording_split.zip") if make_zip else \
        ExportResult(tmp_path / "recording_split", 2, None)
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
    if make_zip:
        assert "in ZIP archive:" in messages[0] and str(result.archive) in messages[0]
        assert "to:\n" not in messages[0] and "None" not in messages[0]
    else:
        assert str(result.folder) in messages[0] and "ZIP archive" not in messages[0]
    window.close()


@pytest.mark.parametrize("size", [(1400, 940), (1000, 720)], ids=["normal", "compact"])
def test_bulk_toolbar_contrast_and_compact_layout(themed_app, qtbot, size):
    window = MainWindow()
    qtbot.addWidget(window)
    window.table.set_sentences([Sentence("One.", 0, 1), Sentence("Two.", 2, 3)], 4)
    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    scroll = window.centralWidget()
    assert isinstance(scroll, QScrollArea)
    panel = window.table.parentWidget()
    rendered = panel.grab().toImage()
    assert rendered.pixelColor(0, 0) == QColor("#f7f9fc")
    for widget in (window.selection_label, window.summary_label, window.include_selected_box,
                   window.reviewed_selected_box, window.include_all_box, window.reviewed_all_box):
        corner = widget.mapTo(panel, widget.rect().bottomRight())
        background = rendered.pixelColor(corner)
        assert background == QColor("#f7f9fc")
        foreground = widget.palette().color(QPalette.WindowText)
        assert contrast_ratio(foreground, background) >= 4.5
    assert window.table.parentWidget().rect().contains(window.table.geometry())
    if size == (1000, 720):
        assert scroll.verticalScrollBar().maximum() > 0
    for widget in (window.select_all_button, window.reviewed_all_box, window.export_button):
        scroll.ensureWidgetVisible(widget)
        center = widget.mapTo(scroll.viewport(), widget.rect().center())
        assert scroll.viewport().rect().contains(center)
    window.close()


@pytest.mark.parametrize("field,column", [("include", 6), ("reviewed", 7)])
def test_shift_checkbox_updates_themed_toolbar(themed_app, qtbot, field, column):
    window = MainWindow()
    qtbot.addWidget(window)
    window.table.set_sentences([
        Sentence(str(row), row * 2, row * 2 + 1, review_reasons=["Check."])
        for row in range(3)
    ], 6)
    window.show()
    qtbot.waitExposed(window)
    table = window.table
    window.centralWidget().ensureWidgetVisible(table)
    for row, modifiers in ((0, Qt.NoModifier), (2, Qt.ShiftModifier), (2, Qt.ShiftModifier)):
        index = table.model().index(row, column)
        table.scrollTo(index)
        option = QStyleOptionViewItem()
        option.rect = table.visualRect(index)
        table.itemDelegateForColumn(column).initStyleOption(option, index)
        indicator = table.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, table)
        qtbot.mouseClick(table.viewport(), Qt.LeftButton, modifiers, indicator.center())
        if modifiers & Qt.ShiftModifier:
            qtbot.keyRelease(table.viewport(), Qt.Key_Shift)
            expected = getattr(table.sentences[row], field)
            assert all(getattr(sentence, field) == expected for sentence in table.sentences)
            assert getattr(window, f"{field}_all_box").checkState() == (
                Qt.Checked if expected else Qt.Unchecked)
    if field == "reviewed":
        assert "3 need review" in window.summary_label.text()
    else:
        assert "3 included" in window.summary_label.text()
    window.close()
