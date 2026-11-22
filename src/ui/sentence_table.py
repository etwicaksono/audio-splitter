from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt, Signal
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
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.setMinimumHeight(230)
        self.itemChanged.connect(self.item_changed)

    def set_sentences(self, sentences: list[Sentence], duration: float):
        self.clearSelection()
        self.sentences = sentences
        self.audio_duration = duration
        self.refresh()
        if self.sentences:
            self.selectRow(0)
        self.updated.emit()

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def checkbox_state(self, field: str, rows=None):
        if field not in ("include", "reviewed"):
            raise ValueError("Choose Include or Reviewed.")
        rows = list(range(len(self.sentences))) if rows is None else list(rows)
        if not rows:
            return Qt.Unchecked
        checked = sum(getattr(self.sentences[row], field) for row in rows)
        if checked == len(rows):
            return Qt.Checked
        return Qt.PartiallyChecked if checked else Qt.Unchecked

    def set_checked(self, field: str, checked: bool, rows=None):
        if field not in ("include", "reviewed"):
            raise ValueError("Choose Include or Reviewed.")
        rows = list(range(len(self.sentences))) if rows is None else sorted(set(rows))
        if not rows:
            return
        if any(not 0 <= row < len(self.sentences) for row in rows):
            raise ValueError("Select existing sentence rows.")
        for row in rows:
            setattr(self.sentences[row], field, checked)
        self.refresh()
        self.updated.emit()

    def refresh(self):
        selected = self.selected_rows()
        current = self.currentRow()
        blocker = QSignalBlocker(self)
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
        self.clearSelection()
        selection = self.selectionModel()
        for row in selected:
            if row < len(self.sentences):
                selection.select(self.model().index(row, 0),
                                 QItemSelectionModel.Select | QItemSelectionModel.Rows)
        if self.sentences:
            selection.setCurrentIndex(
                self.model().index(min(max(current, 0), len(self.sentences) - 1), 0),
                QItemSelectionModel.NoUpdate)
        blocker.unblock()

    def item_changed(self, item):
        row, col = item.row(), item.column()
        if not 0 <= row < len(self.sentences):
            return
        if col in (6, 7):
            self.set_checked("include" if col == 6 else "reviewed",
                             item.checkState() == Qt.Checked, [row])
            return
        sentence = self.sentences[row]
        old = (sentence.text, sentence.start, sentence.end)
        try:
            if col in (1, 2, 3):
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
        rows = self.selected_rows()
        if len(rows) != 1:
            raise ValueError("Select exactly one sentence to merge with the following sentence.")
        row = rows[0]
        if row + 1 >= len(self.sentences):
            raise ValueError("Select a sentence with a following sentence to merge.")
        self.sentences[row:row + 2] = [
            merge_sentences(self.sentences[row], self.sentences[row + 1])]
        self.refresh()
        self.updated.emit()

    def split_selected(self, after_word: int):
        rows = self.selected_rows()
        if len(rows) != 1:
            raise ValueError("Select exactly one sentence to split.")
        row = rows[0]
        self.sentences[row:row + 1] = list(split_sentence(self.sentences[row], after_word))
        self.refresh()
        self.updated.emit()
