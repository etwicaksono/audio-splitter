from copy import deepcopy

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from src.models.sentence import Sentence
from src.ui.main_window import MainWindow


@pytest.fixture
def bulk_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.table.set_sentences([
        Sentence(f"Sentence {row + 1}.", row * 2 + 0.1, row * 2 + 0.9,
                 review_reasons=["Confirm this boundary."])
        for row in range(4)
    ], 8)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.worker = None
    window.close()


def select_rows(table, rows):
    table.clearSelection()
    for row in rows:
        table.selectionModel().select(
            table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


@pytest.mark.parametrize("field", ["include", "reviewed"])
@pytest.mark.parametrize("scope", ["selected", "all"])
def test_bulk_checkbox_toggles_check_and_uncheck(bulk_window, qtbot, field, scope):
    window = bulk_window
    window.table.set_checked(field, False)
    select_rows(window.table, [0, 2])
    box = getattr(window, f"{field}_{scope}_box")
    target = [0, 2] if scope == "selected" else list(range(4))
    qtbot.mouseClick(box, Qt.LeftButton)
    assert box.checkState() == Qt.Checked
    assert [row for row, sentence in enumerate(window.table.sentences)
            if getattr(sentence, field)] == target
    assert window.table.selected_rows() == [0, 2]
    qtbot.mouseClick(box, Qt.LeftButton)
    assert box.checkState() == Qt.Unchecked
    assert not any(getattr(sentence, field) for sentence in window.table.sentences)
    if field == "include":
        assert all(sentence.needs_review for sentence in window.table.sentences)
    else:
        assert all(sentence.include for sentence in window.table.sentences)


def test_selection_toggle_does_not_change_checkboxes(bulk_window, qtbot):
    window = bulk_window
    before = deepcopy(window.table.sentences)
    qtbot.mouseClick(window.select_all_button, Qt.LeftButton)
    assert window.table.selected_rows() == [0, 1, 2, 3]
    assert window.select_all_button.text() == "Unselect all rows"
    assert window.selection_label.text() == "4 selected"
    qtbot.mouseClick(window.select_all_button, Qt.LeftButton)
    assert window.table.selected_rows() == []
    assert window.select_all_button.text() == "Select all rows"
    assert not window.include_selected_box.isEnabled()
    assert not window.reviewed_selected_box.isEnabled()
    assert window.table.sentences == before


def test_mixed_states_sync_without_marking_sentences(bulk_window, qtbot):
    window = bulk_window
    window.table.set_checked("include", False, [1])
    window.table.set_checked("reviewed", True, [0])
    before = deepcopy(window.table.sentences)
    select_rows(window.table, [0, 1])
    for box in (window.include_selected_box, window.reviewed_selected_box,
                window.include_all_box, window.reviewed_all_box):
        assert box.checkState() == Qt.PartiallyChecked
    assert window.table.sentences == before
    qtbot.mouseClick(window.reviewed_selected_box, Qt.LeftButton)
    assert window.reviewed_selected_box.checkState() == Qt.Checked
    assert [sentence.reviewed for sentence in window.table.sentences] == [True, True, False, False]
    assert "2 need review" in window.summary_label.text()


def test_bulk_and_edit_controls_disable_when_empty_busy_or_multi_selected(bulk_window):
    window = bulk_window
    controls = (window.select_all_button, window.include_selected_box, window.reviewed_selected_box,
                window.include_all_box, window.reviewed_all_box)
    select_rows(window.table, [0, 2])
    assert not window.merge_button.isEnabled() and not window.split_button.isEnabled()
    window.worker = object()
    window.update_controls()
    assert not any(control.isEnabled() for control in controls)
    before = window.table.selected_rows()
    window.toggle_row_selection()
    assert window.table.selected_rows() == before
    window.worker = None
    window.update_controls()
    assert all(control.isEnabled() for control in controls)
    select_rows(window.table, [0])
    assert window.merge_button.isEnabled() and window.split_button.isEnabled()
    select_rows(window.table, [3])
    assert not window.merge_button.isEnabled() and window.split_button.isEnabled()
    window.table.set_sentences([], 0)
    assert not any(control.isEnabled() for control in controls)


def test_bulk_review_and_include_drive_real_export(qtbot, tone_audio, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.Ok)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("bulk-export", True))
    window.import_audio(tone_audio)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    window.table.set_sentences([
        Sentence("First sentence.", 0.1, 1.0, review_reasons=["Check."]),
        Sentence("Second sentence.", 1.2, 2.0, review_reasons=["Check."]),
        Sentence("Third sentence.", 2.2, 3.0, review_reasons=["Check."]),
    ], 4)
    select_rows(window.table, [0, 2])
    qtbot.mouseClick(window.reviewed_selected_box, Qt.LeftButton)
    qtbot.mouseClick(window.export_button, Qt.LeftButton)
    assert errors and "Yellow" in errors[-1]
    assert window.worker is None
    select_rows(window.table, [1])
    qtbot.mouseClick(window.include_selected_box, Qt.LeftButton)
    assert not window.table.sentences[1].include and window.table.sentences[1].needs_review
    qtbot.mouseClick(window.export_button, Qt.LeftButton)
    assert window.worker is not None
    assert not window.include_all_box.isEnabled() and not window.reviewed_all_box.isEnabled()
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    destination = tmp_path / "bulk-export"
    assert (destination / "001.mp3").is_file() and (destination / "002.mp3").is_file()
    assert not (destination / "003.mp3").exists()
    transcript = (destination / "transcript.txt").read_text(encoding="utf-8")
    assert "First sentence." in transcript and "Third sentence." in transcript
    assert "Second sentence." not in transcript
    window.close()
