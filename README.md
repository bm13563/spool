# spool

Process-safe structured logging with a fast TUI reader. Writes JSONL via atomic `O_APPEND`, reads via mmap with optional C-accelerated search.

## Structure

- **`spool.writer`** — Write logs. Process-safe, zero dependencies beyond orjson.
- **`spool.reader`** — Read and search JSONL files. mmap-backed with optional native C acceleration.
- **`spool.tui`** — Terminal UI for exploring logs. Built on Textual, consumes the reader API.

## Install

```
pip install git+https://github.com/bm13563/spool.git
```

For native C acceleration (optional):

```
make
```

## Writer

```python
from spool.writer import get_logger

log = get_logger("myapp")
log.info("server_started", port=8080)
log.debug("request", method="GET", path="/health")
log.warning("slow_query", duration_ms=1200)
log.error("connection_lost", peer="10.0.0.1")
```

Logs write to `~/.local/share/tdl-crypto/logs/{name}.jsonl`. Each line is a single atomic `write()` — safe across multiple processes writing to the same file.

## Reader

```python
from spool.reader import LogIndex

idx = LogIndex("path/to/file.jsonl")
matches = idx.search_substr("error")
matches = idx.search_kv("mint", "7Vwuj*")
matches = idx.search_level("warning")
matches = idx.search_time("2026-03-20T04:50", "2026-03-20T05:00")

for i in matches:
    print(idx.get_line(i))

idx.close()
```

## TUI

```
spool path/to/file.jsonl
```

Keybindings: `/` search, `n`/`N` next/prev match, `e` toggle exact mode, `1-4` filter by level, `j`/`k` navigate, `y` copy line, `q` quit.
