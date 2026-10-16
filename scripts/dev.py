from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
CLIENT_DIR = ROOT / "client"


def pump(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{name}] {line.rstrip()}")


def main() -> int:
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(SERVER_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    frontend = None
    if (CLIENT_DIR / "node_modules").exists():
        frontend = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(CLIENT_DIR),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        print("[client] node_modules не найден — запустите npm install в client/")

    threads = [threading.Thread(target=pump, args=("server", backend), daemon=True)]
    if frontend is not None:
        threads.append(threading.Thread(target=pump, args=("client", frontend), daemon=True))
    for t in threads:
        t.start()

    print("\nОткройте http://127.0.0.1:5173 (dev) или http://127.0.0.1:8000 (prod-сборка)\n")

    try:
        backend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (frontend, backend):
            if proc and proc.poll() is None:
                proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
