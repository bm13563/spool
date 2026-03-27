# Reader API

The reader provides `LogIndex`, an mmap-backed JSONL index with optional C-accelerated search. It never loads the full file into memory.

## LogIndex

```python
from spool.reader import LogIndex

idx = LogIndex("path/to/file.jsonl")
```

### Properties

- `idx.line_count` — Total number of lines
- `idx.using_native` — Whether the C library is loaded

### Methods

- `idx.get_line(i)` — Get line `i` as a string
- `idx.search_substr(pattern)` — Lines containing substring
- `idx.search_wild(pattern)` — Lines matching glob pattern (`*`, `?`)
- `idx.search_kv(key, val_pattern)` — Lines where JSON key matches glob value
- `idx.search_level(level)` — Lines with `"level":"<level>"`
- `idx.search_time(start_ts, end_ts)` — Lines within timestamp range (binary search for start)
- `idx.find_line_at_time(timestamp)` — Binary search for line index at timestamp
- `idx.close()` — Release mmap and file handle

All search methods return a list of integer line indices, sorted ascending.

## Native acceleration

Build with `make` from the repo root. The C library (`liblogindex.so`) uses mmap + memmem for search, typically 5-10x faster than the Python fallback on large files. If the `.so` isn't found, it falls back to pure Python transparently.

## Search patterns

`search_kv` accepts glob patterns for the value:

```python
idx.search_kv("mint", "7Vwuj*")     # prefix match
idx.search_kv("wallet", "5CDX*")    # prefix match
idx.search_kv("event", "buy_*")     # event prefix
idx.search_kv("level", "")          # any value (key exists)
```

`search_time` uses ISO 8601 timestamps and binary-searches for the start position:

```python
idx.search_time("2026-03-20T04:50", "2026-03-20T05:00")
idx.search_time("2026-03-20", "")  # everything from this date onward
```
