from __future__ import annotations

import bisect
import re
import subprocess
from datetime import datetime, timedelta

import orjson
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static
from textual import work

from spool.reader import LogIndex

def _copy_to_clipboard(text):
    for cmd in (['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
        try:
            subprocess.run(cmd, input=text.encode(), check=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return False


LEVEL_STYLES = {
    "error": "bold red",
    "warning": "bold yellow",
    "info": "bold green",
    "debug": "dim",
}

_RELATIVE_RE = re.compile(r"^-(\d+)([smhd])$")
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$")


def _resolve_time(spec, last_ts):
    spec = spec.strip()
    if not spec or not last_ts:
        return spec

    m = _RELATIVE_RE.match(spec)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        delta = {"s": timedelta(seconds=amount), "m": timedelta(minutes=amount),
                 "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
        ref = datetime.fromisoformat(last_ts.rstrip("Z"))
        return (ref - delta).strftime("%Y-%m-%dT%H:%M:%S")

    if _TIME_ONLY_RE.match(spec):
        return f"{last_ts[:10]}T{spec}"

    return spec


def _parse_single(query):
    query = query.strip()
    if not query:
        return "none", {}, False

    negate = query.startswith("~")
    if negate:
        query = query[1:]

    if "=" in query:
        eq_pos = query.index("=")
        left = query[:eq_pos]
        if left.isidentifier():
            return "kv", {"key": left, "value": query[eq_pos + 1:]}, negate

    if "*" in query or "?" in query:
        return "wildcard", {"pattern": query}, negate

    return "substring", {"pattern": query}, negate


_ANCHOR_RE = re.compile(r"\s*@(\S+)\s*")


def parse_search(query):
    query = query.strip()
    if not query:
        return [], None

    anchor = None
    m = _ANCHOR_RE.search(query)
    if m:
        anchor = m.group(1)
        query = (query[:m.start()] + query[m.end():]).strip()

    if not query:
        return [], anchor

    or_groups = re.split(r"\s+OR\s+", query)
    parsed = []
    for group in or_groups:
        group = re.sub(r"\s+AND\s+", " ", group)
        tokens = group.split()
        parsed.append([_parse_single(t) for t in tokens])
    return parsed, anchor


def _extract_highlight_terms(groups):
    terms = []
    for group in groups:
        for mode, args, neg in group:
            if neg:
                continue
            if mode == "substring":
                terms.append(args["pattern"])
            elif mode == "kv":
                val = args["value"].replace("*", "").replace("?", "")
                if val:
                    terms.append(val)
                terms.append(args["key"])
            elif mode == "wildcard":
                clean = args["pattern"].replace("*", "").replace("?", "")
                if clean:
                    terms.append(clean)
    return terms


class LogView(Widget, can_focus=True):
    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "go_top", "Top", show=False),
        Binding("end", "go_bottom", "Bottom", show=False),
        Binding("g", "go_top", "Top", show=False),
        Binding("G", "go_bottom", "Bottom", show=False),
        Binding("y", "yank_line", "Copy", show=False),
        Binding("enter", "to_detail", "Detail", show=False),
    ]

    offset = reactive(0)
    cursor = reactive(0)

    class CursorMoved(Message):
        def __init__(self, file_line: int):
            self.file_line = file_line
            super().__init__()

    def __init__(self, index: LogIndex, **kwargs):
        super().__init__(**kwargs)
        self.index = index
        self.total_lines = index.line_count
        self.matches = []
        self.match_set = set()
        self.exact_mode = False
        self._parse_cache = {}
        self.highlight_terms = []

    @property
    def total_visible(self):
        if self.exact_mode and self.matches:
            return len(self.matches)
        return self.total_lines

    def file_line_at(self, pos):
        if self.exact_mode and self.matches:
            if 0 <= pos < len(self.matches):
                return self.matches[pos]
            return 0
        return pos

    @property
    def current_file_line(self):
        return self.file_line_at(self.cursor)

    def set_matches(self, matches):
        self.matches = matches
        self.match_set = set(matches)
        if matches:
            if self.exact_mode:
                self.cursor = 0
                self.offset = 0
            else:
                self.cursor = matches[0]
                self._ensure_visible()
        self.refresh()

    def clear_matches(self):
        self.matches = []
        self.match_set = set()
        self.highlight_terms = []
        self.refresh()

    def toggle_exact(self):
        if self.exact_mode and self.matches:
            file_line = self.matches[self.cursor] if self.cursor < len(self.matches) else 0
            self.exact_mode = False
            self.cursor = file_line
            self._ensure_visible()
        elif not self.exact_mode and self.matches:
            cur_file = self.current_file_line
            self.exact_mode = True
            idx = bisect.bisect_left(self.matches, cur_file)
            if idx >= len(self.matches):
                idx = len(self.matches) - 1
            self.cursor = idx
            self.offset = max(0, idx - self.content_size.height // 2)
        else:
            self.exact_mode = not self.exact_mode
            self.cursor = min(self.cursor, self.total_visible - 1)
            self._ensure_visible()
        self.refresh()

    def _ensure_visible(self):
        height = self.content_size.height
        if height <= 0:
            return
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + height:
            self.offset = self.cursor - height + 1
        self.offset = max(0, min(self.offset, self.total_visible - height))

    def action_cursor_up(self):
        if self.cursor > 0:
            self.cursor -= 1
            self._ensure_visible()
            self.post_message(self.CursorMoved(self.current_file_line))
            self.refresh()

    def action_cursor_down(self):
        if self.cursor < self.total_visible - 1:
            self.cursor += 1
            self._ensure_visible()
            self.post_message(self.CursorMoved(self.current_file_line))
            self.refresh()

    def action_page_up(self):
        page = max(1, self.content_size.height - 2)
        self.cursor = max(0, self.cursor - page)
        self._ensure_visible()
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def action_page_down(self):
        page = max(1, self.content_size.height - 2)
        self.cursor = min(self.total_visible - 1, self.cursor + page)
        self._ensure_visible()
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def action_go_top(self):
        self.cursor = 0
        self.offset = 0
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def action_go_bottom(self):
        self.cursor = self.total_visible - 1
        self._ensure_visible()
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def next_match(self):
        if not self.matches:
            return
        if self.exact_mode:
            self.action_cursor_down()
            return
        cur = self.cursor
        idx = bisect.bisect_right(self.matches, cur)
        if idx >= len(self.matches):
            idx = 0
        self.cursor = self.matches[idx]
        self._ensure_visible()
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def prev_match(self):
        if not self.matches:
            return
        if self.exact_mode:
            self.action_cursor_up()
            return
        cur = self.cursor
        idx = bisect.bisect_left(self.matches, cur) - 1
        if idx < 0:
            idx = len(self.matches) - 1
        self.cursor = self.matches[idx]
        self._ensure_visible()
        self.post_message(self.CursorMoved(self.current_file_line))
        self.refresh()

    def _parse_line(self, file_idx):
        if file_idx in self._parse_cache:
            return self._parse_cache[file_idx]
        raw = self.index.get_line(file_idx)
        try:
            data = orjson.loads(raw)
        except Exception:
            data = {"_raw": raw}
        if len(self._parse_cache) > 5000:
            to_remove = list(self._parse_cache.keys())[:2500]
            for k in to_remove:
                del self._parse_cache[k]
        self._parse_cache[file_idx] = data
        return data

    def _format_line(self, file_idx, width):
        data = self._parse_line(file_idx)
        ts = data.get("timestamp", "")
        level = data.get("level", "")
        event = data.get("event", "")

        ts_short = ts[11:23] if len(ts) > 23 else ts

        text = Text()
        text.append(f"{ts_short:12s} ", style="dim")
        text.append(f"{level:8s} ", style=LEVEL_STYLES.get(level, ""))
        text.append(f"{event:30s} ", style="bold")

        extras = {k: v for k, v in data.items()
                  if k not in ("timestamp", "level", "event")}
        for k, v in extras.items():
            text.append(str(k), style="cyan")
            text.append("=")
            text.append(str(v), style="magenta")
            text.append(" ")

        text.truncate(width)
        remaining = width - text.cell_len
        if remaining > 0:
            text.append(" " * remaining)

        if self.highlight_terms:
            plain = text.plain
            lower = plain.lower()
            for term in self.highlight_terms:
                tl = term.lower()
                start = 0
                while True:
                    idx = lower.find(tl, start)
                    if idx == -1:
                        break
                    text.stylize("bold yellow on #2a2a00", idx, idx + len(tl))
                    start = idx + len(tl)

        return text

    def render(self):
        height = self.content_size.height
        width = self.content_size.width
        if height <= 0 or width <= 0:
            return Text("")

        output = Text()
        for i in range(height):
            pos = self.offset + i
            if pos >= self.total_visible:
                output.append(" " * width)
                if i < height - 1:
                    output.append("\n")
                continue

            file_idx = self.file_line_at(pos)
            line = self._format_line(file_idx, width)

            is_match = file_idx in self.match_set
            if self.match_set and not self.exact_mode:
                if is_match:
                    line.stylize("on #1a2a1a")
                else:
                    line.stylize("dim")
            if pos == self.cursor:
                if self.exact_mode:
                    line.stylize("bold on #003355")
                else:
                    line.stylize("reverse")

            output.append_text(line)
            if i < height - 1:
                output.append("\n")

        return output

    def action_yank_line(self):
        raw = self.index.get_line(self.current_file_line)
        if _copy_to_clipboard(raw):
            self.app.notify("Copied line", timeout=1)

    def action_to_detail(self):
        self.app.query_one("#detail", DetailPanel).focus()


class DetailPanel(Widget, can_focus=True):
    DEFAULT_CSS = """
    DetailPanel {
        height: 8;
        border-top: solid #444444;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("y", "copy_value", "Copy val", show=False),
        Binding("enter", "copy_value", show=False),
        Binding("Y", "copy_kv", "Copy k=v", show=False),
    ]

    cursor = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data = {}
        self._keys = []

    def update_line(self, data):
        self._data = data
        self._keys = list(data.keys())
        self.cursor = min(self.cursor, max(0, len(self._keys) - 1))
        self.refresh()

    def render(self):
        width = self.content_size.width
        height = self.content_size.height
        if not self._keys or width <= 0 or height <= 0:
            return Text("")

        max_key = max(len(str(k)) for k in self._keys)
        output = Text()
        for i, key in enumerate(self._keys):
            if i >= height:
                break
            line = Text()
            line.append(f"  {str(key):<{max_key + 2}}", style="cyan bold")
            line.append(str(self._data[key]), style="white")
            line.truncate(width)
            remaining = width - line.cell_len
            if remaining > 0:
                line.append(" " * remaining)
            if i == self.cursor and self.has_focus:
                line.stylize("reverse")
            output.append_text(line)
            if i < min(len(self._keys), height) - 1:
                output.append("\n")
        return output

    def action_cursor_up(self):
        if self.cursor > 0:
            self.cursor -= 1
            self.refresh()

    def action_cursor_down(self):
        if self.cursor < len(self._keys) - 1:
            self.cursor += 1
            self.refresh()

    def action_copy_value(self):
        if self._keys and 0 <= self.cursor < len(self._keys):
            val = str(self._data[self._keys[self.cursor]])
            if _copy_to_clipboard(val):
                self.app.notify(f"Copied: {val[:60]}", timeout=1)

    def action_copy_kv(self):
        if self._keys and 0 <= self.cursor < len(self._keys):
            key = self._keys[self.cursor]
            text = f"{key}={self._data[key]}"
            if _copy_to_clipboard(text):
                self.app.notify(f"Copied: {text[:60]}", timeout=1)


class SearchInput(Input):
    BINDINGS = [
        Binding("ctrl+a", "select_all", "Select All", show=False),
    ]


class SearchBar(Horizontal):
    DEFAULT_CSS = """
    SearchBar {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    SearchBar Label {
        padding: 1 1 0 0;
        width: auto;
    }
    SearchBar Input {
        width: 1fr;
    }
    SearchBar #mode-label {
        width: auto;
        padding: 1 1 0 1;
        color: #888888;
    }
    SearchBar #level-label {
        width: auto;
        padding: 1 1 0 0;
        color: #888888;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(" /", id="search-icon")
        yield SearchInput(placeholder="text | key=val | *wild* | AND / OR | ~exclude | @anchor", id="search-input")
        yield Label("[Context]", id="mode-label")
        yield Label("[All]", id="level-label")


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #1a1a2e;
        color: #888888;
        padding: 0 1;
    }
    """

    def set_status(self, line, total, match_count, match_pos, exact, level,
                   native, filename):
        parts = []
        parts.append(f"Line {line + 1}/{total}")
        if match_count > 0:
            parts.append(f"Match {match_pos}/{match_count}")
        if exact:
            parts.append("EXACT")
        if level:
            parts.append(f"Level:{level}")
        parts.append(f"[{'C' if native else 'py'}]")
        parts.append(filename)
        self.update(" | ".join(parts))


class SpoolApp(App):
    CSS = """
    Screen {
        background: #0f0f1a;
    }
    #log-view {
        height: 1fr;
        border-top: solid #444444;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "focus_search", "Search", key_display="/"),
        Binding("n", "next_match", "Next"),
        Binding("N", "prev_match", "Prev", key_display="N"),
        Binding("e", "toggle_exact", "Exact"),
        Binding("1", "level_error", "Errors", show=False),
        Binding("2", "level_warning", "Warnings", show=False),
        Binding("3", "level_info", "Info", show=False),
        Binding("4", "level_debug", "Debug", show=False),
        Binding("0", "level_all", "All Levels", show=False),
        Binding("escape", "escape", "Back", show=False),
    ]

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.log_index = LogIndex(file_path)
        self.current_level = None  # type: Optional[str]
        self._search_query = ""
        self._match_cursor_idx = 0

    def compose(self) -> ComposeResult:
        yield SearchBar()
        yield LogView(self.log_index, id="log-view")
        yield DetailPanel(id="detail")
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self):
        log_view = self.query_one("#log-view", LogView)
        if log_view.total_lines > 0:
            data = log_view._parse_line(0)
            self.query_one("#detail", DetailPanel).update_line(data)
        self._update_status()
        self.query_one("#log-view").focus()

    def _update_status(self):
        lv = self.query_one("#log-view", LogView)
        status = self.query_one("#status", StatusBar)

        match_pos = 0
        if lv.matches:
            cur_file = lv.current_file_line
            idx = bisect.bisect_left(lv.matches, cur_file)
            if idx < len(lv.matches) and lv.matches[idx] == cur_file:
                match_pos = idx + 1

        status.set_status(
            line=lv.current_file_line,
            total=lv.total_lines,
            match_count=len(lv.matches),
            match_pos=match_pos,
            exact=lv.exact_mode,
            level=self.current_level,
            native=self.log_index.using_native,
            filename=self.file_path.split("/")[-1] if "/" in self.file_path else self.file_path,
        )

    def on_log_view_cursor_moved(self, event: LogView.CursorMoved):
        lv = self.query_one("#log-view", LogView)
        data = lv._parse_line(event.file_line)
        self.query_one("#detail", DetailPanel).update_line(data)
        self._update_status()

    def _last_ts(self):
        n = self.log_index.line_count
        if n == 0:
            return ""
        try:
            return orjson.loads(self.log_index.get_line(n - 1)).get("timestamp", "")
        except Exception:
            return ""

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            query = event.value.strip()
            if not query:
                lv = self.query_one("#log-view", LogView)
                lv.clear_matches()
                self._search_query = ""
                self._update_status()
                lv.focus()
                return
            self._search_query = query
            self._run_search(query)
            self.query_one("#log-view").focus()

    def _exec_single(self, mode, args):
        idx = self.log_index
        if mode == "substring":
            return idx.search_substr(args["pattern"])
        if mode == "wildcard":
            return idx.search_wild(args["pattern"])
        if mode == "kv":
            return idx.search_kv(args["key"], args["value"])
        return []

    @work(thread=True, exclusive=True, group="search")
    def _run_search(self, query):
        groups, anchor = parse_search(query)

        anchor_line = None
        if anchor:
            last = self._last_ts()
            resolved = _resolve_time(anchor, last)
            anchor_line = self.log_index.find_line_at_time(resolved)

        if not groups:
            self.call_from_thread(self._apply_anchor_only, anchor_line)
            return

        all_results = set()
        for terms in groups:
            pos = [set(self._exec_single(m, a)) for m, a, neg in terms
                   if m != "none" and not neg]
            neg = [set(self._exec_single(m, a)) for m, a, neg in terms
                   if m != "none" and neg]
            if pos:
                group_result = pos[0]
                for s in pos[1:]:
                    group_result &= s
            elif neg:
                group_result = set(range(self.log_index.line_count))
            else:
                continue
            for s in neg:
                group_result -= s
            all_results |= group_result

        if self.current_level:
            level_set = set(self.log_index.search_level(self.current_level))
            all_results &= level_set

        highlights = _extract_highlight_terms(groups)
        self.call_from_thread(self._apply_results, sorted(all_results), anchor_line, highlights)

    def _jump_to_anchor(self, lv, anchor_line):
        if lv.matches:
            idx = bisect.bisect_left(lv.matches, anchor_line)
            if idx >= len(lv.matches):
                idx = len(lv.matches) - 1
            elif idx > 0:
                if abs(lv.matches[idx - 1] - anchor_line) < abs(lv.matches[idx] - anchor_line):
                    idx -= 1
            if lv.exact_mode:
                lv.cursor = idx
            else:
                lv.cursor = lv.matches[idx]
        else:
            lv.cursor = min(anchor_line, lv.total_visible - 1)
        lv._ensure_visible()
        lv.post_message(lv.CursorMoved(lv.current_file_line))
        lv.refresh()

    def _apply_anchor_only(self, anchor_line):
        lv = self.query_one("#log-view", LogView)
        if anchor_line is not None:
            self._jump_to_anchor(lv, anchor_line)
        self._update_status()

    def _apply_results(self, results, anchor_line=None, highlights=None):
        lv = self.query_one("#log-view", LogView)
        lv.highlight_terms = highlights or []
        lv.set_matches(results)
        if anchor_line is not None:
            self._jump_to_anchor(lv, anchor_line)
        self._update_status()
        mode_label = self.query_one("#mode-label", Label)
        mode_label.update(
            f"[{'Exact' if lv.exact_mode else 'Context'}] {len(results)} matches"
        )

    def action_focus_search(self):
        self.query_one("#search-input", Input).focus()

    def action_next_match(self):
        self.query_one("#log-view", LogView).next_match()

    def action_prev_match(self):
        self.query_one("#log-view", LogView).prev_match()

    def action_toggle_exact(self):
        lv = self.query_one("#log-view", LogView)
        lv.toggle_exact()
        mode_label = self.query_one("#mode-label", Label)
        n = len(lv.matches) if lv.matches else 0
        mode_label.update(
            f"[{'Exact' if lv.exact_mode else 'Context'}] {n} matches"
        )
        self._update_status()

    def _apply_level_filter(self, level):
        self.current_level = level
        level_label = self.query_one("#level-label", Label)
        level_label.update(f"[{level or 'All'}]")
        if self._search_query:
            self._run_search(self._search_query)
        elif level:
            self._run_level_only(level)
        else:
            lv = self.query_one("#log-view", LogView)
            lv.clear_matches()
            self._update_status()

    @work(thread=True, exclusive=True, group="search")
    def _run_level_only(self, level):
        results = self.log_index.search_level(level)
        self.call_from_thread(self._apply_results, results)

    def action_level_error(self):
        self._apply_level_filter(
            None if self.current_level == "error" else "error")

    def action_level_warning(self):
        self._apply_level_filter(
            None if self.current_level == "warning" else "warning")

    def action_level_info(self):
        self._apply_level_filter(
            None if self.current_level == "info" else "info")

    def action_level_debug(self):
        self._apply_level_filter(
            None if self.current_level == "debug" else "debug")

    def action_level_all(self):
        self._apply_level_filter(None)

    def action_escape(self):
        focused = self.focused
        lv = self.query_one("#log-view", LogView)
        if focused is not lv:
            lv.focus()
        else:
            lv.clear_matches()
            self._search_query = ""
            self.current_level = None
            self.query_one("#mode-label", Label).update("[Context]")
            self.query_one("#level-label", Label).update("[All]")
            self._update_status()

    def on_unmount(self):
        self.log_index.close()
