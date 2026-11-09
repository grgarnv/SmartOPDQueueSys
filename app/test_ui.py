"""Browser checks (test_ui.js) against a throwaway demo server. Run: python3 app/test_ui.py

Optional: needs playwright-cli (npm install -g @playwright/cli) and its Chromium. Without it the
check is skipped, so the other suites keep working with Python alone.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from test_api import TMP, start_server

HERE = Path(__file__).parent


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("ui: skipped (playwright-cli is not installed)")
        return
    proc, base = start_server(f"{TMP}/ui.db")
    script = Path(TMP) / "test_ui.js"
    script.write_text((HERE / "test_ui.js").read_text().replace("__BASE__", base))
    session = ["-s=opd-ui-test"]
    try:
        subprocess.run([cli, *session, "open", "about:blank"], capture_output=True, check=True, timeout=60, cwd=TMP)
        run = subprocess.run([cli, *session, "run-code", f"--filename={script}"], capture_output=True, text=True, timeout=300, cwd=TMP)
    finally:
        subprocess.run([cli, *session, "close"], capture_output=True, timeout=60, cwd=TMP)  # cwd: the CLI writes its logs there
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    # the CLI prints Markdown sections; the script's return value is the JSON line under "### Result"
    sections = run.stdout.split("### ")
    result = next((s for s in sections if s.startswith("Result")), None)
    if result is None:
        sys.exit(f"ui: the browser checks stopped with an error:\n{next((s for s in sections if s.startswith('Error')), run.stdout + run.stderr)}")
    report = json.loads(result.splitlines()[1])
    print(report)
    failed = [line for line in report.splitlines() if line.startswith("FAIL")]
    passed = sum(line.startswith("PASS") for line in report.splitlines())
    assert "Traceback" not in log, log
    if failed:
        sys.exit(f"ui: {len(failed)} failed, {passed} passed")
    print(f"ui: all {passed} checks passed")


if __name__ == "__main__":
    main()
