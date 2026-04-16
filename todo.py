from __future__ import annotations

import json
import time
import platform
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Literal

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Header, Footer, Input, Static, DataTable, Button, Label
from textual.screen import ModalScreen
from textual.binding import Binding


FilterMode = Literal["All", "Active", "Done"]
SortMode = Literal["Created", "Due", "Priority", "Title"]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def now_ts() -> float:
    return time.time()


def fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def parse_due(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.timestamp()
        except ValueError:
            pass
    raise ValueError("Due format: YYYY-MM-DD or YYYY-MM-DD HH:MM")


def fmt_due(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@dataclass
class TodoItem:
    id: str
    title: str
    note: str = ""
    done: bool = False
    created_at: float = 0.0
    due_at: Optional[float] = None
    priority: int = 2  # 1 high, 2 medium, 3 low


class TodoStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: List[TodoItem] = []

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.items = []
            return

        items: List[TodoItem] = []
        for raw in data.get("items", []):
            items.append(
                TodoItem(
                    id=str(raw["id"]),
                    title=str(raw["title"]),
                    note=str(raw.get("note", "")),
                    done=bool(raw.get("done", False)),
                    created_at=float(raw.get("created_at", 0.0)),
                    due_at=raw.get("due_at", None),
                    priority=int(raw.get("priority", 2)),
                )
            )
        self.items = items

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"items": [asdict(x) for x in self.items]}
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert(self, item: TodoItem) -> None:
        for i, it in enumerate(self.items):
            if it.id == item.id:
                self.items[i] = item
                return
        self.items.append(item)

    def delete(self, item_id: str) -> None:
        self.items = [x for x in self.items if x.id != item_id]


class TaskEditor(ModalScreen[Optional[TodoItem]]):
    CSS = """
    TaskEditor {
        align: center middle;
    }
    TaskEditor > Container {
        width: 78;
        max-width: 92%;
        max-height: 90%;
        border: round $surface;
        background: $panel;
        padding: 0 1;
    }
    .row {
        height: auto;
        margin: 0;
    }
    Input {
        width: 1fr;
        margin: 0 0 1 0;
    }
    .buttons {
        height: auto;
        align: right middle;
        margin-top: 0;
    }
    Button {
        margin-left: 1;
    }
    #hint {
        height: auto;
        margin: 0 0 1 0;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, existing: Optional[TodoItem] = None) -> None:
        super().__init__()
        self.existing = existing

    def compose(self) -> ComposeResult:
        title = "Edit task" if self.existing else "Add task"
        with Container():
            yield Static(f"[b]{title}[/b]\n", classes="row")
            yield Label("Title", classes="row")
            yield Input(
                value=(self.existing.title if self.existing else ""),
                id="title",
                placeholder="e.g. Recap NeoGeo caps",
            )
            yield Label("Note", classes="row")
            yield Input(
                value=(self.existing.note if self.existing else ""),
                id="note",
                placeholder="Optional details…",
            )
            yield Label("Due (YYYY-MM-DD or YYYY-MM-DD HH:MM)", classes="row")
            yield Input(
                value=(
                    datetime.fromtimestamp(self.existing.due_at).strftime("%Y-%m-%d %H:%M")
                    if self.existing and self.existing.due_at
                    else ""
                ),
                id="due",
                placeholder="",
            )
            yield Label("Priority (1=High, 2=Med, 3=Low)", classes="row")
            yield Input(
                value=(str(self.existing.priority) if self.existing else "2"),
                id="prio",
                placeholder="2",
            )
            yield Static("[dim]Ctrl+S = Save[/dim]", id="hint", classes="row")
            yield Static("", id="error", classes="row")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Save", variant="success", id="save")

    def on_mount(self) -> None:
        self.query_one("#title", Input).focus()

    def _set_error(self, msg: str) -> None:
        self.query_one("#error", Static).update(f"[red]{msg}[/red]")

    def _submit(self) -> None:
        title_in = self.query_one("#title", Input).value.strip()
        note_in = self.query_one("#note", Input).value.strip()
        due_in = self.query_one("#due", Input).value.strip()
        prio_in = self.query_one("#prio", Input).value.strip()

        if not title_in:
            self._set_error("Title is required.")
            return

        try:
            due_at = parse_due(due_in)
        except Exception:
            self._set_error("Bad due format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM")
            return

        try:
            prio = int(prio_in or "2")
            if prio not in (1, 2, 3):
                raise ValueError()
        except Exception:
            self._set_error("Priority must be 1, 2, or 3.")
            return

        if self.existing:
            item = TodoItem(
                id=self.existing.id,
                title=title_in,
                note=note_in,
                done=self.existing.done,
                created_at=self.existing.created_at,
                due_at=due_at,
                priority=prio,
            )
        else:
            item = TodoItem(
                id=str(int(now_ts() * 1000)),
                title=title_in,
                note=note_in,
                done=False,
                created_at=now_ts(),
                due_at=due_at,
                priority=prio,
            )

        self.dismiss(item)

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        if event.button.id == "save":
            self._submit()

    def key_escape(self) -> None:
        self.dismiss(None)


class ConfirmDelete(ModalScreen[bool]):
    CSS = """
    ConfirmDelete {
        align: center middle;
    }
    ConfirmDelete > Container {
        width: 64;
        max-width: 92%;
        border: round $error;
        background: $panel;
        padding: 1 2;
    }
    .buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    Button { margin-left: 1; }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[b][red]Delete[/red][/b]\n\nDelete:\n• [b]{self.title}[/b]\n")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Delete", id="delete", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "delete":
            self.dismiss(True)

    def key_escape(self) -> None:
        self.dismiss(False)


class DetailPopup(ModalScreen[None]):
    CSS = """
    DetailPopup {
        align: center middle;
    }
    DetailPopup > Container {
        width: 80;
        max-width: 94%;
        border: round $surface;
        background: $panel;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "close_popup", "Close", show=False, priority=True),
        Binding("enter", "close_popup", "Close", show=False, priority=True),
    ]

    def __init__(self, item: TodoItem) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        status = "✅ DONE" if self.item.done else "⏳ ACTIVE"
        pr = {1: "HIGH", 2: "MED", 3: "LOW"}.get(self.item.priority, "MED")
        due = fmt_due(self.item.due_at)
        created = fmt_dt(self.item.created_at)
        note = self.item.note.strip() or "—"
        with Container():
            yield Static(
                f"[b]{self.item.title}[/b]\n"
                f"[dim]{status} • Priority: {pr} • Due: {due} • Created: {created}[/dim]\n\n"
                f"{note}\n\n"
                f"[dim]Press Esc / Enter to close[/dim]"
            )

    def action_close_popup(self) -> None:
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)

    def key_enter(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key in ("enter", "escape"):
            event.stop()
            self.dismiss(None)


class _QuickPrompt(ModalScreen[Optional[str]]):
    CSS = """
    _QuickPrompt {
        align: center middle;
    }
    _QuickPrompt > Container {
        width: 70;
        max-width: 92%;
        border: round $surface;
        background: $panel;
        padding: 1 2;
    }
    .buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    Button { margin-left: 1; }
    """

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self.title = title
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[b]{self.title}[/b]\n")
            yield Input(
                value=self.initial,
                id="value",
                placeholder="Type and hit Save (empty clears)",
            )
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Save", id="save", variant="success")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self.dismiss(self.query_one("#value", Input).value)

    def key_escape(self) -> None:
        self.dismiss(None)

    def key_enter(self) -> None:
        self.dismiss(self.query_one("#value", Input).value)


class TodoTUI(App):
    CSS = """
    #topbar {
        height: auto;
        padding: 0 1;
        border: round $surface;
        background: $panel;
    }
    #stats {
        height: auto;
        padding: 0 1;
    }
    #controls {
        height: auto;
        padding: 0 1;
    }
    #table_wrap {
        height: 1fr;
        border: round $surface;
        background: $panel;
    }
    DataTable {
        height: 1fr;
    }
    """

    TITLE = "todo-tui"
    SUB_TITLE = "llmfit-ish terminal todo"

    BINDINGS = [
        Binding("j,down", "down", "Down", show=False),
        Binding("k,up", "up", "Up", show=False),
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("x", "toggle", "Toggle done"),
        Binding("d", "delete", "Delete"),
        Binding("/", "search", "Search"),
        Binding("f", "filter", "Filter"),
        Binding("s", "sort", "Sort"),
        Binding("t", "theme", "Theme"),
        Binding("enter", "detail", "Detail"),
        Binding("q", "quit", "Quit"),
    ]

    THEMES = ["textual-dark", "textual-light", "monokai", "dracula", "nord", "catppuccin-mocha"]

    def __init__(self) -> None:
        super().__init__()
        base = app_dir()
        self.store = TodoStore(base / "todos.json")
        self.config_path = base / "config.json"

        self.filter_mode: FilterMode = "All"
        self.sort_mode: SortMode = "Created"
        self.query: str = ""
        self.theme_idx: int = 0
        self._row_to_id: List[str] = []

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            theme_idx = int(data.get("theme_idx", 0))
            if 0 <= theme_idx < len(self.THEMES):
                self.theme_idx = theme_idx
        except Exception:
            pass

    def _save_config(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"theme_idx": self.theme_idx}
            self.config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical():
            with Horizontal(id="topbar"):
                yield Static(self._header_text(), id="stats")
                yield Static(self._control_text(), id="controls")

            with Container(id="table_wrap"):
                table = DataTable(id="table")
                table.cursor_type = "row"
                yield table

        yield Footer()

    def on_mount(self) -> None:
        self._load_config()
        self.store.load()
        self._setup_table()
        self._refresh_all()
        self.theme = self.THEMES[self.theme_idx]

    def _setup_table(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns(" ", "Title", "Due", "Pri", "Created")
        try:
            table.fixed_columns = 1
        except Exception:
            pass
        try:
            table.zebra_stripes = True
        except Exception:
            pass

    def _header_text(self) -> str:
        cpu = platform.processor() or "CPU"
        return f"[b]{self.TITLE}[/b]\n[dim]Host: {platform.system()} • {cpu}[/dim]"

    def _control_text(self) -> str:
        return (
            f"[b]Filter[/b]: [cyan]{self.filter_mode}[/cyan]   "
            f"[b]Sort[/b]: [cyan]{self.sort_mode}[/cyan]   "
            f"[b]Query[/b]: [cyan]{self.query or '—'}[/cyan]   "
            f"[b]Theme[/b]: [cyan]{self.THEMES[self.theme_idx]}[/cyan]"
        )

    def _get_selected_id(self) -> Optional[str]:
        table = self.query_one("#table", DataTable)
        if table.row_count == 0:
            return None
        row = getattr(table, "cursor_row", 0)
        if 0 <= row < len(self._row_to_id):
            return self._row_to_id[row]
        return None

    def _safe_set_cursor_row(self, row: int) -> None:
        table = self.query_one("#table", DataTable)
        if table.row_count <= 0:
            return

        row = max(0, min(row, table.row_count - 1))

        if hasattr(table, "move_cursor"):
            try:
                table.move_cursor(row=row, column=0)
                return
            except TypeError:
                try:
                    table.move_cursor(row, 0)
                    return
                except Exception:
                    pass
            except Exception:
                pass

        if hasattr(table, "goto_row"):
            try:
                table.goto_row(row)
                return
            except Exception:
                pass

        if hasattr(table, "cursor_coordinate"):
            try:
                table.cursor_coordinate = (row, 0)
                return
            except Exception:
                pass

    def _filtered_sorted_items(self) -> List[TodoItem]:
        items = list(self.store.items)

        if self.filter_mode == "Active":
            items = [x for x in items if not x.done]
        elif self.filter_mode == "Done":
            items = [x for x in items if x.done]

        q = self.query.strip().lower()
        if q:
            items = [x for x in items if q in x.title.lower() or q in x.note.lower()]

        if self.sort_mode == "Created":
            items.sort(key=lambda x: x.created_at, reverse=True)
        elif self.sort_mode == "Due":
            items.sort(key=lambda x: (x.due_at is None, x.due_at or 0), reverse=False)
        elif self.sort_mode == "Priority":
            items.sort(key=lambda x: (x.priority, x.due_at is None, x.due_at or 0))
        elif self.sort_mode == "Title":
            items.sort(key=lambda x: x.title.lower())

        return items

    def _refresh_table(self) -> None:
        table = self.query_one("#table", DataTable)
        prev_row = getattr(table, "cursor_row", 0)

        table.clear()
        items = self._filtered_sorted_items()
        self._row_to_id = [x.id for x in items]

        for it in items:
            status = "✅" if it.done else "•"
            due = fmt_due(it.due_at)
            pr = {1: "[red]H[/red]", 2: "[yellow]M[/yellow]", 3: "[green]L[/green]"}.get(it.priority, "M")
            created = fmt_dt(it.created_at)

            title = it.title
            if it.done:
                title = f"[dim][strike]{title}[/strike][/dim]"

            table.add_row(status, title, due, pr, created)

        self._safe_set_cursor_row(prev_row)

    def _refresh_bars(self) -> None:
        self.query_one("#stats", Static).update(self._header_text())
        self.query_one("#controls", Static).update(self._control_text())

    def _refresh_all(self) -> None:
        self._refresh_table()
        self._refresh_bars()

    def _on_task_saved(self, item: Optional[TodoItem]) -> None:
        if not item:
            return
        self.store.upsert(item)
        self.store.save()
        self._refresh_all()

    def _on_search_set(self, value: Optional[str]) -> None:
        if value is None:
            return
        self.query = value.strip()
        self._refresh_all()

    def _on_delete_confirmed(self, ok: bool, item_id: str) -> None:
        if not ok:
            return
        self.store.delete(item_id)
        self.store.save()
        self._refresh_all()

    def _open_selected_detail(self) -> None:
        sel = self._get_selected_id()
        if not sel:
            self.bell()
            return
        existing = next((x for x in self.store.items if x.id == sel), None)
        if existing:
            self.push_screen(DetailPopup(existing))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_selected_detail()

    def action_down(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.row_count:
            row = getattr(table, "cursor_row", 0)
            self._safe_set_cursor_row(row + 1)

    def action_up(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.row_count:
            row = getattr(table, "cursor_row", 0)
            self._safe_set_cursor_row(row - 1)

    def action_add(self) -> None:
        self.push_screen(TaskEditor(None), callback=self._on_task_saved)

    def action_edit(self) -> None:
        sel = self._get_selected_id()
        if not sel:
            self.bell()
            return
        existing = next((x for x in self.store.items if x.id == sel), None)
        if not existing:
            self.bell()
            return
        self.push_screen(TaskEditor(existing), callback=self._on_task_saved)

    def action_toggle(self) -> None:
        sel = self._get_selected_id()
        if not sel:
            self.bell()
            return
        for it in self.store.items:
            if it.id == sel:
                it.done = not it.done
                self.store.save()
                self._refresh_all()
                return

    def action_delete(self) -> None:
        sel = self._get_selected_id()
        if not sel:
            self.bell()
            return
        existing = next((x for x in self.store.items if x.id == sel), None)
        if not existing:
            self.bell()
            return
        self.push_screen(
            ConfirmDelete(existing.title),
            callback=lambda ok: self._on_delete_confirmed(bool(ok), existing.id),
        )

    def action_search(self) -> None:
        self.push_screen(_QuickPrompt("Search", self.query), callback=self._on_search_set)

    def action_filter(self) -> None:
        order: List[FilterMode] = ["All", "Active", "Done"]
        self.filter_mode = order[(order.index(self.filter_mode) + 1) % len(order)]
        self._refresh_all()

    def action_sort(self) -> None:
        order: List[SortMode] = ["Created", "Due", "Priority", "Title"]
        self.sort_mode = order[(order.index(self.sort_mode) + 1) % len(order)]
        self._refresh_all()

    def action_theme(self) -> None:
        self.theme_idx = (self.theme_idx + 1) % len(self.THEMES)
        self.theme = self.THEMES[self.theme_idx]
        self._save_config()
        self._refresh_bars()

    def action_detail(self) -> None:
        self._open_selected_detail()


if __name__ == "__main__":
    TodoTUI().run()