from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from darkweb_collector import self_update


if os.name != "nt":
    raise SystemExit("Windows updater checks require Windows")


with tempfile.TemporaryDirectory(prefix="darkweb-update-runtime-") as temporary:
    root = Path(temporary)

    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait(timeout=10)
    assert not self_update._process_running(finished.pid)

    check_script = root / "check-file-hash.ps1"
    check_script.write_text(
        "if (-not (Get-Command Get-FileHash -ErrorAction SilentlyContinue)) { exit 7 }\n",
        encoding="utf-8",
    )
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    previous_module_path = os.environ.get("PSModulePath")
    os.environ["PSModulePath"] = ""
    try:
        with (root / "powershell.log").open("w", encoding="utf-8") as log:
            self_update._run_logged(
                [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(check_script)],
                root,
                log,
                timeout=30,
            )
    finally:
        if previous_module_path is None:
            os.environ.pop("PSModulePath", None)
        else:
            os.environ["PSModulePath"] = previous_module_path

    runtime = root / "darkweb_collector/.runtime/windows"
    runtime.mkdir(parents=True)
    (runtime / "ports.json").write_text(
        json.dumps(
            {
                "api_base_url": "http://127.0.0.1:18101",
                "frontend_url": "http://127.0.0.1:5184",
            }
        ),
        encoding="utf-8-sig",
    )

    class Response:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _maximum: int | None = None) -> bytes:
            return self.payload

    original_urlopen = self_update.urllib.request.urlopen

    def fake_urlopen(url: str, timeout: int = 0):
        del timeout
        if str(url).endswith("/api/health"):
            return Response(b'{"status":"ok","version":"v20990101"}')
        return Response(b'<meta name="darkweb-ui" content="xuanjian-new-ui">')

    self_update.urllib.request.urlopen = fake_urlopen
    try:
        self_update._health_version(root, "v20990101")
    finally:
        self_update.urllib.request.urlopen = original_urlopen


repository_root = Path(__file__).resolve().parents[2]
launcher_source = (
    repository_root / "darkweb_collector/scripts/start_all_services_windows.ps1"
).read_text(encoding="utf-8")
assert 'Import-Module -Name $module' in launcher_source
assert 'Preserving active update controller pid' in launcher_source
assert '[Text.UTF8Encoding]::new($false)' in launcher_source
print("Windows updater runtime regression checks passed.")
