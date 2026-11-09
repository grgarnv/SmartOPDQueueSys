"""Browser checks (test_ui.js for the legacy UI, test_ui_react.js for /app/) against throwaway demo servers. Run: python3 app/test_ui.py

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
    failed = run(cli, "test_ui.js", "legacy UI")
    if (HERE.parent / "frontend" / "dist" / "index.html").is_file():
        failed += run(cli, "test_ui_react.js", "React UI")
    else:
        print("ui (React): skipped (frontend not built: cd frontend && npm run build)")
    if failed:
        sys.exit(f"ui: {failed} failed")


def run(cli, name, label):
    """One browser script against its own throwaway demo server. Returns the number of failed checks."""
    proc, base = start_server(f"{TMP}/{name}.db")
    script = Path(TMP) / name
    script.write_text((HERE / name).read_text().replace("__BASE__", base))
    session = ["-s=opd-ui-test"]
    try:
        subprocess.run([cli, *session, "open", "about:blank"], capture_output=True, check=True, timeout=60, cwd=TMP)
        result = subprocess.run([cli, *session, "run-code", f"--filename={script}"], capture_output=True, text=True, timeout=300, cwd=TMP)
    finally:
        subprocess.run([cli, *session, "close"], capture_output=True, timeout=60, cwd=TMP)  # cwd: the CLI writes its logs there
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    # the CLI prints Markdown sections; the script's return value is the JSON line under "### Result"
    sections = result.stdout.split("### ")
    found = next((s for s in sections if s.startswith("Result")), None)
    if found is None:
        sys.exit(f"ui ({label}): the browser checks stopped with an error:\n{next((s for s in sections if s.startswith('Error')), result.stdout + result.stderr)}")
    report = json.loads(found.splitlines()[1])
    print(report)
    failed = [line for line in report.splitlines() if line.startswith("FAIL")]
    passed = sum(line.startswith("PASS") for line in report.splitlines())
    assert "Traceback" not in log, log
    print(f"ui ({label}): {passed} passed, {len(failed)} failed")
    return len(failed)


if __name__ == "__main__":
    main()
