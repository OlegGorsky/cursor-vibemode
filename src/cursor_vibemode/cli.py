from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapter_server import run as run_adapter
from .cursor_app import inspect_cursor_app
from .cursor_db import (
    read_status,
    remove_openai_key,
    set_openai_enabled,
)
from .errors import CursorVibemodeError, format_error
from .keys import remove_local_key
from .operations import setup_cursor, verify_api, watch_openai_key
from .paths import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    candidate_db_paths,
    cursor_processes,
    find_cursor_db,
    local_auth_path,
)
from .surfaces import detect_surfaces
from .url_safety import host_warnings, status_host_warnings


def require_db(path: str | None) -> Path:
    db_path = find_cursor_db(path)
    if db_path:
        return db_path
    checked = "\n".join(f"  - {p}" for p in candidate_db_paths())
    if path:
        checked = f"  - {Path(path).expanduser()}"
    raise CursorVibemodeError(
        "CURSOR_DB_NOT_FOUND",
        "профиль Cursor не найден",
        "Cursor еще не создал локальную базу настроек или путь указан неверно.",
        "открой Cursor хотя бы один раз, полностью закрой его и повтори запуск.",
        f"Проверенные пути:\n{checked}",
    )


def ensure_cursor_closed(force: bool) -> None:
    running = cursor_processes()
    if running and not force:
        joined = ", ".join(running)
        raise CursorVibemodeError(
            "CURSOR_IS_RUNNING",
            "Cursor сейчас открыт",
            "База настроек может быть заблокирована или перезаписана самим Cursor.",
            "полностью закрой Cursor и повтори запуск.",
            f"Процессы: {joined}",
        )


def print_status(db_path: Path) -> int:
    status = read_status(db_path)
    surfaces = detect_surfaces(db_path)
    ready = bool(status.has_key and status.use_openai_key and status.base_url)
    print("Статус Cursor Vibemode")
    print(f"Подключение: {'включено' if ready else 'не завершено'}")
    print(f"Подключено для: {surfaces.display}")
    print(f"Моделей подключено: {len(status.registered_models)}")
    if status.composer_model:
        print(f"Основная модель: {status.composer_model}")
    for warning in status_host_warnings(status.base_url):
        if status.base_url:
            print(f"Предупреждение: {warning}")
    return 0 if status.has_item_table else 2


