# spool

Structured logging and log exploration. Write process-safe JSONL, then search and navigate it fast.

The TUI is built for investigating, not querying. Search for a thing, see it in context. Jump to an approximate time and scroll around. No need to specify exact ranges or know what you're looking for upfront — land in the right neighbourhood and follow the thread.

## Install

```
pip install git+https://github.com/bm13563/spool.git
```

For native C-accelerated search (optional):

```
make
```

## Writer

```python
from spool.writer import get_logger

log = get_logger("myapp")
log.info("server_started", port=8080)
log.warning("slow_query", duration_ms=1200)
log.error("connection_lost", peer="10.0.0.1")
```

Writes JSONL to `~/.local/share/tdl-crypto/logs/{name}.jsonl`. Each line is a single atomic `os.write()` with `O_APPEND` — safe across multiple processes, no locking needed.

## TUI

```
spool path/to/file.jsonl
```

Search for a substring, a key=value, a glob — results highlight in place so you see what happened before and after. Press `e` to collapse to just matches. Use `@-30m` to jump to 30 minutes before the end. Combine: `buy_confirmed @-1h` searches and jumps.

Full search syntax and keybindings in [docs/tui.md](docs/tui.md).

## Reader API

The TUI is built on a reader API you can use directly for programmatic access — useful for scripting or AI-driven log analysis.

```python
from spool.reader import LogIndex

idx = LogIndex("path/to/file.jsonl")
matches = idx.search_kv("mint", "7Vwuj*")
for i in matches:
    print(idx.get_line(i))
idx.close()
```

Full API in [docs/reader.md](docs/reader.md).

## Structure

- **`spool.writer`** — Write logs. Process-safe, no deps beyond orjson. [docs/writer.md](docs/writer.md)
- **`spool.reader`** — Read and search JSONL. mmap-backed, optional C acceleration. [docs/reader.md](docs/reader.md)
- **`spool.tui`** — Terminal UI. Built on Textual, consumes the reader API. [docs/tui.md](docs/tui.md)
