from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from .api import EndpointCheck, check_model_endpoints, check_models
from .adapter_service import ensure_adapter
from .cursor_app import CursorAppPatchReport, patch_cursor_app
from .cursor_db import apply_setup, read_openai_key, read_status, set_openai_enabled
from .errors import CursorVibemodeError
from .keys import resolve_api_key, save_local_key
from .models import provider_model_id
from .paths import DEFAULT_BASE_URL, VIBEMODE_MODELS
from .surfaces import detect_surfaces
from .url_safety import host_warnings


@dataclass(frozen=True)
class ApiCatalog:
    models: list[str]
    checked: bool


def parse_model_list(value: str | None, api_models: list[str] | None = None) -> list[str]:
    if not value or value.lower() == "auto":
        if api_models:
            return list(dict.fromkeys(api_models))
        return list(VIBEMODE_MODELS)
    if value.lower() == "builtin":
        return list(VIBEMODE_MODELS)
    models = list(
        dict.fromkeys(
            provider_model_id(item.strip()) for item in value.split(",") if item.strip()
        )
    )
    return models or list(VIBEMODE_MODELS)


def model_count(value: int) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        word = "моделей"
    elif value % 10 == 1:
        word = "модель"
    elif 2 <= value % 10 <= 4:
        word = "модели"
    else:
        word = "моделей"
    return f"{value} {word}"


def setup_cursor(
    args: argparse.Namespace,
    *,
    db_path: Path,
    title: str,
) -> int:
    surfaces_before = detect_surfaces(db_path)
    app_report = None
    if not getattr(args, "skip_app_patch", True):
        app_report = patch_cursor_app(getattr(args, "app_root", None))
    existing_key = "" if args.replace_key else read_openai_key(db_path)
    result = resolve_api_key(
        explicit_key=args.key,
        replace_key=args.replace_key,
        non_interactive=args.non_interactive,
        cursor_key=existing_key,
    )
    base_url = args.base_url.rstrip("/")
    warnings = host_warnings(base_url)

    catalog = fetch_api_models(args, base_url, result.value, warnings)
    models = parse_model_list(args.models, catalog.models)
    adapter = ensure_adapter(base_url, result.value)
    selected_model = provider_model_id(args.model)
    backups = apply_setup(
        db_path,
        api_key=result.value,
        base_url=adapter.base_url,
        model_id=selected_model,
        model_ids=models,
        backup=not args.no_backup,
    )
    if not args.no_save_key:
        save_local_key(result.value)

    surfaces_after = detect_surfaces(db_path)
    print_setup_result(
        title,
        surfaces_after if surfaces_after.has_settings else surfaces_before,
        selected_model,
        models,
        len(backups),
        warnings,
        app_report,
    )
    if args.skip_api_check:
        print("Проверка API: пропущена")
        return 0
    if catalog.checked:
        print_api_models(catalog.models, models)
    else:
        print("Проверка API: каталог не проверен, использован резервный список моделей")
    if args.deep_api_check:
        print_endpoint_checks(check_model_endpoints(base_url, result.value, models))
    return 0


def fetch_api_models(
    args: argparse.Namespace,
    base_url: str,
    api_key: str,
    warnings: list[str],
) -> ApiCatalog:
    if args.skip_api_check:
        return ApiCatalog([], False)
    try:
        models = check_models(base_url, api_key)
    except RuntimeError as error:
        detail = str(error)
        if is_cloudflare_browser_block(detail):
            warnings.append(
                "Cloudflare заблокировал терминальную проверку каталога. "
                "Настройка продолжена с резервным списком моделей."
            )
            return ApiCatalog([], False)
        raise CursorVibemodeError(
            "API_CATALOG_CHECK_FAILED",
            "не удалось проверить каталог моделей Vibemode",
            "API не ответил на запрос списка моделей.",
            "проверь ключ, интернет и base URL или запусти с --skip-api-check.",
            detail,
        ) from error
    if not models:
        raise CursorVibemodeError(
            "API_CATALOG_EMPTY",
            "каталог моделей пуст",
            "Vibemode API ответил, но не вернул ни одной модели.",
            "проверь ключ и провайдера или запусти с явным --models.",
        )
    return ApiCatalog(models, True)


def is_cloudflare_browser_block(detail: str) -> bool:
    lower = detail.lower()
    return (
        "error 1010" in lower
        or "browser_signature_banned" in lower
        or '"error_code":1010' in lower
        or '"cloudflare_error":true' in lower
    )