def command_status(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    return print_status(db_path)


def command_doctor(args: argparse.Namespace) -> int:
    db_path = find_cursor_db(args.db)
    app = inspect_cursor_app(args.app_root)
    print("Диагностика Cursor Vibemode")
    print(f"Процессы Cursor: {', '.join(cursor_processes()) or 'не найдены'}")
    print(f"Локальный режим Cursor: {app.display}")
    if db_path:
        code = print_status(db_path)
        print("")
        print("Для разработчика:")
        print(f"- база Cursor: {db_path}")
        print(f"- приложение Cursor: {app.app_root or 'не найдено'}")
        print(f"- приложение доступно для патча: {'да' if app.writable else 'нет'}")
        print(f"- локальное хранилище ключа: {local_auth_path()}")
        return code
    print("Подключение: не завершено")
    print("Причина: профиль Cursor не найден")
    print("")
    print("Для разработчика:")
    for path in candidate_db_paths():
        print(f"- {path}: {'найден' if path.is_file() else 'нет'}")
    return 2


def command_setup(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    return setup_cursor(args, db_path=db_path, title="setup")


def command_repair(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    return setup_cursor(args, db_path=db_path, title="repaired")


def command_verify(args: argparse.Namespace) -> int:
    db_path = find_cursor_db(args.db)
    return verify_api(args, db_path)


def command_enable(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = set_openai_enabled(db_path, True, backup=not args.no_backup)
    print("Vibemode включен для Cursor.")
    if backups:
        print("Резервная копия: создана")
    return 0


def command_disable(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = set_openai_enabled(db_path, False, backup=not args.no_backup)
    print("Vibemode выключен. Ключ и модели сохранены.")
    if backups:
        print("Резервная копия: создана")
    return 0


def command_toggle(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    status = read_status(db_path)
    enabled = not bool(status.use_openai_key)
    backups = set_openai_enabled(db_path, enabled, backup=not args.no_backup)
    print(f"Vibemode {'включен' if enabled else 'выключен'} для Cursor.")
    if backups:
        print("Резервная копия: создана")
    return 0


def command_watch(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    return watch_openai_key(args, db_path)


def command_remove(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = remove_openai_key(db_path, backup=not args.no_backup)
    removed_local = remove_local_key() if args.forget_key else False
    print("Vibemode удален из Cursor.")
    print(f"Локальный ключ: {'удален' if removed_local else 'не менялся'}")
    if backups:
        print("Резервная копия: создана")
    return 0


def add_common_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="путь к профилю Cursor, если автоопределение не сработало")


def add_app_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-root", help="путь к resources/app Cursor, если автоопределение не сработало")


def add_write_safety_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force", action="store_true", help="записать настройки, даже если Cursor открыт")
    parser.add_argument("--no-backup", action="store_true", help="не создавать резервную копию")


def add_setup_args(parser: argparse.ArgumentParser) -> None:
    add_common_db_args(parser)
    add_app_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="адрес Vibemode API")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="основная модель")
    parser.add_argument(
        "--models",
        help="auto, builtin или список model ID через запятую",
    )
    parser.add_argument("--key", help="ключ Vibemode для автоматического запуска")
    parser.add_argument("--replace-key", action="store_true", help="заменить сохраненный ключ")
    parser.add_argument("--non-interactive", action="store_true", help="не спрашивать ключ в терминале")
    parser.add_argument("--skip-api-check", action="store_true", help="не проверять API")
    parser.add_argument("--skip-app-patch", action="store_true", help="не патчить приложение Cursor")
    parser.add_argument("--deep-api-check", action="store_true", help="проверить каждую модель коротким запросом")
    parser.add_argument("--no-save-key", action="store_true", help="не сохранять ключ локально")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cursor-vibemode", description="Подключение Vibemode к Cursor")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Показать диагностику Cursor")
    add_common_db_args(doctor)
    add_app_args(doctor)
    doctor.set_defaults(func=command_doctor)

    status = sub.add_parser("status", help="Показать состояние подключения")
    add_common_db_args(status)
    status.set_defaults(func=command_status)

    setup = sub.add_parser("setup", help="Подключить Vibemode к Cursor")
    add_setup_args(setup)
    setup.set_defaults(func=command_setup)

    repair = sub.add_parser("repair", help="Восстановить подключение Vibemode")
    add_setup_args(repair)
    repair.set_defaults(func=command_repair)

    verify = sub.add_parser("verify", help="Проверить API и модели")
    add_common_db_args(verify)
    verify.add_argument("--base-url")
    verify.add_argument("--models", help="auto, builtin или список model ID через запятую")
    verify.add_argument("--key", help="ключ Vibemode; по умолчанию читается из Cursor")
    verify.add_argument("--models-only", action="store_true", help="проверить только каталог моделей")
    verify.set_defaults(func=command_verify)

    enable = sub.add_parser("enable", help="Включить Vibemode")
    add_common_db_args(enable)
    add_write_safety_args(enable)
    enable.set_defaults(func=command_enable)

    disable = sub.add_parser("disable", help="Выключить Vibemode")
    add_common_db_args(disable)
    add_write_safety_args(disable)
    disable.set_defaults(func=command_disable)

    toggle = sub.add_parser("toggle", help="Переключить Vibemode")
    add_common_db_args(toggle)
    add_write_safety_args(toggle)
    toggle.set_defaults(func=command_toggle)

    watch = sub.add_parser("watch", help="Следить, чтобы Cursor не выключал Vibemode")
    add_common_db_args(watch)
    watch.add_argument("--interval", type=int, default=30, help="интервал проверки в секундах")
    watch.add_argument("--count", type=int, default=0, help="сколько проверок выполнить")
    watch.add_argument("--once", action="store_true", help="проверить один раз и выйти")
    watch.add_argument("--verbose", action="store_true", help="показывать каждую проверку")
    watch.set_defaults(func=command_watch)

    remove = sub.add_parser("remove", help="Удалить подключение Vibemode")
    add_common_db_args(remove)
    add_write_safety_args(remove)
    remove.add_argument("--forget-key", action="store_true", help="удалить локально сохраненный ключ")
    remove.set_defaults(func=command_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    if raw_args == ["adapter", "serve"]:
        try:
            run_adapter()
        except KeyboardInterrupt:
            return 130
        return 0
    parser = build_parser()
    args = parser.parse_args(raw_args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    except CursorVibemodeError as error:
        print(format_error(error), file=sys.stderr)
        return 1
    except Exception as error:
        wrapped = CursorVibemodeError(
            "UNEXPECTED_ERROR",
            "неожиданная ошибка",
            "Скрипт остановился на необработанном исключении.",
            "передай этот вывод разработчику.",
            repr(error),
        )
        print(format_error(wrapped), file=sys.stderr)
        return 1
