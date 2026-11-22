from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
    QWidget, QInputDialog, QSplitter, QGroupBox, QScrollArea,
)

from src.services.audio_service import SUPPORTED, clip_ranges
from src.services.errors import AppError
from src.ui.audio_player import AudioPlayer
from src.ui.sentence_table import SentenceTable
from src.workers.processing_worker import ImportWorker, ProcessingWorker, ExportWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Audio Sentence Splitter")
        self.resize(1400, 940)
        self.setMinimumSize(1000, 720)
        self.setAcceptDrops(True)
        self.settings = QSettings("AudioSplitter", "AI Audio Sentence Splitter")
        self.metadata = None
        self.silences = []
        self.worker = None
        self.local_model = None
        self.close_when_idle = False
        central = QWidget()
        central.setObjectName("central")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        title = QLabel("AI Audio Sentence Splitter")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Local English transcription • Review sentence boundaries • Export clean MP3 clips")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        import_box = QGroupBox("1. Import a recording")
        import_layout = QVBoxLayout(import_box)
        import_row = QHBoxLayout()
        self.browse_button = QPushButton("Browse audio…")
        self.file_label = QLabel("Drop an MP3, WAV, M4A, FLAC, or AAC file here")
        self.file_label.setWordWrap(True)
        import_row.addWidget(self.browse_button)
        import_row.addWidget(self.file_label, 1)
        import_layout.addLayout(import_row)
        self.player = AudioPlayer()
        import_layout.addWidget(self.player)
        layout.addWidget(import_box)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Whisper model"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["base", "small", "medium"])
        self.model_combo.setCurrentText(self.settings.value("model", "small"))
        model_row.addWidget(self.model_combo)
        model_row.addWidget(QLabel("Language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("English (en)")
        model_row.addWidget(self.language_combo)
        self.local_button = QPushButton("Local model folder…")
        self.local_button.setToolTip("Optional: choose a complete Faster-Whisper/CTranslate2 model folder.")
        model_row.addWidget(self.local_button)
        self.offline_box = QCheckBox("Offline mode")
        self.offline_box.setChecked(self.settings.value("offline", False, type=bool))
        self.offline_box.setToolTip("Use only cached or local models. No model download is attempted.")
        model_row.addWidget(self.offline_box)
        self.refine_box = QCheckBox("Use silence refinement")
        self.refine_box.setChecked(True)
        model_row.addWidget(self.refine_box)
        model_row.addStretch()
        self.process_button = QPushButton("Start Processing")
        self.process_button.setObjectName("primary")
        model_row.addWidget(self.process_button)
        layout.addLayout(model_row)
        self.local_label = QLabel("CPU • int8 • One model loaded at a time")
        self.local_label.setObjectName("muted")
        layout.addWidget(self.local_label)
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
        self.status_label = QLabel("Import audio to begin.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Vertical)
        transcript_box = QGroupBox("Live transcript")
        transcript_layout = QVBoxLayout(transcript_box)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Transcribed English text will appear here.")
        self.transcript.setMaximumBlockCount(100000)
        transcript_layout.addWidget(self.transcript)
        splitter.addWidget(transcript_box)
        table_box = QWidget()
        table_box.setObjectName("sentencePanel")
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel("2. Review sentences")
        table_layout.addWidget(self.summary_label)
        self.table = SentenceTable()
        bulk_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all rows")
        self.selection_label = QLabel("0 selected")
        self.include_selected_box = QCheckBox("Include selected")
        self.reviewed_selected_box = QCheckBox("Reviewed selected")
        self.include_all_box = QCheckBox("Include all")
        self.reviewed_all_box = QCheckBox("Reviewed all")
        bulk_row.addWidget(self.select_all_button)
        bulk_row.addWidget(self.selection_label)
        bulk_row.addStretch()
        for box, field, scope in (
                (self.include_selected_box, "Include", "selected"),
                (self.reviewed_selected_box, "Reviewed", "selected"),
                (self.include_all_box, "Include", "all"),
                (self.reviewed_all_box, "Reviewed", "all")):
            box.setTristate(True)
            box.setAccessibleName(f"{field} for {scope} sentences")
            box.setToolTip(
                f"Check or uncheck {field} for {scope} sentences. A dash means mixed values."
                + (" Mark Reviewed only after checking the clips." if field == "Reviewed" else ""))
            bulk_row.addWidget(box)
        table_layout.addLayout(bulk_row)
        table_layout.addWidget(self.table)
        edit_row = QHBoxLayout()
        self.merge_button = QPushButton("Merge with next")
        self.split_button = QPushButton("Split at word…")
        edit_row.addWidget(self.merge_button)
        edit_row.addWidget(self.split_button)
        hint = QLabel("Ctrl/Shift-click rows to select multiple. Shift-click checkboxes to change a range. "
                      "Double-click text or times to edit. Yellow rows must be reviewed before export.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        edit_row.addWidget(hint, 1)
        table_layout.addLayout(edit_row)
        splitter.addWidget(table_box)
        splitter.setSizes([130, 330])
        layout.addWidget(splitter, 1)

        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Padding before"))
        self.before_spin = QSpinBox()
        self.before_spin.setRange(0, 2000)
        self.before_spin.setSuffix(" ms")
        self.before_spin.setValue(self.settings.value("padding_before", 100, type=int))
        export_row.addWidget(self.before_spin)
        export_row.addWidget(QLabel("after"))
        self.after_spin = QSpinBox()
        self.after_spin.setRange(0, 2000)
        self.after_spin.setSuffix(" ms")
        self.after_spin.setValue(self.settings.value("padding_after", 150, type=int))
        export_row.addWidget(self.after_spin)
        self.copy_box = QCheckBox("Prefer lossless copy when safe")
        self.copy_box.setToolTip("Exact full-file MP3 copy only. Sentence cuts re-encode at 192 kbps for accurate boundaries.")
        self.copy_box.setChecked(True)
        export_row.addWidget(self.copy_box)
        export_row.addStretch()
        self.export_button = QPushButton("Export MP3")
        self.zip_button = QPushButton("Export ZIP")
        self.zip_button.setObjectName("primary")
        export_row.addWidget(self.export_button)
        export_row.addWidget(self.zip_button)
        layout.addLayout(export_row)

        self.browse_button.clicked.connect(self.browse)
        self.local_button.clicked.connect(self.select_local_model)
        self.model_combo.currentTextChanged.connect(self.clear_local_model)
        self.process_button.clicked.connect(self.process)
        self.cancel_button.clicked.connect(self.cancel)
        self.table.preview_requested.connect(self.preview)
        self.table.error.connect(self.show_error)
        self.table.updated.connect(self.update_summary)
        self.table.itemSelectionChanged.connect(self.update_bulk_controls)
        self.select_all_button.clicked.connect(self.toggle_row_selection)
        self.include_selected_box.clicked.connect(
            lambda checked: self.table.set_checked("include", checked, self.table.selected_rows()))
        self.reviewed_selected_box.clicked.connect(
            lambda checked: self.table.set_checked("reviewed", checked, self.table.selected_rows()))
        self.include_all_box.clicked.connect(
            lambda checked: self.table.set_checked("include", checked))
        self.reviewed_all_box.clicked.connect(
            lambda checked: self.table.set_checked("reviewed", checked))
        self.merge_button.clicked.connect(self.merge)
        self.split_button.clicked.connect(self.split)
        self.export_button.clicked.connect(lambda: self.export(False))
        self.zip_button.clicked.connect(lambda: self.export(True))
        self.player.error.connect(self.show_error)
        self.update_controls()

    def show_error(self, message):
        self.status_label.setText(message)
        QMessageBox.warning(self, "Audio Sentence Splitter", message)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose audio", str(Path.home()),
            "Audio files (*.mp3 *.wav *.m4a *.flac *.aac)")
        if path:
            self.import_audio(Path(path))

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if not self.worker and len(urls) == 1 and urls[0].isLocalFile() and \
                Path(urls[0].toLocalFile()).suffix.lower() in SUPPORTED:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.worker and event.mimeData().hasUrls():
            self.import_audio(Path(event.mimeData().urls()[0].toLocalFile()))
            event.acceptProposedAction()

    def import_audio(self, path: Path):
        if self.worker:
            return
        if self.table.sentences and QMessageBox.question(
                self, "Replace current recording?", "This will discard the current sentence edits.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.player.clear()
        self.metadata = None
        self.silences = []
        self.table.set_sentences([], 0)
        self.transcript.clear()
        self.file_label.setText(str(path))
        worker = ImportWorker(path, self)
        worker.result.connect(self.imported)
        self.start_worker(worker)

    def imported(self, value):
        self.metadata, peaks = value
        metadata = self.metadata
        self.file_label.setText(
            f"{metadata.path.name}  |  {metadata.duration:.2f} seconds  |  "
            f"{metadata.size / 1024 / 1024:.2f} MB  |  {metadata.sample_rate} Hz")
        self.player.load(metadata.path, metadata.duration, peaks)

    def clear_local_model(self, *_):
        self.local_model = None
        self.local_label.setText("CPU • int8 • One model loaded at a time")

    def select_local_model(self):
        directory = QFileDialog.getExistingDirectory(self, "Select complete Faster-Whisper model folder")
        if directory:
            path = Path(directory)
            if not all((path / file).is_file() for file in ("model.bin", "config.json", "tokenizer.json")):
                self.show_error("Choose a model folder containing model.bin, config.json, and tokenizer.json.")
                return
            self.local_model = path
            self.local_label.setText(f"Local model: {path} • CPU • int8")

    def process(self):
        if not self.metadata or self.worker:
            return
        if self.table.sentences and QMessageBox.question(
                self, "Transcribe again?", "This will replace the current sentence edits.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.player.stop()
        self.table.set_sentences([], self.metadata.duration)
        self.silences = []
        self.transcript.clear()
        worker = ProcessingWorker(
            self.metadata, self.model_combo.currentText(), self.local_model,
            self.offline_box.isChecked(), self.refine_box.isChecked(), self)
        worker.partial.connect(self.append_transcript)
        worker.result.connect(self.processed)
        self.start_worker(worker)

    def append_transcript(self, text):
        self.transcript.appendPlainText(text)
        self.summary_label.setText(
            f"Transcribing… about {self.transcript.toPlainText().count('.')} sentences so far")

    def processed(self, value):
        self.silences = value.silences
        self.table.set_sentences(value.sentences, self.metadata.duration)
        self.transcript.setPlainText("\n".join(sentence.text for sentence in value.sentences))
        count = sum(s.needs_review for s in value.sentences)
        self.status_label.setText(
            f"English ({value.language}, requested language). Found {len(value.sentences)} "
            f"sentences; {count} need review. Preview clips before exporting.")

    def start_worker(self, worker):
        self.worker = worker
        self.progress_bar.setRange(0, 0)
        worker.progress.connect(self.progress)
        worker.failed.connect(self.show_error)
        worker.cancelled.connect(lambda: self.status_label.setText("Cancelled. No export was kept."))
        worker.finished.connect(self.worker_finished)
        self.update_controls()
        worker.start()

    def progress(self, value, message):
        self.progress_bar.setRange(0, 0 if value == 0 else 100)
        if value:
            self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        self.progress_bar.setRange(0, 100)
        if worker:
            worker.deleteLater()
        self.update_controls()
        if self.close_when_idle:
            self.close()

    def cancel(self):
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.status_label.setText(
                "Cancelling after the current step. Model loading/download cannot be interrupted immediately.")

    def update_controls(self):
        busy = self.worker is not None
        for widget in (self.browse_button, self.model_combo, self.language_combo,
                       self.local_button, self.offline_box, self.refine_box,
                       self.before_spin, self.after_spin, self.copy_box, self.table,
                       self.player):
            widget.setEnabled(not busy)
        self.process_button.setEnabled(not busy and self.metadata is not None)
        has_sentences = bool(self.table.sentences)
        for widget in (self.export_button, self.zip_button):
            widget.setEnabled(not busy and has_sentences)
        self.cancel_button.setEnabled(busy)
        self.update_bulk_controls()

    def toggle_row_selection(self):
        if self.worker or not self.table.sentences:
            return
        if len(self.table.selected_rows()) == len(self.table.sentences):
            self.table.clearSelection()
        else:
            self.table.selectAll()

    def update_bulk_controls(self):
        rows = self.table.selected_rows()
        count = len(self.table.sentences)
        ready = self.worker is None and count > 0
        self.selection_label.setText(f"{len(rows)} selected")
        self.select_all_button.setText(
            "Unselect all rows" if count and len(rows) == count else "Select all rows")
        self.select_all_button.setEnabled(ready)
        for box, field, target in (
                (self.include_selected_box, "include", rows),
                (self.reviewed_selected_box, "reviewed", rows),
                (self.include_all_box, "include", None),
                (self.reviewed_all_box, "reviewed", None)):
            box.setEnabled(ready and (target is None or bool(target)))
            with QSignalBlocker(box):
                box.setCheckState(self.table.checkbox_state(field, target))
        self.merge_button.setEnabled(ready and len(rows) == 1 and rows[0] + 1 < count)
        self.split_button.setEnabled(ready and len(rows) == 1)

    def update_summary(self):
        sentences = self.table.sentences
        self.summary_label.setText(
            f"2. Review sentences  |  {len(sentences)} detected  |  "
            f"{sum(s.include for s in sentences)} included  |  "
            f"{sum(s.include and s.needs_review for s in sentences)} need review")
        self.update_controls()

    def preview(self, index):
        if not self.metadata or self.worker:
            return
        try:
            ranges = clip_ranges(self.table.sentences, self.metadata.duration,
                                 self.before_spin.value() / 1000, self.after_spin.value() / 1000,
                                 self.silences)
            self.player.preview(*ranges[index])
            self.status_label.setText(f"Previewing sentence {index + 1} with export padding.")
        except (AppError, ValueError) as exc:
            self.show_error(str(exc))

    def merge(self):
        self.player.stop()
        try:
            self.table.merge_selected()
        except ValueError as exc:
            self.show_error(str(exc))

    def split(self):
        row = self.table.currentRow()
        if row < 0:
            return
        sentence = self.table.sentences[row]
        if len(sentence.words) < 2:
            self.show_error("This sentence has fewer than two timestamped words.")
            return
        options = [
            f"{index}: after {sentence.words[index - 1].text.strip()} "
            f"({sentence.words[index - 1].end:.3f} s)"
            for index in range(1, len(sentence.words))
        ]
        option, ok = QInputDialog.getItem(
            self, "Split sentence", "Choose the last word of the first sentence:", options, 0, False)
        if ok:
            self.player.stop()
            try:
                self.table.split_selected(options.index(option) + 1)
            except ValueError as exc:
                self.show_error(str(exc))

    def export(self, make_zip):
        if not self.metadata or self.worker:
            return
        included = [s for s in self.table.sentences if s.include]
        if not included:
            self.show_error("Include at least one sentence.")
            return
        if any(s.needs_review for s in included):
            self.show_error("Yellow rows need review. Preview, correct if needed, then check Reviewed.")
            return
        parent = QFileDialog.getExistingDirectory(self, "Choose output parent folder")
        if not parent:
            return
        default = self.metadata.path.stem + "_split"
        name, ok = QInputDialog.getText(self, "Output folder name", "Create a new folder named:", text=default)
        if not ok:
            return
        name = name.strip()
        if (not name or name in {".", ".."} or any(c in name for c in '<>:"/\\|?*') or
                name.endswith((".", " "))):
            self.show_error("Use a simple new folder name without special characters.")
            return
        self.player.stop()
        worker = ExportWorker(
            self.metadata, deepcopy(self.table.sentences), Path(parent) / name,
            {"before": self.before_spin.value() / 1000, "after": self.after_spin.value() / 1000,
             "make_zip": make_zip, "prefer_copy": self.copy_box.isChecked(),
             "silences": list(self.silences)}, self)
        worker.result.connect(self.exported)
        self.start_worker(worker)

    def exported(self, result):
        message = f"Exported {result.count} MP3 clips and both transcripts to:\n{result.folder}"
        if result.archive:
            message += f"\n\nZIP archive:\n{result.archive}"
        self.status_label.setText(message)
        QMessageBox.information(self, "Export complete", message)

    def closeEvent(self, event):
        if self.worker:
            if QMessageBox.question(
                    self, "Processing is running",
                    "Cancel processing and close when the current step finishes?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                self.close_when_idle = True
                self.cancel()
            event.ignore()
            return
        self.settings.setValue("model", self.model_combo.currentText())
        self.settings.setValue("offline", self.offline_box.isChecked())
        self.settings.setValue("padding_before", self.before_spin.value())
        self.settings.setValue("padding_after", self.after_spin.value())
        self.player.clear()
        event.accept()
