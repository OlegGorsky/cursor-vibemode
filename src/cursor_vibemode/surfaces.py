from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .cursor_db import connect, get_value, has_item_table
from .paths import APP_USER_KEY, OPENAI_KEY_STORAGE


GLASS_PREFIXES = ("glass.", "cursor/glass.")


@dataclass(frozen=True)
class CursorSurfaceReport:
    has_editor: bool
    has_agents: bool
    has_settings: bool

    @property
    def names(self) -> list[str]:
        names: list[str] = []
        if self.has_editor:
            names.append("редактор")
        if self.has_agents:
            names.append("агентное окно")
        return names or ["профиль Cursor"]

    @property
    def display(self) -> str:
        if len(self.names) == 1:
            return self.names[0]
        return ", ".join(self.names[:-1]) + " и " + self.names[-1]


def detect_surfaces(db_path: Path) -> CursorSurfaceReport:
    if not db_path.is_file():
        return CursorSurfaceReport(False, False, False)
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            return CursorSurfaceReport(False, False, False)
        has_settings = bool(get_value(conn, APP_USER_KEY) or get_value(conn, OPENAI_KEY_STORAGE))
        has_agents = has_glass_keys(conn)
        has_editor = has_settings or not has_agents
        return CursorSurfaceReport(has_editor, has_agents, has_settings)


def has_glass_keys(conn) -> bool:
    for prefix in GLASS_PREFIXES:
        row = conn.execute(
            "SELECT key FROM ItemTable WHERE key LIKE ? LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        if row:
            return True
    return False
