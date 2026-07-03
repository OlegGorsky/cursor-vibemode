# cursor-vibemode

`cursor-vibemode` настраивает Cursor на работу через Vibemode/OpenAI-compatible
API. Скрипт патчит реальное хранилище Cursor `state.vscdb`: записывает ключ,
включает OpenAI BYOK, прописывает base URL и добавляет модели Vibemode в список
доступных моделей.

## Быстрый запуск

Перед запуском полностью закрой Cursor.

Linux, macOS или WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i.ps1 | iex
```

Windows-скрипт настраивает Cursor в Windows и автоматически пробует настроить
WSL, если `wsl.exe` есть и default distro уже инициализирован. Если WSL не
установлен или не готов, он просто пропускается.

Терминал попросит вставить Vibemode API key скрытым вводом. В обычном терминале
будет показываться одна `*` на каждый символ.

## Что делает скрипт

1. находит Cursor `state.vscdb`;
2. проверяет, что Cursor закрыт;
3. делает backup базы;
4. записывает ключ в `cursorAuth/openAIKey`;
5. выставляет `openAIBaseUrl = https://api.vibemod.pro/v1`;
6. включает `useOpenAIKey = true`;
7. добавляет модели Vibemode;
8. проверяет API через `/v1/models`.

После успешной настройки открой Cursor заново.

## Пути Cursor DB

Linux:

```text
~/.config/Cursor/User/globalStorage/state.vscdb
```

macOS:

```text
~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
```

Windows:

```text
%APPDATA%\Cursor\User\globalStorage\state.vscdb
```

WSL обычно использует Windows Cursor DB через `/mnt/c/...`. Скрипт умеет
находить этот путь автоматически. Если внутри WSL установлен отдельный Linux
Cursor и есть `~/.config/Cursor/User/globalStorage/state.vscdb`, он тоже может
быть настроен.

## Что именно меняется

В SQLite-базе Cursor меняются записи:

- `cursorAuth/openAIKey`
- `src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser`
- `__$__targetStorageMarker`

Перед изменением создается backup рядом с базой:

```text
state.vscdb.bak-YYYYmmdd-HHMMSS
```

## Windows: полезные варианты

Взять ключ из буфера обмена:

```powershell
$env:CURSOR_VIBEMODE_KEY_FROM_CLIPBOARD='1'; irm https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i.ps1 | iex; Remove-Item Env:\CURSOR_VIBEMODE_KEY_FROM_CLIPBOARD
```

Пропустить проверку API:

```powershell
$env:CURSOR_VIBEMODE_SKIP_API_CHECK='1'; irm https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i.ps1 | iex; Remove-Item Env:\CURSOR_VIBEMODE_SKIP_API_CHECK
```

Настроить конкретный WSL-дистрибутив:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i.ps1))) -WslDistro Ubuntu
```

Отключить WSL-часть:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i.ps1))) -NoWsl
```

## Linux/macOS/WSL: полезные варианты

Пропустить проверку API:

```bash
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash -s -- --skip-api-check
```

Указать путь к Cursor DB вручную:

```bash
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash -s -- --db ~/.config/Cursor/User/globalStorage/state.vscdb
```

Автоматический запуск без prompt:

```bash
export CURSOR_VIBEMODE_KEY=sk-...
curl -fsSL https://raw.githubusercontent.com/OlegGorsky/cursor-vibemode/main/i | bash -s -- --non-interactive
unset CURSOR_VIBEMODE_KEY
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

Linux/macOS/WSL:

- `bash`
- `curl`
- `tar`
- `python3`

Windows:

- PowerShell
- Python 3 в `PATH` или Python Launcher `py.exe`
- Cursor, открытый хотя бы один раз
- WSL опционален
