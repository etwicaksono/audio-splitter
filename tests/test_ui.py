import csv
import io
import zipfile

import pytest

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QMessageBox, QInputDialog, QFileDialog

from src.models.sentence import Sentence, Word
from src.ui.main_window import MainWindow


def test_real_ui_import_player_and_editing(qtbot, tone_audio, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    window.table.error.disconnect()
    window.table.error.connect(errors.append)
    window.import_audio(tone_audio)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    assert window.metadata.duration == 4
    assert "48000 Hz" in window.file_label.text()
    assert window.process_button.isEnabled()
    words = [Word("One", 0.2, 0.5), Word("sentence.", 0.6, 1.0),
             Word("Two", 2.2, 2.5), Word("sentences.", 2.6, 3.0)]
    window.table.set_sentences([
        Sentence("One sentence.", 0.2, 1.0, words[:2]),
        Sentence("Two sentences.", 2.2, 3.0, words[2:]),
    ], 4)
    window.table.item(0, 1).setText("Edited sentence.")
    assert window.table.sentences[0].text == "Edited sentence."
    assert window.table.sentences[0].needs_review
    window.table.item(0, 2).setText("0.9")
    assert window.table.sentences[0].start == 0.2
    assert errors and "first word" in errors[-1]
    window.table.item(0, 2).setText("0.1")
    assert window.table.sentences[0].start == 0.1
    window.table.item(0, 7).setCheckState(Qt.Checked)
    assert not window.table.sentences[0].needs_review
    window.table.item(1, 6).setCheckState(Qt.Unchecked)
    assert not window.table.sentences[1].include
    window.table.item(1, 6).setCheckState(Qt.Checked)
    window.table.selectRow(0)
    qtbot.mouseClick(window.merge_button, Qt.LeftButton)
    assert len(window.table.sentences) == 1
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][1], True))
    qtbot.mouseClick(window.split_button, Qt.LeftButton)
    assert len(window.table.sentences) == 2
    qtbot.waitUntil(lambda: window.player.player.mediaStatus() in (
        QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia), timeout=15000)
    qtbot.mouseClick(window.table.cellWidget(0, 5), Qt.LeftButton)
    qtbot.waitUntil(lambda: window.player.player.playbackState() == QMediaPlayer.PlayingState,
                    timeout=5000)
    qtbot.waitUntil(lambda: window.player.player.playbackState() == QMediaPlayer.PausedState,
                    timeout=5000)
    assert window.player.player.position() >= 1000
    window.close()


@pytest.mark.parametrize("make_zip", [False, True], ids=["folder", "zip-only"])
def test_export_buttons_and_review_gate(qtbot, tone_audio, tmp_path, monkeypatch, make_zip):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    errors = []
    messages = []
    prompts = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args: messages.append(args[2]) or QMessageBox.Ok)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    def choose_name(parent, title, label, **kwargs):
        prompts.append((title, label, kwargs["text"]))
        return "gui-export", True

    monkeypatch.setattr(QInputDialog, "getText", choose_name)
    window.import_audio(tone_audio)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    window.table.set_sentences([
        Sentence("One sentence.", 0.1, 1.0, review_reasons=["Check."]),
        Sentence("Another sentence.", 2.0, 3.0),
    ], 4)
    button = window.zip_button if make_zip else window.export_button
    qtbot.mouseClick(button, Qt.LeftButton)
    assert errors and "Yellow" in errors[0]
    assert window.worker is None
    assert not prompts and not messages
    errors.clear()
    window.table.item(0, 7).setCheckState(Qt.Checked)
    qtbot.mouseClick(button, Qt.LeftButton)
    assert window.worker is not None
    assert not window.table.isEnabled() and not window.process_button.isEnabled()
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    folder = tmp_path / "gui-export"
    archive_path = tmp_path / "gui-export.zip"
    expected = {"001-one-sentence.mp3", "002-another-sentence.mp3",
                "transcript.txt", "transcript.csv"}
    if make_zip:
        assert archive_path.is_file() and not folder.exists()
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == expected
            rows = list(csv.DictReader(io.StringIO(archive.read("transcript.csv").decode("utf-8"))))
            assert [row["filename"] for row in rows] == [
                "001-one-sentence.mp3", "002-another-sentence.mp3"]
            assert [row["sentence"] for row in rows] == [
                "One sentence.", "Another sentence."]
            assert archive.read("transcript.txt").decode("utf-8").splitlines() == [
                "001-one-sentence.mp3\tOne sentence.",
                "002-another-sentence.mp3\tAnother sentence."]
        assert prompts == [("ZIP archive name",
                            "Create a ZIP archive named (without .zip):", "test_split")]
        assert str(archive_path) in messages[0] and "in ZIP archive:" in messages[0]
        assert "to:\n" not in messages[0] and "None" not in messages[0]
    else:
        assert folder.is_dir() and not archive_path.exists()
        assert {path.name for path in folder.iterdir()} == expected
        assert prompts == [("Output folder name", "Create a new folder named:", "test_split")]
        assert str(folder) in messages[0] and "ZIP archive" not in messages[0]
    assert not list(tmp_path.glob(".sentence-export-*"))
    assert not errors and messages == [window.status_label.text()]
    assert "Exported 2 MP3" in window.status_label.text()
    assert window.table.isEnabled()
    window.close()


def test_drop_and_error_recovery(qtbot, tone_audio, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.Ok)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tone_audio))])
    drag = QDragEnterEvent(window.rect().center(), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
    window.dragEnterEvent(drag)
    assert drag.isAccepted()
    drop = QDropEvent(window.rect().center(), Qt.CopyAction, mime,
                      Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(drop)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    assert window.metadata
    window.import_audio(tone_audio.with_suffix(".invalid"))
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    assert window.metadata is None
    assert not window.process_button.isEnabled()
    assert window.browse_button.isEnabled()
    assert "Choose an existing" in window.status_label.text()
    window.close()
