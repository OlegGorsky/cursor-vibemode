# cursor-vibemode

`cursor-vibemode` настраивает Cursor на работу через Vibemode/OpenAI-compatible API.

Скрипт делает то, что обычная настройка Cursor часто не доводит до рабочего
состояния: патчит реальное хранилище Cursor `state.vscdb`, записывает ключ,
включает OpenAI BYOK, прописывает base URL и добавляет модели Vibemode в список
доступных моделей.

## Быстрый запуск

Закрой Cursor полностью, затем выполни:

```bash
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash
```

Терминал попросит вставить Vibemode API key скрытым вводом. В обычном терминале
будет показываться одна `*` на каждый символ. После ввода скрипт:

1. найдет Cursor `state.vscdb`;
2. сделает backup базы;
3. запишет ключ в `cursorAuth/openAIKey`;
4. выставит `openAIBaseUrl = https://api.vibemod.pro/v1`;
5. включит `useOpenAIKey = true`;
6. добавит модели Vibemode;
7. проверит API через `/v1/models`.

После успешной настройки открой Cursor заново.

## Что именно меняется

Cursor хранит AI-настройки не в обычном `settings.json`, а в SQLite-базе:

```text
~/.config/Cursor/User/globalStorage/state.vscdb
```

Скрипт меняет записи:

- `cursorAuth/openAIKey`
- `src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser`
- `__$__targetStorageMarker`

Перед изменением создается backup рядом с базой:

```text
state.vscdb.bak-YYYYmmdd-HHMMSS
```

## Локальный запуск из клона

```bash
git clone https://github.com/OlegGorsky/cursor-vibemode.git
cd cursor-vibemode
./cursor-vibemode doctor
./cursor-vibemode setup
```

Команды:

```bash
./cursor-vibemode doctor
./cursor-vibemode status
./cursor-vibemode setup --model gpt-5.4
./cursor-vibemode disable
./cursor-vibemode enable
./cursor-vibemode remove --forget-key
```

## Опции

Пропустить проверку API:

```bash
./cursor-vibemode setup --skip-api-check
```

Указать путь к Cursor DB вручную:

```bash
./cursor-vibemode setup --db ~/.config/Cursor/User/globalStorage/state.vscdb
```

Автоматический запуск без prompt:

```bash
CURSOR_VIBEMODE_KEY=sk-... ./cursor-vibemode setup --non-interactive
```

Через GitHub bootstrap с опциями:

```bash
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash -s -- --skip-api-check
```

## Важно

- Перед `setup`, `enable`, `disable` и `remove` Cursor должен быть закрыт.
- Скрипт не читает `~/.codex`, `~/.codex2` и `CODEX_KEY`.
- Обычный `setup` получает ключ прямо в терминале.
- Ключ может быть сохранен только в локальный cache `~/.cursor-vibemode/auth.json`.
- Если Cursor не был открыт ни разу, `state.vscdb` может еще не существовать.

## Проверка после установки

```bash
./cursor-vibemode status
```

Ожидаемые признаки:

```text
OpenAI key: saved
useOpenAIKey: True
openAIBaseUrl: https://api.vibemod.pro/v1
composerModel: gpt-5.4
```

## Требования

- Linux/macOS с `bash`, `curl`, `tar`, `python3`
- установленный и хотя бы один раз открытый Cursor

На NixOS дополнительных пакетов обычно не нужно, если `curl`, `tar` и `python3`
есть в системном профиле.
