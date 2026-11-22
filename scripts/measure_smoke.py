"""Measure a fresh GUI process, including native libraries and audio subprocesses."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.report_dir.mkdir(parents=True, exist_ok=True)
    command = [str(args.executable.resolve())] if args.executable else \
        [sys.executable, str(root / "app.py")]
    command += ["--self-test", str(args.audio.resolve()),
                "--report-dir", str(args.report_dir.resolve()), "--offline"]
    peak = 0
    began = time.perf_counter()
    with (args.report_dir / "process.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        observed = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                children = observed.children(recursive=True)
                total = observed.memory_info().rss
                for child in children:
                    try:
                        total += child.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, total)
            except psutil.Error:
                pass
            if time.perf_counter() - began > 1900:
                for child in observed.children(recursive=True):
                    child.kill()
                process.kill()
                raise RuntimeError("Smoke test timed out.")
            time.sleep(0.1)
    summary = {"exit_code": process.returncode, "wall_seconds": time.perf_counter() - began,
               "peak_process_tree_rss_mb": peak / 1024 / 1024}
    (args.report_dir / "measurements.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
