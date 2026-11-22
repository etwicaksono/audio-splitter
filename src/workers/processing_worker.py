from dataclasses import dataclass
from pathlib import Path
import logging

from PySide6.QtCore import QThread, Signal

from src.models.sentence import Sentence
from src.services.audio_service import AudioMetadata, AudioService
from src.services.errors import AppError, Cancelled
from src.services.export_service import ExportService
from src.services.sentence_detection import detect_sentences
from src.services.transcription_service import TranscriptionService


@dataclass
class ProcessingResult:
    sentences: list[Sentence]
    language: str
    silences: list[tuple[float, float]]


class BackgroundWorker(QThread):
    progress = Signal(int, str)
    partial = Signal(str)
    result = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def execute(self):
        raise NotImplementedError

    def run(self):
        try:
            value = self.execute()
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.result.emit(value)
        except Cancelled:
            self.cancelled.emit()
        except (AppError, ValueError, OSError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            logging.exception("Background operation failed")
            self.failed.emit("An unexpected error occurred. Restart the app and try the base model.")


class ImportWorker(BackgroundWorker):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path

    def execute(self):
        audio = AudioService()
        self.progress.emit(0, "Reading audio metadata and waveform…")
        metadata = audio.probe(self.path)
        peaks = audio.waveform(metadata, cancel=self.isInterruptionRequested)
        self.progress.emit(100, "Audio ready")
        return metadata, peaks


class ProcessingWorker(BackgroundWorker):
    def __init__(self, metadata: AudioMetadata, model: str, local_model=None,
                 offline=False, refine=True, parent=None):
        super().__init__(parent)
        self.metadata = metadata
        self.model = model
        self.local_model = local_model
        self.offline = offline
        self.refine = refine

    def execute(self):
        words, language = TranscriptionService(
            self.model, self.local_model, self.offline,
        ).transcribe(self.metadata.path, self.metadata.duration,
                     self.progress.emit, self.partial.emit, self.isInterruptionRequested)
        sentences = detect_sentences(words, self.metadata.duration)
        audio = AudioService()
        silences = audio.silences(self.metadata, self.isInterruptionRequested) if self.refine else []
        if self.refine:
            audio.refine_boundaries(self.metadata, sentences, silences)
        self.progress.emit(100, f"Found {len(sentences)} sentences")
        return ProcessingResult(sentences, language, silences)


class ExportWorker(BackgroundWorker):
    def __init__(self, metadata, sentences, destination, settings, parent=None):
        super().__init__(parent)
        self.metadata = metadata
        self.sentences = sentences
        self.destination = destination
        self.settings = settings

    def execute(self):
        return ExportService().export(
            self.metadata, self.sentences, self.destination, **self.settings,
            progress=self.progress.emit, cancel=self.isInterruptionRequested,
        )
