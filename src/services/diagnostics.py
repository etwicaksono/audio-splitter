"""Opt-in developer smoke test using the actual desktop controls and workers."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QTimer, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox


def run_self_test(app, window, arguments) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, required=True, metavar="AUDIO")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--model", choices=["base", "small", "medium"], default="small")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(arguments)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = {"input": str(args.self_test), "model": args.model, "errors": [],
              "stages": {}, "timer_ticks": 0}
    state = {"step": "import", "start": time.perf_counter(), "last": time.perf_counter()}
    report_path = args.report_dir / "report.json"

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def fail(message):
        report["errors"].append(str(message))
        save()
        if window.worker:
            window.worker.requestInterruption()
        else:
            app.exit(1)

    # Replace only modal chooser/message dialogs; real widgets/signals/workers remain in use.
    window.show_error = fail
    window.table.error.disconnect()
    window.table.error.connect(fail)
    window.player.error.disconnect()
    window.player.error.connect(fail)
    QMessageBox.warning = lambda *a, **k: fail(a[-1]) or QMessageBox.Ok
    QMessageBox.information = lambda *a, **k: QMessageBox.Ok
    QMessageBox.question = lambda *a, **k: QMessageBox.Yes
    QFileDialog.getExistingDirectory = lambda *a, **k: str(args.report_dir)
    QInputDialog.getText = lambda *a, **k: ("clips", True)
    window.model_combo.setCurrentText(args.model)
    window.offline_box.setChecked(args.offline)
    window.before_spin.setValue(100)
    window.after_spin.setValue(150)
    window.import_audio(args.self_test)

    def tick():
        report["timer_ticks"] += 1
        if time.perf_counter() - state["start"] > 1800:
            fail("Smoke test exceeded 30 minutes.")
            timer.stop()
            return
        if window.worker:
            return
        if report["errors"]:
            app.exit(1)
            return
        try:
            step = state["step"]
            now = time.perf_counter()
            if step == "import":
                assert window.metadata and window.process_button.isEnabled()
                report["stages"]["import_seconds"] = now - state["last"]
                report["duration_seconds"] = window.metadata.duration
                state.update(step="transcribe", last=now)
                window.process_button.click()
            elif step == "transcribe":
                assert window.table.sentences
                report["stages"]["transcription_seconds"] = now - state["last"]
                report["sentences_detected"] = len(window.table.sentences)
                report["review_required"] = sum(s.needs_review for s in window.table.sentences)
                (args.report_dir / "sentences.json").write_text(
                    json.dumps([asdict(s) for s in window.table.sentences],
                               ensure_ascii=False, indent=2), encoding="utf-8")
                window.grab().save(str(args.report_dir / "desktop.png"))
                first_safe = next(i for i, s in enumerate(window.table.sentences) if not s.needs_review)
                state.update(step="preview", last=now, preview_row=first_safe, saw_playing=False)
                window.table.cellWidget(first_safe, 5).click()
            elif step == "preview":
                if window.player.player.playbackState() == QMediaPlayer.PlayingState:
                    state["saw_playing"] = True
                if state["saw_playing"] and window.player.player.playbackState() == QMediaPlayer.PausedState:
                    report["preview_played_and_stopped"] = True
                    # Do not falsely approve uncertain sentences to make a test pass.
                    for row, sentence in enumerate(window.table.sentences):
                        if sentence.needs_review:
                            window.table.item(row, 6).setCheckState(Qt.Unchecked)
                    report["sentences_exported"] = sum(s.include for s in window.table.sentences)
                    state.update(step="export", last=now)
                    window.zip_button.click()
            elif step == "export":
                assert (args.report_dir / "clips" / "transcript.csv").is_file()
                assert (args.report_dir / "clips.zip").is_file()
                report["stages"]["export_seconds"] = now - state["last"]
                report["total_seconds"] = now - state["start"]
                report["success"] = True
                save()
                window.player.clear()
                timer.stop()
                app.exit(0)
        except Exception:
            fail(traceback.format_exc())

    timer = QTimer(window)
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    return app.exec()
