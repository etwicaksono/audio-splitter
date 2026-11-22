from dataclasses import dataclass
import csv
import math
from pathlib import Path
import shutil
import tempfile
import zipfile

from src.models.sentence import Sentence
from src.services.audio_service import AudioMetadata, AudioService, clip_ranges
from src.services.errors import AppError, Cancelled


def filename_for(number: int) -> str:
    if number < 1:
        raise ValueError("Clip numbers start at one.")
    return f"{number:03d}.mp3"


def write_transcripts(folder: Path, rows: list[dict]) -> None:
    with (folder / "transcript.txt").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            text = " ".join(row["sentence"].splitlines())
            handle.write(f'{row["filename"]}\t{text}\n')
    with (folder / "transcript.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "filename", "sentence", "start_time", "end_time", "duration",
        ])
        writer.writeheader()
        writer.writerows(rows)


@dataclass(frozen=True)
class ExportResult:
    folder: Path
    count: int
    archive: Path | None


class ExportService:
    def __init__(self, audio: AudioService | None = None):
        self.audio = audio or AudioService()

    def export(self, source: AudioMetadata, sentences: list[Sentence], destination: Path,
               before: float = 0.1, after: float = 0.15, make_zip: bool = False,
               prefer_copy: bool = False, silences=None, progress=None, cancel=None
               ) -> ExportResult:
        destination = Path(destination).resolve()
        archive = destination.parent / (destination.name + ".zip") if make_zip else None
        if destination.exists() or (archive and archive.exists()):
            raise AppError("That output folder or ZIP already exists. Choose a new name.")
        if not destination.parent.is_dir():
            raise AppError("The output parent folder does not exist.")
        included = [(i, sentence) for i, sentence in enumerate(sentences) if sentence.include]
        if not included:
            raise AppError("Include at least one sentence to export.")
        if any(sentence.needs_review for _, sentence in included):
            raise AppError("Some sentences need review. Preview, correct, and mark them reviewed.")
        ranges = clip_ranges(sentences, source.duration, before, after, silences)
        expected = sum(ranges[i][1] - ranges[i][0] for i, _ in included) * 24000
        required = math.ceil(expected * (2.2 if make_zip else 1.2) + 10 * 1024 * 1024)
        if shutil.disk_usage(destination.parent).free < required:
            raise AppError("Not enough disk space. Choose another output drive.")
        committed = False
        with tempfile.TemporaryDirectory(prefix=".sentence-export-", dir=destination.parent) as temp:
            stage = Path(temp) / "clips"
            stage.mkdir()
            try:
                rows = []
                for number, (index, sentence) in enumerate(included, 1):
                    if cancel and cancel():
                        raise Cancelled("Export cancelled. No partial export was kept.")
                    start, end = ranges[index]
                    filename = filename_for(number)
                    self.audio.cut(source, stage / filename, start, end, prefer_copy, cancel)
                    rows.append({
                        "filename": filename, "sentence": sentence.text,
                        "start_time": f"{start:.6f}", "end_time": f"{end:.6f}",
                        "duration": f"{end - start:.6f}",
                    })
                    if progress:
                        progress(int(number / len(included) * 90),
                                 f"Exported clip {number} of {len(included)}")
                write_transcripts(stage, rows)
                staged_zip = Path(temp) / "archive.zip"
                if make_zip:
                    if progress:
                        progress(92, "Packaging MP3s and transcripts…")
                    with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as bundle:
                        for file in sorted(stage.iterdir()):
                            if cancel and cancel():
                                raise Cancelled("Export cancelled. No partial export was kept.")
                            bundle.write(file, file.name)
                    with zipfile.ZipFile(staged_zip) as bundle:
                        if bundle.testzip() is not None:
                            raise AppError("ZIP verification failed.")
                if cancel and cancel():
                    raise Cancelled("Export cancelled. No partial export was kept.")
                stage.rename(destination)
                committed = True
                if archive:
                    staged_zip.rename(archive)
                if progress:
                    progress(100, f"Finished: {len(included)} sentence clips")
                return ExportResult(destination, len(included), archive)
            except BaseException as exc:
                if committed:
                    shutil.rmtree(destination)
                if isinstance(exc, (AppError, ValueError)):
                    raise
                if isinstance(exc, OSError):
                    raise AppError("Cannot write the output. Check free space and folder permissions.") from exc
                raise
