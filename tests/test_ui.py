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


def test_export_mp3_button_and_review_gate(qtbot, tone_audio, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.Ok)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("gui-export", True))
    window.import_audio(tone_audio)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    window.table.set_sentences([
        Sentence("One sentence.", 0.1, 1.0, review_reasons=["Check."]),
        Sentence("Another sentence.", 2.0, 3.0),
    ], 4)
    qtbot.mouseClick(window.export_button, Qt.LeftButton)
    assert errors and "Yellow" in errors[0]
    assert window.worker is None
    window.table.item(0, 7).setCheckState(Qt.Checked)
    qtbot.mouseClick(window.export_button, Qt.LeftButton)
    assert window.worker is not None
    assert not window.table.isEnabled() and not window.process_button.isEnabled()
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    assert (tmp_path / "gui-export" / "002.mp3").is_file()
    assert (tmp_path / "gui-export" / "transcript.txt").is_file()
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
