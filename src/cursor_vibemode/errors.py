from __future__ import annotations


class CursorVibemodeError(RuntimeError):
    def __init__(
        self,
        code: str,
        title: str,
        reason: str,
        hint: str = "",
        developer: str = "",
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.title = title
        self.reason = reason
        self.hint = hint
        self.developer = developer


def format_error(error: CursorVibemodeError) -> str:
    lines = [
        f"Ошибка [{error.code}]: {error.title}",
        f"Причина: {error.reason}",
    ]
    if error.hint:
        lines.append(f"Что сделать: {error.hint}")
    if error.developer:
        lines.append(f"Для разработчика: {error.developer}")
    return "\n".join(lines)
