import gc
import os
from pathlib import Path
import threading

from platformdirs import user_cache_dir

from src.models.sentence import Word
from src.services.errors import AppError, Cancelled


MODEL_NAMES = ("base", "small", "medium")
MODEL_LOCK = threading.Lock()


class TranscriptionService:
    def __init__(self, model_name: str = "small", local_model: Path | None = None,
                 offline: bool = False):
        if model_name not in MODEL_NAMES:
            raise AppError("Choose the base, small, or medium model.")
        self.model_name = model_name
        self.local_model = local_model
        self.offline = offline

    def transcribe(self, path: Path, duration: float, progress=None, partial=None,
                   cancel=None) -> tuple[list[Word], str]:
        from faster_whisper import WhisperModel

        def report(value, message):
            if progress:
                progress(value, message)

        def check():
            if cancel and cancel():
                raise Cancelled("Transcription cancelled.")

        model = None
        # One model at a time, including callers outside the GUI.
        with MODEL_LOCK:
            try:
                check()
                report(0, "Loading model. First use may download it; this can take several minutes.")
                root = Path(__file__).resolve().parents[2]
                bundled = root / "models" / self.model_name
                import sys
                if getattr(sys, "frozen", False):
                    bundled = Path(sys._MEIPASS) / "models" / self.model_name
                model_path = self.local_model or (bundled if bundled.is_dir() else None)
                if model_path and not (Path(model_path) / "tokenizer.json").is_file():
                    raise AppError("Model folder must contain model.bin, config.json, and tokenizer.json.")
                try:
                    model = WhisperModel(
                        str(model_path) if model_path else self.model_name,
                        device="cpu", compute_type="int8",
                        cpu_threads=min(8, max(1, (os.cpu_count() or 4) - 2)), num_workers=1,
                        download_root=user_cache_dir("AI Audio Sentence Splitter", "AudioSplitter"),
                        local_files_only=self.offline or bool(model_path),
                    )
                except Exception as exc:
                    raise AppError(
                        "Could not load the speech model. For first use, connect to the internet "
                        "and turn off Offline mode, or select a complete local model folder. "
                        "Check free disk space and try the base model if memory is limited."
                    ) from exc
                check()
                report(3, "Transcribing English audio on CPU (int8)…")
                segments, info = model.transcribe(
                    str(path), language="en", word_timestamps=True, vad_filter=True,
                    beam_size=5, vad_parameters={"min_silence_duration_ms": 500},
                )
                words = []
                for segment in segments:
                    check()
                    if segment.text.strip() and not segment.words:
                        raise AppError(
                            "Speech was found without word timestamps. Try another model. "
                            "No guessed clips have been created."
                        )
                    for word in segment.words or []:
                        if word.word.strip():
                            if word.start is None or word.end is None or word.end < word.start:
                                raise AppError("A spoken word has no usable timestamps. Retry with another model.")
                            # Upstream alignment can legitimately assign a zero-duration token.
                            # Keep its original timing and text; detection flags it for review.
                            words.append(Word(word.word, word.start, word.end, word.probability))
                    if partial:
                        partial(segment.text.strip())
                    report(min(95, int(3 + 92 * segment.end / duration)),
                           f"Transcribed {min(segment.end, duration):.1f} of {duration:.1f} seconds")
                if not words:
                    raise AppError("No speech was detected. Check the audio or choose another model.")
                report(96, "Finding complete sentences and refining boundaries…")
                # English is explicitly requested, not automatically detected.
                return words, info.language
            except (AppError, Cancelled):
                raise
            except Exception as exc:
                raise AppError("Transcription failed. Try the base model or another audio file.") from exc
            finally:
                del model
                gc.collect()
