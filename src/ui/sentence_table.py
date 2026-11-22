from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem,
)

from src.models.sentence import Sentence, merge_sentences, split_sentence


class SentenceTable(QTableWidget):
    preview_requested = Signal(int)
    updated = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(0, 9, parent)
        self.sentences: list[Sentence] = []
        self.audio_duration = 0.0
        self.setHorizontalHeaderLabels([
            "#", "Sentence text", "Start (s)", "End (s)", "Duration", "Preview",
            "Include", "Reviewed", "Boundary status",
        ])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.setMinimumHeight(230)
        self.itemChanged.connect(self.item_changed)

    def set_sentences(self, sentences: list[Sentence], duration: float):
        self.sentences = sentences
        self.audio_duration = duration
        self.refresh()
        self.updated.emit()

    def refresh(self):
        selected = self.currentRow()
        self.blockSignals(True)
        self.setRowCount(len(self.sentences))
        for row, sentence in enumerate(self.sentences):
            values = [str(row + 1), sentence.text, f"{sentence.start:.3f}",
                      f"{sentence.end:.3f}", f"{sentence.duration:.3f} s"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col not in (1, 2, 3):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(row, col, item)
            button = QPushButton("Preview")
            button.setAccessibleName(f"Preview sentence {row + 1}")
            button.clicked.connect(lambda checked=False, index=row: self.preview_requested.emit(index))
            self.setCellWidget(row, 5, button)
            for col, checked in ((6, sentence.include), (7, sentence.reviewed)):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.setItem(row, col, item)
            status = "Needs review" if sentence.needs_review else \
                ("Reviewed" if sentence.reviewed else "Automatic")
            item = QTableWidgetItem(status)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setToolTip("\n".join(sentence.review_reasons) or
                            "Punctuation boundary with word timestamps. Preview is still recommended.")
            if sentence.needs_review:
                item.setBackground(QColor("#fff0cf"))
            self.setItem(row, 8, item)
        self.blockSignals(False)
        if self.sentences:
            self.selectRow(min(max(selected, 0), len(self.sentences) - 1))

    def item_changed(self, item):
        row, col = item.row(), item.column()
        if not 0 <= row < len(self.sentences):
            return
        sentence = self.sentences[row]
        old = (sentence.text, sentence.start, sentence.end)
        try:
            if col == 6:
                sentence.include = item.checkState() == Qt.Checked
            elif col == 7:
                sentence.reviewed = item.checkState() == Qt.Checked
            elif col in (1, 2, 3):
                if col == 1:
                    sentence.text = item.text().strip()
                elif col == 2:
                    sentence.start = float(item.text())
                else:
                    sentence.end = float(item.text())
                sentence.validate(self.audio_duration)
                if row and sentence.start < self.sentences[row - 1].end - 0.001:
                    raise ValueError("Start overlaps the preceding sentence.")
                if row + 1 < len(self.sentences) and sentence.end > self.sentences[row + 1].start + 0.001:
                    raise ValueError("End overlaps the following sentence.")
                sentence.reviewed = False
                if "Manually edited. Preview to confirm." not in sentence.review_reasons:
                    sentence.review_reasons.append("Manually edited. Preview to confirm.")
        except ValueError as exc:
            sentence.text, sentence.start, sentence.end = old
            self.error.emit(str(exc))
        self.refresh()
        self.updated.emit()

    def merge_selected(self):
        row = self.currentRow()
        if row < 0 or row + 1 >= len(self.sentences):
            raise ValueError("Select a sentence with a following sentence to merge.")
        self.sentences[row:row + 2] = [
            merge_sentences(self.sentences[row], self.sentences[row + 1])]
        self.refresh()
        self.updated.emit()

    def split_selected(self, after_word: int):
        row = self.currentRow()
        if row < 0:
            raise ValueError("Select a sentence to split.")
        self.sentences[row:row + 1] = list(split_sentence(self.sentences[row], after_word))
        self.refresh()
        self.updated.emit()