def print_setup_result(
    title: str,
    surfaces,
    model: str,
    models: list[str],
    backup_count: int,
    warnings: list[str],
    app_report: CursorAppPatchReport | None = None,
) -> None:
    action = "Восстановление завершено" if title == "repaired" else "Настройка завершена"
    print(f"{action}: Vibemode подключен к Cursor.")
    print(f"Подключено для: {surfaces.display}")
    if app_report:
        print(f"Локальный режим Cursor: {app_report.display}")
        if app_report.launcher:
            print(f"Запуск Cursor: {app_report.launcher}")
    print(f"Моделей подключено: {len(models)}")
    print(f"Основная модель: {model}")
    if backup_count:
        print("Резервная копия: создана")
    for warning in warnings:
        print(f"Предупреждение: {warning}")


def print_api_models(api_models: list[str], configured: list[str]) -> None:
    print(f"Проверка API: каталог доступен ({model_count(len(api_models))})")
    missing = [model for model in configured if model not in api_models]
    if missing:
        print(f"Предупреждение: не найдены в каталоге API: {', '.join(missing)}")


def print_endpoint_checks(checks: list[EndpointCheck]) -> int:
    failed = [check for check in checks if not check.ok]
    if failed:
        details = "; ".join(
            f"{check.model_id} -> {check.endpoint}: {check.detail}" for check in failed
        )
        raise CursorVibemodeError(
            "API_MODEL_CHECK_FAILED",
            "часть моделей не прошла глубокую проверку",
            f"Не прошли проверку: {model_count(len(failed))}. Всего проверено: {model_count(len(checks))}.",
            "проверь совместимость endpoint у провайдера или запусти обычный setup без --deep-api-check.",
            details,
        )
    print(f"Глубокая проверка API: успешно ({model_count(len(checks))})")
    return 0


def verify_api(args: argparse.Namespace, db_path: Path | None) -> int:
    status = read_status(db_path) if db_path else None
    api_key = args.key or (read_openai_key(db_path) if db_path else "")
    if not api_key:
        raise CursorVibemodeError(
            "API_KEY_MISSING",
            "ключ Vibemode не найден",
            "В Cursor еще не сохранен API-ключ, и --key не был передан.",
            "запусти setup и вставь ключ в терминале.",
        )
    base_url = (args.base_url or (status.base_url if status else "") or DEFAULT_BASE_URL).rstrip("/")
    try:
        api_models = check_models(base_url, api_key)
    except RuntimeError as error:
        raise CursorVibemodeError(
            "API_CATALOG_CHECK_FAILED",
            "не удалось проверить каталог моделей Vibemode",
            "API не ответил на запрос списка моделей.",
            "проверь ключ, интернет и base URL.",
            str(error),
        ) from error
    if not api_models:
        raise CursorVibemodeError(
            "API_CATALOG_EMPTY",
            "каталог моделей пуст",
            "Vibemode API ответил, но не вернул ни одной модели.",
            "проверь ключ и провайдера.",
        )
    models = parse_model_list(args.models, api_models)
    print_api_models(api_models, models)
    if args.models_only:
        return 0
    return print_endpoint_checks(check_model_endpoints(base_url, api_key, models))


def watch_openai_key(args: argparse.Namespace, db_path: Path) -> int:
    if args.interval < 1:
        raise CursorVibemodeError(
            "WATCH_INTERVAL_INVALID",
            "неверный интервал наблюдения",
            "Интервал должен быть не меньше 1 секунды.",
            "запусти watch с --interval 30 или без этого параметра.",
        )
    if not read_status(db_path).has_key:
        raise CursorVibemodeError(
            "API_KEY_MISSING",
            "ключ Vibemode не найден",
            "Наблюдение можно включить только после настройки ключа.",
            "сначала запусти setup.",
        )
    print("Наблюдение запущено. Если Cursor выключит Vibemode, скрипт включит его обратно.")
    cycles = 0
    repaired = False
    while True:
        status = read_status(db_path)
        if status.use_openai_key is False:
            set_openai_enabled(db_path, True, backup=False)
            repaired = True
            print(f"{time.strftime('%H:%M:%S')} Vibemode был выключен Cursor и включен обратно.")
        elif args.verbose:
            print(f"{time.strftime('%H:%M:%S')} Vibemode включен")
        cycles += 1
        if args.once or (args.count and cycles >= args.count):
            if not repaired and args.once:
                print("Проверка завершена: Vibemode включен.")
            return 0
        time.sleep(args.interval)
