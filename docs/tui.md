# TUI

```
spool path/to/file.jsonl
```

## Layout

- **Search bar** — top, activate with `/`
- **Log view** — main area, scrollable log lines
- **Detail panel** — bottom, shows all fields of the selected line
- **Status bar** — line position, match count, mode, engine indicator (`C` or `py`)

## Keybindings

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `j` / `k` | Cursor down / up |
| `g` / `G` | Jump to top / bottom |
| `PageUp` / `PageDown` | Page scroll |
| `n` / `N` | Next / previous match |
| `e` | Toggle exact mode (show only matching lines) |
| `Enter` | Focus detail panel |
| `y` | Copy current line to clipboard |
| `Y` | Copy key=value from detail panel |
| `Escape` | Return to log view / clear search |
| `1` | Toggle error filter |
| `2` | Toggle warning filter |
| `3` | Toggle info filter |
| `4` | Toggle debug filter |
| `0` | Clear level filter |
| `q` | Quit |

## Search syntax

Searches are entered in the search bar (`/`) and executed on `Enter`. Empty search clears results.

### Basic

| Query | Matches |
|-------|---------|
| `buy_confirmed` | Lines containing the substring |
| `mint=7VwujP*` | Lines where JSON key `mint` glob-matches `7VwujP*` |
| `*timeout*` | Lines matching the glob pattern |

### Combinators

| Query | Meaning |
|-------|---------|
| `buy_confirmed mint=7Vwuj*` | AND — both must match (space-separated) |
| `buy_confirmed OR sell_confirmed` | OR — either matches |
| `error OR warning mint=7Vwuj*` | OR groups, then AND with remaining terms |
| `~debug` | NOT — exclude lines matching `debug` |
| `~mint=7Vwuj*` | NOT — exclude lines where mint matches |

### Anchors

Anchors jump to a position in the file without filtering. Combine with search terms to search + jump.

| Query | Meaning |
|-------|---------|
| `@-30m` | Jump to 30 minutes before end of file |
| `@-2h` | Jump to 2 hours before end |
| `@-5s` | Jump to 5 seconds before end |
| `@-1d` | Jump to 1 day before end |
| `@12:30` | Jump to 12:30 on the last day in the file |
| `@12:30:45` | Jump to 12:30:45 |
| `@2026-03-20T04:50` | Jump to absolute timestamp |
| `error @-1h` | Search for "error" and jump to 1h before end |

### Context vs exact mode

By default, search highlights matching lines in context — you see all lines with matches highlighted. Press `e` to toggle **exact mode**, which hides non-matching lines entirely. `n`/`N` navigate between matches in both modes.

### Level filters

Press `1`-`4` to filter by level (toggles on/off). Level filters combine with search — if you search for `buy_confirmed` and press `1`, you get only error-level buy_confirmed lines.
