#!/usr/bin/env python3
"""Hot-swap watcher for the banano_kling bot.

Watches project source/config files and restarts the systemd bot service after
the change burst settles.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from watchdog.events import (
    FileClosedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers.polling import PollingObserver as Observer

TRIGGER_TYPES = (FileModifiedEvent, FileCreatedEvent, FileMovedEvent, FileClosedEvent)
WATCH_DIRS = ["bot", "data", "services", "tbank_payment"]
WATCH_ROOT_FILES = {
    ".env",
    "requirements.txt",
    "bot.service",
    "start.sh",
    "stop.sh",
    "restart.sh",
}
WATCH_EXTENSIONS = {".py", ".json", ".env", ".txt", ".service", ".sh"}
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", "logs", "venv"}
PIDFILE = Path("/tmp/banano-kling-watcher.pid")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watcher] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("watcher")


class RestartHandler(FileSystemEventHandler):
    def __init__(self, service: str, debounce: float) -> None:
        self._service = service
        self._debounce = debounce
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or not isinstance(event, TRIGGER_TYPES):
            return

        path = Path(str(event.src_path))
        if any(part in IGNORED_PARTS for part in path.parts):
            return
        if path.name not in WATCH_ROOT_FILES and path.suffix not in WATCH_EXTENSIONS:
            return

        log.info("Changed: %s (%s)", path, event.event_type)
        self._schedule_restart()

    def _schedule_restart(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._restart)
            self._timer.daemon = True
            self._timer.start()

    def _restart(self) -> None:
        log.info("Restarting %s ...", self._service)
        try:
            result = subprocess.run(
                ["systemctl", "restart", self._service],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            log.error("Failed to restart %s: %s", self._service, exc)
            return

        if result.returncode == 0:
            log.info("Restarted %s OK", self._service)
        else:
            stderr = result.stderr.strip() or result.stdout.strip()
            log.error("systemctl restart %s failed: %s", self._service, stderr)


def _acquire_lock() -> None:
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            os.kill(old_pid, signal.SIGTERM)
            log.info("Terminated previous watcher instance (pid=%s)", old_pid)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    PIDFILE.write_text(str(os.getpid()))


def _release_lock() -> None:
    try:
        if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="banano_kling hot-swap watcher")
    parser.add_argument(
        "--service",
        default="bot.service",
        help="systemd service to restart",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="seconds to wait after the last change",
    )
    args = parser.parse_args()

    _acquire_lock()

    root = Path(__file__).resolve().parent.parent
    handler = RestartHandler(service=args.service, debounce=args.debounce)
    observer = Observer()

    watched: list[str] = []
    observer.schedule(handler, str(root), recursive=False)
    watched.append(f"{root}/ (root, non-recursive)")

    for dirname in WATCH_DIRS:
        watch_path = root / dirname
        if watch_path.exists():
            observer.schedule(handler, str(watch_path), recursive=True)
            watched.append(str(watch_path))

    if not watched:
        log.error("No watch targets found under %s", root)
        sys.exit(1)

    log.info("Watching: %s", ", ".join(watched))
    log.info("Service: %s | Debounce: %.1fs", args.service, args.debounce)

    observer.start()
    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        log.info("Interrupted, stopping...")
    finally:
        observer.stop()
        observer.join()
        _release_lock()


if __name__ == "__main__":
    main()
