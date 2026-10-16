"""Start this app, open its page after readiness, stop our child on Ctrl+C."""
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
port = os.getenv("PORT", "8765")
url = f"http://127.0.0.1:{port}"
print("CampusPulse · Google Gemini и Google Calendar\n" + url, flush=True)
process = subprocess.Popen([sys.executable, "-m", "uvicorn", "campuspulse.server:app", "--host", "127.0.0.1", "--port", port, "--no-access-log"], cwd=ROOT)
try:
    for _ in range(80):
        if process.poll() is not None:
            raise SystemExit(process.returncode)
        try:
            with urlopen(url + "/api/health", timeout=0.3) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    break
        except Exception:
            time.sleep(0.25)
    process.wait()
except KeyboardInterrupt:
    pass
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
