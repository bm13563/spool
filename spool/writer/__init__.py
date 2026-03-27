import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import orjson

LOG_DIR = Path.home() / ".local" / "share" / "tdl-crypto" / "logs"

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
LEVEL_COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[32m", "debug": DIM}
CYAN = "\033[36m"
MAGENTA = "\033[35m"


class Logger:
    __slots__ = ("_name", "_level", "_fd")

    def __init__(self, name, level, fd):
        self._name = name
        self._level = level
        self._fd = fd

    def _emit(self, level, event, kw):
        if LEVELS[level] < self._level:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        record = {"timestamp": ts, "level": level, "event": event}
        record.update(kw)
        line = orjson.dumps(record, option=orjson.OPT_SERIALIZE_NUMPY)
        os.write(self._fd, line + b"\n")
        kv = " ".join(f"{CYAN}{k}{RESET}={MAGENTA}{v}{RESET}" for k, v in kw.items())
        lc = LEVEL_COLORS.get(level, "")
        console = f"{DIM}{ts}{RESET} [{lc}{BOLD}{level:8s}{RESET}] {BOLD}{event:30s}{RESET} {kv}\n"
        sys.stderr.write(console)

    def debug(self, event, **kw):
        if self._level > 10:
            return
        self._emit("debug", event, kw)

    def info(self, event, **kw):
        self._emit("info", event, kw)

    def warning(self, event, **kw):
        self._emit("warning", event, kw)

    def error(self, event, **kw):
        self._emit("error", event, kw)


def get_logger(name, level=20):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{name}.jsonl"
    fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    return Logger(name, level, fd)


def list_logs():
    if not LOG_DIR.exists():
        print(f"No log directory: {LOG_DIR}")
        return
    files = sorted(LOG_DIR.glob("*.jsonl"))
    if not files:
        print("No log files found")
        return
    for f in files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.stem:30s} {size_mb:8.1f} MB  {f}")
