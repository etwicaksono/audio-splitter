from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget


def clock(seconds: float) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{remainder:02d}"


class Waveform(QWidget):
    seek = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks = []
        self.position = 0.0
        self.setMinimumHeight(80)
        self.setAccessibleName("Audio waveform, click to seek")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f0f5ff"))
        middle = self.height() / 2
        painter.setPen(QPen(QColor("#94a9ca"), 1))
        painter.drawLine(0, int(middle), self.width(), int(middle))
        painter.setPen(QPen(QColor("#3977db"), 2))
        for index, peak in enumerate(self.peaks):
            x = int(index / max(1, len(self.peaks) - 1) * (self.width() - 1))
            amplitude = max(1, peak * (middle - 8))
            painter.drawLine(x, int(middle - amplitude), x, int(middle + amplitude))
        painter.setPen(QPen(QColor("#e36b36"), 2))
        x = int(self.position * (self.width() - 1))
        painter.drawLine(x, 0, x, self.height())
        painter.end()

    def mousePressEvent(self, event):
        self.seek.emit(max(0, min(1, event.position().x() / max(1, self.width()))))


class AudioPlayer(QWidget):
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)
        self.duration = 0.0
        self.clip_end = None
        self.pending_preview = None
        self.waveform = Waveform()
        self.play_button = QPushButton("Play original")
        self.stop_button = QPushButton("Stop")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setAccessibleName("Playback position")
        self.time_label = QLabel("00:00 / 00:00")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.waveform)
        controls = QHBoxLayout()
        for widget in (self.play_button, self.stop_button, self.slider, self.time_label):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.play_button.clicked.connect(self.toggle)
        self.stop_button.clicked.connect(self.stop)
        self.slider.sliderMoved.connect(lambda value: self.seek(value / 10000))
        self.waveform.seek.connect(self.seek)
        self.player.positionChanged.connect(self.position_changed)
        self.player.mediaStatusChanged.connect(self.media_status)
        self.player.errorOccurred.connect(
            lambda *_: self.error.emit("Audio playback failed: " + self.player.errorString()))
        self.player.playbackStateChanged.connect(self.state_changed)
        # Multimedia positionChanged can be too coarse for short sentence previews.
        self.preview_timer = QTimer(self)
        self.preview_timer.setTimerType(Qt.PreciseTimer)
        self.preview_timer.setInterval(15)
        self.preview_timer.timeout.connect(self.check_preview_end)
        self.preview_timer.start()

    def load(self, path: Path, duration: float, peaks: list[float]):
        self.stop()
        self.duration = duration
        self.waveform.peaks = peaks
        self.waveform.position = 0
        self.waveform.update()
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.position_changed(0)

    def clear(self):
        self.stop()
        self.player.setSource(QUrl())
        self.duration = 0
        self.waveform.peaks = []
        self.position_changed(0)

    def stop(self):
        self.clip_end = None
        self.pending_preview = None
        self.player.stop()

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.clip_end = None
            self.pending_preview = None
            self.player.play()

    def seek(self, fraction: float):
        self.clip_end = None
        self.pending_preview = None
        self.player.setPosition(int(fraction * self.duration * 1000))

    def preview(self, start: float, end: float):
        self.player.pause()
        self.pending_preview = (start, end)
        self.clip_end = None
        if self.player.mediaStatus() in (
                QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia,
                QMediaPlayer.BufferingMedia, QMediaPlayer.EndOfMedia):
            self._play_pending()

    def _play_pending(self):
        if self.pending_preview:
            start, end = self.pending_preview
            self.pending_preview = None
            self.player.setPosition(int(start * 1000))
            self.clip_end = int(end * 1000)
            self.player.play()

    def media_status(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._play_pending()

    def position_changed(self, milliseconds):
        if self.clip_end is not None and milliseconds >= self.clip_end:
            self.player.pause()
            self.clip_end = None
        seconds = milliseconds / 1000
        self.slider.setValue(int(seconds / self.duration * 10000) if self.duration else 0)
        self.waveform.position = min(1, seconds / self.duration) if self.duration else 0
        self.waveform.update()
        self.time_label.setText(f"{clock(seconds)} / {clock(self.duration)}")

    def check_preview_end(self):
        if self.clip_end is not None and self.player.position() >= self.clip_end:
            self.position_changed(self.player.position())

    def state_changed(self, state):
        self.play_button.setText("Pause" if state == QMediaPlayer.PlayingState else "Play original")
