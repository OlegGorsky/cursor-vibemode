from __future__ import annotations

import argparse
import time
from pathlib import Path

from .api import EndpointCheck, check_model_endpoints, check_models
from .cursor_db import apply_setup, read_openai_key, read_status, set_openai_enabled
from .keys import resolve_api_key, save_local_key
from .paths import DEFAULT_BASE_URL, VIBEMODE_MODELS, mask_secret
from .url_safety import host_warnings


def parse_model_list(value: str | None, api_models: list[str] | None = None) -> list[str]:
    if not value or value.lower() == "auto":
        if api_models:
            return list(dict.fromkeys(api_models))
        return list(VIBEMODE_MODELS)
    if value.lower() == "builtin":
        return list(VIBEMODE_MODELS)
    models = [item.strip() for item in value.split(",") if item.strip()]
    return models or list(VIBEMODE_MODELS)


def setup_cursor(
    args: argparse.Namespace,
    *,
    db_path: Path,
    title: str,
) -> int:
    existing_key = "" if args.replace_key else read_openai_key(db_path)
    result = resolve_api_key(
        explicit_key=args.key,
        replace_key=args.replace_key,
        non_interactive=args.non_interactive,
        cursor_key=existing_key,
    )
    base_url = args.base_url.rstrip("/")
    for warning in host_warnings(base_url):
        print(f"warning: {warning}")

    api_models = fetch_api_models(args, base_url, result.value)
    models = parse_model_list(args.models, api_models)
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

    print_setup_result(title, db_path, result.source, result.value, base_url, args.model, models)
    for backup in backups:
        print(f"backup: {backup}")
    if args.skip_api_check:
        print("API check: skipped")
        return 0
    print_api_models(api_models, models)
    if args.deep_api_check:
        return print_endpoint_checks(check_model_endpoints(base_url, result.value, models))
    return 0


def fetch_api_models(args: argparse.Namespace, base_url: str, api_key: str) -> list[str]:
    if args.skip_api_check:
        return []
    models = check_models(base_url, api_key)
    if not models:
        raise RuntimeError("API /models returned no model IDs. Use --skip-api-check for manual setup.")
    print(f"API /models: ok ({len(models)} models)")
    return models


def print_setup_result(
    title: str,
    db_path: Path,
    key_source: str,
    api_key: str,
    base_url: str,
    model: str,
    models: list[str],
) -> None:
    print(f"{title}: {db_path}")
    print(f"key source: {key_source} ({mask_secret(api_key)})")
    print(f"base URL: {base_url}")
    print(f"model: {model}")
    print(f"registered models: {len(models)}")


def print_api_models(api_models: list[str], configured: list[str]) -> None:
    shown = ", ".join(api_models[:8])
    if shown:
        print(f"models: {shown}{'...' if len(api_models) > 8 else ''}")
    missing = [model for model in configured if model not in api_models]
    if missing:
        print(f"warning: configured models not returned by /models: {', '.join(missing)}")


def print_endpoint_checks(checks: list[EndpointCheck]) -> int:
    failed = [check for check in checks if not check.ok]
    for check in checks:
        state = "ok" if check.ok else "failed"
        print(f"{check.model_id}: {check.endpoint} {state}")
        if not check.ok:
            print(f"  {check.detail}")
    if failed:
        print(f"API endpoint check: failed ({len(failed)}/{len(checks)})")
        return 1
    print(f"API endpoint check: ok ({len(checks)} models)")
    return 0


def verify_api(args: argparse.Namespace, db_path: Path | None) -> int:
    status = read_status(db_path) if db_path else None
    api_key = args.key or (read_openai_key(db_path) if db_path else "")
    if not api_key:
        raise RuntimeError("API key not found. Pass --key or run setup first.")
    base_url = (args.base_url or (status.base_url if status else "") or DEFAULT_BASE_URL).rstrip("/")
    api_models = check_models(base_url, api_key)
    if not api_models:
        raise RuntimeError("API /models returned no model IDs.")
    print(f"API /models: ok ({len(api_models)} models)")
    models = parse_model_list(args.models, api_models)
    print_api_models(api_models, models)
    if args.models_only:
        return 0
    return print_endpoint_checks(check_model_endpoints(base_url, api_key, models))


def watch_openai_key(args: argparse.Namespace, db_path: Path) -> int:
    if args.interval < 1:
        raise RuntimeError("--interval must be at least 1 second")
    if not read_status(db_path).has_key:
        raise RuntimeError("Cursor OpenAI key is missing. Run setup first.")
    print(f"watching useOpenAIKey in {db_path}")
    cycles = 0
    while True:
        status = read_status(db_path)
        if status.use_openai_key is False:
            set_openai_enabled(db_path, True, backup=False)
            print(f"{time.strftime('%H:%M:%S')} re-enabled useOpenAIKey")
        elif args.verbose:
            print(f"{time.strftime('%H:%M:%S')} useOpenAIKey={status.use_openai_key}")
        cycles += 1
        if args.once or (args.count and cycles >= args.count):
            return 0
        time.sleep(args.interval)
