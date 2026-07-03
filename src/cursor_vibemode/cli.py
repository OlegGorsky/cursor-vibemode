from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import check_models
from .cursor_db import (
    apply_setup,
    read_openai_key,
    read_status,
    remove_openai_key,
    set_openai_enabled,
)
from .keys import remove_local_key, resolve_api_key, save_local_key
from .paths import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    VIBEMODE_MODELS,
    candidate_db_paths,
    cursor_processes,
    find_cursor_db,
    local_auth_path,
    mask_secret,
)


def parse_model_list(value: str | None) -> list[str]:
    if not value:
        return list(VIBEMODE_MODELS)
    models = [item.strip() for item in value.split(",") if item.strip()]
    return models or list(VIBEMODE_MODELS)


def require_db(path: str | None) -> Path:
    db_path = find_cursor_db(path)
    if db_path:
        return db_path
    checked = "\n".join(f"  - {p}" for p in candidate_db_paths())
    if path:
        checked = f"  - {Path(path).expanduser()}"
    raise RuntimeError(f"Cursor state.vscdb not found. Checked:\n{checked}")


def ensure_cursor_closed(force: bool) -> None:
    running = cursor_processes()
    if running and not force:
        joined = ", ".join(running)
        raise RuntimeError(
            "Cursor appears to be running. Close it fully first, or pass --force. "
            f"Processes: {joined}"
        )


def print_status(db_path: Path) -> int:
    status = read_status(db_path)
    print(f"db: {status.db_path}")
    print(f"ItemTable: {'yes' if status.has_item_table else 'no'}")
    print(f"OpenAI key: {'saved' if status.has_key else 'missing'}")
    print(f"useOpenAIKey: {status.use_openai_key}")
    print(f"openAIBaseUrl: {status.base_url or 'missing'}")
    print(f"composerModel: {status.composer_model or 'missing'}")
    visible = [m for m in status.registered_models if m in VIBEMODE_MODELS]
    print(f"vibemode models: {', '.join(visible) if visible else 'missing'}")
    return 0 if status.has_item_table else 2


def command_status(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    return print_status(db_path)


def command_doctor(args: argparse.Namespace) -> int:
    db_path = find_cursor_db(args.db)
    print("cursor-vibemode doctor")
    print(f"local auth: {local_auth_path()}")
    print(f"Cursor processes: {', '.join(cursor_processes()) or 'none'}")
    print("Candidate DB paths:")
    for path in candidate_db_paths():
        print(f"  - {path} {'[found]' if path.is_file() else '[missing]'}")
    if db_path:
        print("")
        return print_status(db_path)
    print("")
    print("Cursor DB not found. Install and open Cursor once, then run setup again.")
    return 2


def command_setup(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    existing_key = "" if args.replace_key else read_openai_key(db_path)
    result = resolve_api_key(
        explicit_key=args.key,
        replace_key=args.replace_key,
        non_interactive=args.non_interactive,
        cursor_key=existing_key,
    )
    base_url = args.base_url.rstrip("/")
    models = parse_model_list(args.models)
    backups = apply_setup(
        db_path,
        api_key=result.value,
        base_url=base_url,
        model_id=args.model,
        model_ids=models,
        backup=not args.no_backup,
    )
    if not args.no_save_key:
        save_local_key(result.value)

    print(f"db patched: {db_path}")
    print(f"key source: {result.source} ({mask_secret(result.value)})")
    print(f"base URL: {base_url}")
    print(f"model: {args.model}")
    if backups:
        print("backups:")
        for backup in backups:
            print(f"  - {backup}")

    if args.skip_api_check:
        print("API check: skipped")
        return 0
    model_ids = check_models(base_url, result.value)
    print(f"API check: ok ({len(model_ids)} models)")
    shown = ", ".join(model_ids[:8])
    if shown:
        print(f"models: {shown}{'...' if len(model_ids) > 8 else ''}")
    return 0


def command_enable(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = set_openai_enabled(db_path, True, backup=not args.no_backup)
    print(f"OpenAI BYOK enabled in {db_path}")
    for backup in backups:
        print(f"backup: {backup}")
    return 0


def command_disable(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = set_openai_enabled(db_path, False, backup=not args.no_backup)
    print(f"OpenAI BYOK disabled in {db_path}")
    for backup in backups:
        print(f"backup: {backup}")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    db_path = require_db(args.db)
    ensure_cursor_closed(args.force)
    backups = remove_openai_key(db_path, backup=not args.no_backup)
    removed_local = remove_local_key() if args.forget_key else False
    print(f"OpenAI BYOK removed from {db_path}")
    print(f"local key removed: {'yes' if removed_local else 'no'}")
    for backup in backups:
        print(f"backup: {backup}")
    return 0


def add_common_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="Path to Cursor User/globalStorage/state.vscdb")


def add_write_safety_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force", action="store_true", help="Write even if Cursor is running")
    parser.add_argument("--no-backup", action="store_true", help="Do not backup state.vscdb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cursor-vibemode")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show Cursor path diagnostics")
    add_common_db_args(doctor)
    doctor.set_defaults(func=command_doctor)

    status = sub.add_parser("status", help="Inspect Cursor BYOK state")
    add_common_db_args(status)
    status.set_defaults(func=command_status)

    setup = sub.add_parser("setup", help="Patch Cursor for Vibemode BYOK")
    add_common_db_args(setup)
    add_write_safety_args(setup)
    setup.add_argument("--base-url", default=DEFAULT_BASE_URL)
    setup.add_argument("--model", default=DEFAULT_MODEL)
    setup.add_argument("--models", help="Comma-separated model IDs to register")
    setup.add_argument("--key", help="API key for automation. Default setup prompts.")
    setup.add_argument("--replace-key", action="store_true")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--skip-api-check", action="store_true")
    setup.add_argument("--no-save-key", action="store_true")
    setup.set_defaults(func=command_setup)

    enable = sub.add_parser("enable", help="Set useOpenAIKey=true")
    add_common_db_args(enable)
    add_write_safety_args(enable)
    enable.set_defaults(func=command_enable)

    disable = sub.add_parser("disable", help="Set useOpenAIKey=false")
    add_common_db_args(disable)
    add_write_safety_args(disable)
    disable.set_defaults(func=command_disable)

    remove = sub.add_parser("remove", help="Disable BYOK and delete Cursor key")
    add_common_db_args(remove)
    add_write_safety_args(remove)
    remove.add_argument("--forget-key", action="store_true")
    remove.set_defaults(func=command_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
