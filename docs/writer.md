# Writer API

The writer provides process-safe structured logging to JSONL files.

## get_logger

```python
from spool.writer import get_logger

log = get_logger("myapp")           # INFO level (default)
log = get_logger("myapp", level=10) # DEBUG level
```

Levels: `debug=10`, `info=20`, `warning=30`, `error=40`.

Each logger opens a file descriptor with `O_WRONLY | O_CREAT | O_APPEND`. Writes are atomic up to `PIPE_BUF` (4096 bytes on Linux) — multiple processes can safely write to the same file with no locking.

## Logger methods

```python
log.info("event_name", key1=val1, key2=val2)
log.debug("event_name", key1=val1)
log.warning("event_name", key1=val1)
log.error("event_name", key1=val1)
```

Each call writes one JSON line to the file and one ANSI-colored line to stderr.

The `debug()` method short-circuits before touching kwargs if the logger level is above DEBUG — no processing overhead for filtered messages.

## Output format

File (JSONL):
```json
{"timestamp":"2026-03-20T04:50:12.123456Z","level":"info","event":"server_started","port":8080}
```

Console (stderr): ANSI-colored with timestamp, level, event, and key=value pairs.

## Log directory

Logs write to `~/.local/share/tdl-crypto/logs/{name}.jsonl`.

## list_logs

```python
from spool.writer import list_logs
list_logs()
```

Prints all `.jsonl` files in the log directory with sizes.
